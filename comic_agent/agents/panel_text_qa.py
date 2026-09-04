"""Proposal-only source-text QA for approved panel plans."""

from __future__ import annotations

from collections.abc import Iterable

from comic_agent.agents.specs import AgentSpec
from comic_agent.providers.llm import LLMProvider
from comic_agent.providers.openai_compatible import ProviderResponseError
from comic_agent.schemas.base import EvidenceRefV1, RecordStatus
from comic_agent.schemas.comic_planning import PanelPlanV1
from comic_agent.schemas.qa import (
    PanelTextQAFindingV1,
    PanelTextQAInferenceV1,
    PanelTextQAIssueSeverity,
    PanelTextQAProposalV1,
)
from comic_agent.schemas.source import SourceChunkV1
from comic_agent.services.id_service import stable_id


class PanelTextQAAgent:
    """Compare planned visual facts with the same trusted text used upstream."""

    PROMPT_VERSION = "panel-text-qa-v1"
    spec = AgentSpec(
        agent_id="panel-text-qa",
        version="1.0",
        reads=["PanelPlanV1", "SourceChunkV1"],
        output_schema="PanelTextQAProposalV1",
        tools=[],
        can_write_canonical_data=False,
        requires_evidence=True,
        max_context_chunks=8,
        confidence_threshold=0.0,
    )

    def __init__(self, provider: LLMProvider, *, provider_model: str = "unconfigured") -> None:
        self._provider = provider
        self._provider_model = provider_model
        self._provider_request_count = 0

    @property
    def provider_request_count(self) -> int:
        return self._provider_request_count

    @property
    def cache_identity(self) -> dict[str, str]:
        return {
            "agent_id": self.spec.agent_id,
            "agent_version": self.spec.version,
            "prompt_version": self.PROMPT_VERSION,
            "provider_model": self._provider_model,
        }

    def run(
        self,
        *,
        project_id: str,
        panels: list[PanelPlanV1],
        source_chunks: Iterable[SourceChunkV1],
    ) -> PanelTextQAProposalV1:
        """Return one candidate QA proposal without database access or writes."""

        self._provider_request_count = 0
        if not panels:
            raise ValueError("panel text QA requires at least one panel")
        if any(panel.project_id != project_id for panel in panels):
            raise ValueError("panel text QA project mismatch")
        chunks = list(source_chunks)
        if len(chunks) > self.spec.max_context_chunks:
            raise ValueError("panel text QA exceeds trusted source chunk budget")
        chunks_by_id = {chunk.chunk_id: chunk for chunk in chunks}
        evidence = self._evidence_allowlist(panels, chunks_by_id)
        request = self._request(panels, chunks, evidence)
        inference = self._generate(request)
        try:
            findings = self._materialize_findings(inference, panels, evidence)
        except ProviderResponseError as exc:
            raw_codes = exc.diagnostics.get("schema_error_rule_codes", [])
            repair = self._request(
                panels,
                chunks,
                evidence,
                repair_codes=raw_codes if isinstance(raw_codes, list) else [],
            )
            inference = self._generate(repair)
            findings = self._materialize_findings(inference, panels, evidence)
        return PanelTextQAProposalV1(
            proposal_id=stable_id(
                "panel-text-qa", project_id, *(panel.panel_id for panel in panels)
            ),
            project_id=project_id,
            status=RecordStatus.CANDIDATE,
            checked_panel_ids=[panel.panel_id for panel in panels],
            findings=findings,
            evidence_refs=evidence,
            passed=not any(
                finding.severity == PanelTextQAIssueSeverity.BLOCKING
                for finding in findings
            ),
            summary=inference.summary,
            confidence=inference.confidence,
        )

    def _generate(self, request: dict[str, object]) -> PanelTextQAInferenceV1:
        self._provider_request_count += 1
        return self._provider.structured_generate(request, PanelTextQAInferenceV1)

    @staticmethod
    def _evidence_allowlist(
        panels: list[PanelPlanV1], chunks_by_id: dict[str, SourceChunkV1]
    ) -> list[EvidenceRefV1]:
        evidence: list[EvidenceRefV1] = []
        for panel in panels:
            for ref in panel.evidence_refs:
                chunk = chunks_by_id.get(ref.chunk_id)
                if chunk is None:
                    raise ValueError("panel text QA evidence is outside trusted source")
                if ref.quote_start is not None and ref.quote_end is not None:
                    source_quote = chunk.text[ref.quote_start : ref.quote_end]
                    if ref.quote_text is not None and source_quote != ref.quote_text:
                        raise ValueError("panel text QA evidence span does not match source")
                elif ref.quote_text is not None and ref.quote_text not in chunk.text:
                    raise ValueError("panel text QA evidence quote does not match source")
                if ref not in evidence:
                    evidence.append(ref)
        if not evidence:
            raise ValueError("panel text QA requires evidence")
        return evidence

    @staticmethod
    def _materialize_findings(
        inference: PanelTextQAInferenceV1,
        panels: list[PanelPlanV1],
        evidence: list[EvidenceRefV1],
    ) -> list[PanelTextQAFindingV1]:
        findings: list[PanelTextQAFindingV1] = []
        for index, item in enumerate(inference.findings):
            if item.panel_index >= len(panels):
                raise ProviderResponseError(
                    "panel text QA selected an unknown panel",
                    diagnostics={
                        "schema_error_rule_codes": ["PANEL_INDEX_OUT_OF_RANGE"],
                        "expected_output_schema": "PanelTextQAInferenceV1",
                    },
                )
            if any(evidence_index >= len(evidence) for evidence_index in item.evidence_indexes):
                raise ProviderResponseError(
                    "panel text QA selected unknown evidence",
                    diagnostics={
                        "schema_error_rule_codes": ["EVIDENCE_INDEX_OUT_OF_RANGE"],
                        "expected_output_schema": "PanelTextQAInferenceV1",
                    },
                )
            panel = panels[item.panel_index]
            findings.append(
                PanelTextQAFindingV1(
                    finding_id=stable_id(
                        "panel-text-qa-finding",
                        panel.panel_id,
                        item.issue_code,
                        index,
                    ),
                    panel_id=panel.panel_id,
                    issue_code=item.issue_code,
                    severity=item.severity,
                    evidence_refs=[evidence[i] for i in item.evidence_indexes],
                    summary=item.summary,
                )
            )
        return findings

    @staticmethod
    def _request(
        panels: list[PanelPlanV1],
        chunks: list[SourceChunkV1],
        evidence: list[EvidenceRefV1],
        *,
        repair_codes: list[object] | None = None,
    ) -> dict[str, object]:
        safe_codes = [item for item in (repair_codes or []) if isinstance(item, str)][:8]
        return {
            "system_prompt": (
                "You are PanelTextQA. Compare every planned panel only with the supplied exact "
                "source chunks and evidence allowlist. Report BLOCKING only for a direct "
                "contradiction or invented event, character, location, or dialogue. Missing "
                "visual detail and uncertain continuity are WARNING, not BLOCKING. Do not add "
                "facts or quote source text in summaries. Use only supplied integer indexes."
            ),
            "user_prompt": (
                "Return one PanelTextQAInferenceV1 JSON object. Return findings=[] when every "
                "panel is supported."
            ),
            "input_context": {
                "panels": [
                    {
                        "index": index,
                        "plan": panel.model_dump(mode="json", exclude={"evidence_refs"}),
                    }
                    for index, panel in enumerate(panels)
                ],
                "evidence_allowlist": [
                    {"index": index, "evidence_ref": ref.model_dump(mode="json")}
                    for index, ref in enumerate(evidence)
                ],
                "source_chunks": [
                    {"chunk_id": chunk.chunk_id, "text": chunk.text} for chunk in chunks
                ],
                "repair_rule_codes": safe_codes,
                "output_schema": PanelTextQAInferenceV1.model_json_schema(),
            },
        }
