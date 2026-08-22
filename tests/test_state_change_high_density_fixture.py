import json
from pathlib import Path
from typing import TypeVar

import pytest
from pydantic import BaseModel

from comic_agent.agents.state_change_extraction import StateChangeExtractionAgent
from comic_agent.schemas import SourceChunkV1, StateChangeProposalBatchV1
from comic_agent.services.document_parser import DocumentParser

_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "state_change"
_TEXT_PATH = _FIXTURE_DIR / "state_change_high_density_challenge_v1.txt"
_FIXTURE_PATH = _FIXTURE_DIR / "state_change_high_density_challenge_v1.json"
_CONSOLE_MANIFEST_PATH = _FIXTURE_DIR / "state_change_high_density_console_oracle_v1.json"
_OutputT = TypeVar("_OutputT", bound=BaseModel)


class _FixtureProvider:
    def __init__(self, response: dict[str, object]) -> None:
        self.response = response
        self.requests: list[dict[str, object]] = []

    def structured_generate(
        self,
        request: dict[str, object],
        output_model: type[_OutputT],
    ) -> _OutputT:
        self.requests.append(request)
        return output_model.model_validate(self.response)


def _source_chunk(case: dict[str, object]) -> SourceChunkV1:
    return SourceChunkV1(
        chunk_id=str(case["source_chunk_id"]),
        document_id="state-change-high-density",
        chapter_id="challenge",
        project_id="fixture",
        order=0,
        text=str(case["text"]),
        checksum="fixture-only",
    )


def _response_for_case(case: dict[str, object]) -> dict[str, object]:
    changes: list[dict[str, object]] = []
    for index, expected in enumerate(case["expected_changes"]):
        expected_change = dict(expected)
        quote = str(expected_change["evidence_quote"])
        changes.append(
            {
                "schema_version": "1.3",
                "proposal_id": f"{case['case_id']}-change-{index}",
                "event": {
                    "event_summary": quote,
                    "event_proposal_id": None,
                    "proposal_schema": None,
                    "resolution_status": "UNRESOLVED",
                },
                "target": {
                    "mention_text": expected_change["target_mention"],
                    "target_kind": expected_change["target_kind"],
                    "entity_proposal_id": None,
                    "proposal_schema": None,
                    "resolution_status": "UNRESOLVED",
                },
                "attribute_path": expected_change["attribute_path"],
                "old_value": expected_change["old_value"],
                "new_value": expected_change["new_value"],
                "persistent": expected_change["persistent"],
                "reality_layer": "PRIMARY",
                "evidence_refs": [
                    {
                        "chunk_id": case["source_chunk_id"],
                        "quote_start": None,
                        "quote_end": None,
                        "quote_text": quote,
                    }
                ],
                "new_value_evidence_indexes": [0],
                "persistence_evidence_indexes": [],
                "confidence": 0.9,
            }
        )
    return {
        "schema_version": "1.3",
        "batch_id": f"{case['case_id']}-batch",
        "changes": changes,
    }


def test_high_density_state_change_fixture_is_original_and_structured() -> None:
    text = _TEXT_PATH.read_text(encoding="utf-8")
    fixture = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))

    assert 900 <= len(text.replace("\n", "")) <= 1800
    assert fixture["fixture_type"] == "STATE_CHANGE_HIGH_DENSITY_CHALLENGE_V1"
    assert fixture["source_file"] == (
        "tests/fixtures/state_change/state_change_high_density_challenge_v1.txt"
    )
    assert fixture["cases"]
    for case in fixture["cases"]:
        assert {
            "case_id",
                "source_chunk_id",
                "context_chunk_ids",
            "text",
            "category",
            "risk_tags",
            "expected_changes",
            "forbidden_changes",
            "expects_empty_batch",
            "notes",
        } <= set(case)
        assert case["text"]
        assert case["text"] in text
        assert case["context_chunk_ids"]
        assert len(case["context_chunk_ids"]) == len(set(case["context_chunk_ids"]))
        assert all(
            change["evidence_quote"] in case["text"]
            for change in case["expected_changes"]
        )
        assert case["source_chunk_id"]
        assert case["category"] in {"CANDIDATE", "MULTI_CANDIDATE", "NEGATIVE", "BOUNDARY"}

    source_ids = [case["source_chunk_id"] for case in fixture["cases"]]
    assert len(source_ids) == len(set(source_ids))
    assert set(source_ids) == {f"hd-{index:02d}" for index in range(1, len(source_ids) + 1)}
    assert not any(
        marker in text
        for marker in ("当前合同", "明确完成的发型转换", "记录者把每个对象", "这些话不构成")
    )

    text_by_id = {case["source_chunk_id"]: case["text"] for case in fixture["cases"]}
    for case in fixture["cases"]:
        context_text = "\n".join(text_by_id[chunk_id] for chunk_id in case["context_chunk_ids"])
        assert set(case["context_chunk_ids"]) <= set(text_by_id)
        assert all(
            change["evidence_quote"] in context_text
            for change in case["expected_changes"]
        )
        assert all(
            forbidden.get("evidence_quote") in context_text
            for forbidden in case["forbidden_changes"]
            if forbidden.get("evidence_quote")
        )
        if case["expects_empty_batch"]:
            assert case["expected_changes"] == []


def test_high_density_fixture_covers_required_state_change_families() -> None:
    fixture = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    categories = {case["category"] for case in fixture["cases"]}
    paths = {
        change["attribute_path"]
        for case in fixture["cases"]
        for change in case["expected_changes"]
    }

    assert {"CANDIDATE", "MULTI_CANDIDATE", "NEGATIVE", "BOUNDARY"} <= categories
    assert {
        "health.injury",
        "location",
        "physical.condition",
        "accessibility",
        "possession.holder",
        "quantity",
        "appearance.clothing",
        "appearance.hairstyle",
    } <= paths


def test_fake_provider_accepts_high_density_positive_batches() -> None:
    fixture = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    cases_by_id = {case["source_chunk_id"]: case for case in fixture["cases"]}
    positive_cases = [case for case in fixture["cases"] if not case["expects_empty_batch"]]

    for case in positive_cases:
        context_chunks = [
            _source_chunk(cases_by_id[chunk_id]) for chunk_id in case["context_chunk_ids"]
        ]
        provider = _FixtureProvider(_response_for_case(case))
        batch = StateChangeExtractionAgent(provider).run(
            {
                "source_chunk_ids": case["context_chunk_ids"],
                "source_chunks": context_chunks,
            }
        )

        assert isinstance(batch, StateChangeProposalBatchV1)
        assert provider.requests[0]["input_context"]["source_chunk_ids"] == case[
            "context_chunk_ids"
        ]
        assert batch.schema_version == "1.3"
        assert len(batch.changes) == len(case["expected_changes"])
        assert all(change.event.resolution_status == "UNRESOLVED" for change in batch.changes)
        assert all(change.target.resolution_status == "UNRESOLVED" for change in batch.changes)
        assert all(change.new_value_evidence_indexes == [0] for change in batch.changes)
        assert all(change.persistent is False for change in batch.changes)
        assert all(change.persistence_evidence_indexes == [] for change in batch.changes)


def test_agent_replaces_paraphrased_selected_evidence_with_a_verbatim_anchor() -> None:
    """A source-scoped paraphrase must not exhaust a whole Narrative run.

    The replacement is deterministic and remains inside the selected chunk; it
    is not a model-generated quote or a rebinding to another source.
    """

    fixture = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    case = next(case for case in fixture["cases"] if case["expected_changes"])
    response = _response_for_case(case)
    changes = response["changes"]
    assert isinstance(changes, list)
    first_change = changes[0]
    assert isinstance(first_change, dict)
    evidence_refs = first_change["evidence_refs"]
    assert isinstance(evidence_refs, list)
    first_evidence = evidence_refs[0]
    assert isinstance(first_evidence, dict)
    first_evidence["quote_text"] = "模型改写的非逐字证据"

    chunk = _source_chunk(case)
    batch = StateChangeExtractionAgent(_FixtureProvider(response)).run(
        {
            "source_chunk_ids": [chunk.chunk_id],
            "source_chunks": [chunk],
            "output_recovery": "evidence_validation",
        }
    )

    repaired = batch.changes[0].evidence_refs[0]
    assert repaired.chunk_id == chunk.chunk_id
    assert repaired.quote_text is not None
    assert repaired.quote_text in chunk.text
    assert repaired.quote_start is not None
    assert repaired.quote_end is not None
    assert chunk.text[repaired.quote_start : repaired.quote_end] == repaired.quote_text


def test_agent_does_not_move_paraphrased_evidence_to_an_unrelated_selected_chunk() -> None:
    """The deterministic fallback must retain the provider-selected chunk scope."""

    fixture = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    case = next(case for case in fixture["cases"] if case["expected_changes"])
    unrelated_case = next(
        candidate
        for candidate in fixture["cases"]
        if candidate["source_chunk_id"] != case["source_chunk_id"]
    )
    response = _response_for_case(case)
    changes = response["changes"]
    assert isinstance(changes, list)
    first_change = changes[0]
    assert isinstance(first_change, dict)
    evidence_refs = first_change["evidence_refs"]
    assert isinstance(evidence_refs, list)
    first_evidence = evidence_refs[0]
    assert isinstance(first_evidence, dict)
    first_evidence["chunk_id"] = unrelated_case["source_chunk_id"]
    first_evidence["quote_text"] = "模型改写的非逐字证据"
    source_text = str(case["text"])
    unrelated_text = str(unrelated_case["text"])
    target_mention = next(
        source_text[start : start + width]
        for width in range(8, 1, -1)
        for start in range(len(source_text) - width + 1)
        if source_text[start : start + width] not in unrelated_text
    )
    target = first_change["target"]
    assert isinstance(target, dict)
    target["mention_text"] = target_mention

    with pytest.raises(ValueError, match="cannot replace evidence outside"):
        StateChangeExtractionAgent(_FixtureProvider(response)).run(
            {
                "source_chunk_ids": [
                    case["source_chunk_id"],
                    unrelated_case["source_chunk_id"],
                ],
                "source_chunks": [_source_chunk(case), _source_chunk(unrelated_case)],
                "output_recovery": "evidence_validation",
            }
        )


def test_fake_provider_returns_empty_batch_for_high_density_negative_chunks() -> None:
    fixture = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    cases_by_id = {case["source_chunk_id"]: case for case in fixture["cases"]}
    negative_cases = [case for case in fixture["cases"] if case["expects_empty_batch"]]

    for case in negative_cases:
        context_chunks = [
            _source_chunk(cases_by_id[chunk_id]) for chunk_id in case["context_chunk_ids"]
        ]
        provider = _FixtureProvider(
            {
                "schema_version": "1.3",
                "batch_id": f"{case['case_id']}-empty",
                "changes": [],
            }
        )
        batch = StateChangeExtractionAgent(
            provider
        ).run(
            {
                "source_chunk_ids": case["context_chunk_ids"],
                "source_chunks": context_chunks,
            }
        )

        assert batch.schema_version == "1.3"
        assert batch.changes == []
        assert provider.requests[0]["input_context"]["source_chunk_ids"] == case[
            "context_chunk_ids"
        ]


def test_fake_provider_v13_rejects_legacy_states_array() -> None:
    fixture = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    case = fixture["cases"][0]
    chunk = _source_chunk(case)

    with pytest.raises(ValueError):
        StateChangeExtractionAgent(
            _FixtureProvider(
                {
                    "schema_version": "1.3",
                    "batch_id": "hd-invalid-states",
                    "states": [],
                }
            )
        ).run({"source_chunk_ids": [chunk.chunk_id], "source_chunks": [chunk]})


def test_console_ingest_manifest_matches_actual_txt_chunking() -> None:
    manifest = json.loads(_CONSOLE_MANIFEST_PATH.read_text(encoding="utf-8"))
    text = _TEXT_PATH.read_text(encoding="utf-8")
    parsed = DocumentParser().parse_txt(
        project_id=str(manifest["identity"]["project_id"]),
        filename=str(manifest["identity"]["filename"]),
        text=text,
    )

    chunks = parsed.chunks
    entries = manifest["chunks"]
    assert len(chunks) == len(entries)
    assert manifest["identity"]["random_ids_forbidden"] is True
    for chunk, entry in zip(chunks, entries, strict=True):
        assert chunk.order == entry["order"]
        assert chunk.checksum == entry["checksum"]
        assert entry["anchor"] in chunk.text
        expected_changes = entry["expected_changes"]
        if entry["expects_empty_batch"]:
            assert expected_changes == []
        for expected in expected_changes:
            assert expected["evidence_quote"] in chunk.text
        assert all(
            "evidence_quote" not in forbidden or forbidden["evidence_quote"] in chunk.text
            for forbidden in entry["forbidden_changes"]
        )
