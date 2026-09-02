"""Local harness around existing application services for real-provider Demo calls."""

from pathlib import Path

from fastapi.testclient import TestClient

from comic_agent.demo.timeline_adapter import DemoRecoverableTimelineError
from comic_agent.main import create_app
from comic_agent.schemas.narrative import (
    EntityProposalBatchV1,
    EntityProposalV1,
    EventProposalBatchV1,
    EventProposalV1,
)
from comic_agent.schemas.timeline import (
    ApprovedTimelineBundleV1,
    ReviewGate3Decision,
    TimelineAnalysisProposalV1,
)
from comic_agent.services.id_service import stable_id
from comic_agent.services.review_gate3_service import ReviewGate3Service


class ProductionDemoRuntime:
    """Invoke production-wired workflows in an isolated database."""

    def __init__(self, *, input_path: Path, work_dir: Path, max_chunks: int) -> None:
        self.input_path = input_path
        self.max_chunks = max_chunks
        self.project_id = stable_id(
            "real-comic-demo", input_path.name, input_path.read_text("utf-8")
        )
        work_dir.mkdir(parents=True, exist_ok=True)
        database = work_dir / f"{self.project_id}.db"
        self.app = create_app(database_url=f"sqlite+pysqlite:///{database.as_posix()}")
        self._context = TestClient(self.app)
        self.client = self._context.__enter__()
        self._prepare()

    def close(self) -> None:
        self._context.__exit__(None, None, None)

    def _prepare(self) -> None:
        created = self.client.post(
            "/projects", json={"project_id": self.project_id, "name": "Comic Demo"}
        )
        if created.status_code not in {200, 201, 409}:
            raise RuntimeError(f"production project setup failed: HTTP {created.status_code}")
        with self.input_path.open("rb") as stream:
            imported = self.client.post(
                f"/projects/{self.project_id}/documents/import",
                files={"file": (self.input_path.name, stream, "text/plain")},
            )
        if imported.status_code not in {200, 201}:
            raise RuntimeError(f"production TXT import failed: HTTP {imported.status_code}")
        chapters = self.client.get(f"/projects/{self.project_id}/chapters").json()
        self.chunk_ids: list[str] = []
        for chapter in chapters:
            chunks = self.client.get(f"/chapters/{chapter['chapter_id']}/chunks").json()
            self.chunk_ids.extend(str(item["chunk_id"]) for item in chunks)
            if len(self.chunk_ids) >= self.max_chunks:
                break
        self.chunk_ids = self.chunk_ids[: self.max_chunks]
        if not self.chunk_ids:
            raise RuntimeError("production import produced no SourceChunks")

    def _narrative_call(self, mode: str) -> dict[str, object]:
        response = self.client.post(
            f"/projects/{self.project_id}/agent-runs/narrative-analyst",
            json={
                "mode": mode,
                "chunk_ids": self.chunk_ids,
                "chunk_limit": self.max_chunks,
                "real_llm_requested": True,
            },
        )
        if response.status_code not in {200, 201}:
            raise RuntimeError(f"production Narrative {mode} failed: HTTP {response.status_code}")
        payload: dict[str, object] = response.json()
        status = payload.get("agent_run_status")
        if status != "SUCCEEDED" or not isinstance(payload.get("proposal"), dict):
            reason = payload.get("error_message") or status
            raise RuntimeError(f"production Narrative {mode} failed: {reason}")
        return payload

    def run_narrative(self) -> tuple[list[EntityProposalV1], list[EventProposalV1], int]:
        entity_payload = self._narrative_call("entity_extraction")
        event_payload = self._narrative_call("event_extraction")
        entities = EntityProposalBatchV1.model_validate(entity_payload["proposal"]).entities
        events = EventProposalBatchV1.model_validate(event_payload["proposal"]).events
        return entities, events, 2

    def run_timeline(
        self, events: list[EventProposalV1]
    ) -> tuple[ApprovedTimelineBundleV1, str, list[str], int]:
        before = self.app.state.timeline_agent.provider_request_count
        response = self.client.post(
            f"/projects/{self.project_id}/timeline/analyze",
            json={
                "project_id": self.project_id,
                "mode": "LLM",
                "event_proposals": [item.model_dump(mode="json") for item in events],
                "claim_proposals": [],
                "state_change_proposals": [],
            },
        )
        if response.status_code != 200:
            detail = (
                response.json().get("detail")
                if response.headers.get("content-type", "").startswith("application/json")
                else None
            )
            message = f"production Timeline failed: HTTP {response.status_code}: {detail}"
            recoverable_markers = (
                "provider",
                "schema validation",
                "malformed json",
                "timeout",
                "connection",
                "finish_reason=length",
            )
            if any(marker in str(detail).lower() for marker in recoverable_markers):
                raise DemoRecoverableTimelineError(message)
            raise RuntimeError(message)
        proposal = TimelineAnalysisProposalV1.model_validate(response.json())
        run_id = stable_id("demo-real-timeline-run", proposal.proposal_id)
        result, route = ReviewGate3Service().review(
            project_id=self.project_id,
            source_approved_proposal_bundle_id=stable_id("demo-gate2", self.project_id),
            timeline_run_id=run_id,
            reviewer_agent_run_id=stable_id("demo-gate3-agent", run_id),
            event_ids=[item.proposal_id for item in events],
            temporal_relations=proposal.temporal_relations,
            evidence_refs=proposal.evidence_refs,
        )
        # Comic Planning requires a bundle even when Demo only displays Gate 3 findings.
        bundle = route.approved_timeline_bundle
        if bundle is None:
            bundle = ReviewGate3Service.build_approved_bundle(
                decision=ReviewGate3Decision.APPROVED,
                route_id=route.route_id,
                review_id=result.review_id,
                project_id=self.project_id,
                source_bundle_id=result.source_approved_proposal_bundle_id,
                source_gate2_review_id="demo-gate2-review",
                source_gate2_route_id="demo-gate2-route",
                timeline_run_id=run_id,
                relations=proposal.temporal_relations,
                event_ids=[item.proposal_id for item in events],
                evidence=proposal.evidence_refs,
            )
        assert bundle is not None
        issues = [str(item.issue_code) for item in result.issues]
        count = self.app.state.timeline_agent.provider_request_count - before
        return bundle, str(result.decision), issues, count
