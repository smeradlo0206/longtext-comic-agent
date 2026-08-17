import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from comic_agent.agents.timeline_agent import TimelineAgent
from comic_agent.database.models import SourceChunkModel
from comic_agent.main import create_app
from comic_agent.providers.mocks import MockLLMProvider, MockMode
from comic_agent.repositories.timeline_gate3_repository import TimelineGate3Repository
from comic_agent.schemas.base import EvidenceRefV1, RealityLayer
from comic_agent.schemas.narrative import EventProposalV1
from comic_agent.schemas.source import SourceChunkV1
from comic_agent.schemas.timeline import (
    TimelineAnalysisInputV1,
    TimelineAnalysisProposalV1,
    TimelineGate3RunStatus,
    TimelineGate3RunV1,
)
from comic_agent.services.review_gate3_service import ReviewGate3Service


def seed_chunk(
    app: FastAPI,
    *,
    chunk_id: str,
    project_id: str,
    text: str = "Lin waits at the market.",
) -> None:
    """Persist source evidence for project-scope API checks."""

    chunk = SourceChunkV1(
        chunk_id=chunk_id,
        document_id=f"document-{project_id}",
        chapter_id=f"chapter-{project_id}",
        project_id=project_id,
        order=0,
        text=text,
        checksum=f"checksum-{chunk_id}",
    )
    session: Session = app.state.session_factory()
    try:
        session.add(
            SourceChunkModel(
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                chapter_id=chunk.chapter_id,
                project_id=chunk.project_id,
                order=chunk.order,
                text=chunk.text,
                source_page=chunk.source_page,
                char_start=chunk.char_start,
                char_end=chunk.char_end,
                checksum=chunk.checksum,
                payload=chunk.model_dump(mode="json"),
            )
        )
        session.commit()
    finally:
        session.close()


def event_payload(proposal_id: str, chunk_id: str) -> dict[str, object]:
    return {
        "proposal_id": proposal_id,
        "event_type": "HANDOFF",
        "summary": "Chen hands Lin an umbrella.",
        "participant_ids": ["chen", "lin"],
        "location_id": "market",
        "evidence_refs": [{"chunk_id": chunk_id}],
        "confidence": 0.9,
        "reality_layer": "PRIMARY",
    }


def test_timeline_api_returns_candidate_analysis(tmp_path) -> None:  # type: ignore[no-untyped-def]
    app = create_app(database_url=f"sqlite+pysqlite:///{tmp_path / 'timeline.db'}")
    seed_chunk(app, chunk_id="chunk-a", project_id="project-a")
    payload = {
        "project_id": "project-a",
        "event_proposals": [
            event_payload("event-1", "chunk-a"),
            event_payload("event-2", "chunk-a"),
        ],
    }

    with TestClient(app) as client:
        response = client.post("/projects/project-a/timeline/analyze", json=payload)
        repeated_response = client.post("/projects/project-a/timeline/analyze", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "CANDIDATE"
    assert body["temporal_relations"][0]["relation"] == "UNKNOWN"
    assert body["duplicate_candidates"][0]["proposal_ids"] == ["event-1", "event-2"]
    assert repeated_response.status_code == 200
    assert repeated_response.json() == body

    with TestClient(app) as client:
        list_response = client.get("/projects/project-a/timeline/analyses")
        by_id_response = client.get(f"/projects/project-a/timeline/analyses/{body['proposal_id']}")
        agent_runs_response = client.get("/projects/project-a/agent-runs")

    assert list_response.status_code == 200
    assert list_response.json() == [body]
    assert by_id_response.status_code == 200
    assert by_id_response.json() == body
    runs = agent_runs_response.json()
    assert agent_runs_response.status_code == 200
    assert len(runs) == 1
    assert {run["agent_id"] for run in runs} == {"timeline-agent"}
    assert {run["output_proposal_id"] for run in runs} == {body["proposal_id"]}
    assert {run["source_chunk_id"] for run in runs} == {None}


def test_timeline_api_rejects_path_body_project_mismatch(tmp_path) -> None:  # type: ignore[no-untyped-def]
    app = create_app(database_url=f"sqlite+pysqlite:///{tmp_path / 'timeline.db'}")
    seed_chunk(app, chunk_id="chunk-a", project_id="project-a")
    payload = {"project_id": "project-b", "event_proposals": [event_payload("event-1", "chunk-a")]}

    with TestClient(app) as client:
        response = client.post("/projects/project-a/timeline/analyze", json=payload)

    assert response.status_code == 409
    assert response.json()["detail"] == "Timeline analysis project mismatch"


def test_timeline_api_rejects_foreign_evidence(tmp_path) -> None:  # type: ignore[no-untyped-def]
    app = create_app(database_url=f"sqlite+pysqlite:///{tmp_path / 'timeline.db'}")
    seed_chunk(app, chunk_id="chunk-b", project_id="project-b")
    payload = {"project_id": "project-a", "event_proposals": [event_payload("event-1", "chunk-b")]}

    with TestClient(app) as client:
        response = client.post("/projects/project-a/timeline/analyze", json=payload)

    assert response.status_code == 409
    assert response.json()["detail"] == "Timeline analysis project mismatch"


class CountingMockLLMProvider(MockLLMProvider):
    def __init__(self, response: dict[str, object], mode: MockMode = MockMode.SUCCESS) -> None:
        super().__init__(response, mode)
        self.calls = 0

    def structured_generate(self, request, output_model):  # type: ignore[no-untyped-def]
        self.calls += 1
        return super().structured_generate(request, output_model)


def llm_payload(
    *, relation: str = "BEFORE", evidence_ids: list[str] | None = None
) -> dict[str, object]:
    return {
        "relation": relation,
        "supporting_evidence_ids": evidence_ids
        if evidence_ids is not None
        else ([] if relation == "UNKNOWN" else ["event_a_evidence_0"]),
        "confidence": 0.9,
        "reasoning_summary": "The source explicitly gives the ordering.",
    }


def llm_request_payload() -> dict[str, object]:
    return {
        "project_id": "project-a",
        "mode": "LLM",
        "event_proposals": [
            event_payload("event-1", "chunk-a"),
            event_payload("event-2", "chunk-a"),
        ],
    }


def test_timeline_api_llm_validates_evidence_and_reuses_cache(tmp_path) -> None:  # type: ignore[no-untyped-def]
    app = create_app(database_url=f"sqlite+pysqlite:///{tmp_path / 'timeline.db'}")
    seed_chunk(
        app,
        chunk_id="chunk-a",
        project_id="project-a",
        text="Chen leaves before Lin arrives.",
    )
    provider = CountingMockLLMProvider(llm_payload())
    app.state.timeline_agent = TimelineAgent(provider, provider_model="mock-v2")

    with TestClient(app) as client:
        first = client.post("/projects/project-a/timeline/analyze", json=llm_request_payload())
        second = client.post("/projects/project-a/timeline/analyze", json=llm_request_payload())

    assert first.status_code == 200
    assert first.json()["temporal_relations"][0]["relation"] == "BEFORE"
    assert second.json() == first.json()
    assert provider.calls == 1


def test_timeline_api_does_not_reuse_cache_after_model_changes(tmp_path) -> None:  # type: ignore[no-untyped-def]
    app = create_app(database_url=f"sqlite+pysqlite:///{tmp_path / 'timeline.db'}")
    seed_chunk(app, chunk_id="chunk-a", project_id="project-a")
    first_provider = CountingMockLLMProvider(llm_payload())
    app.state.timeline_agent = TimelineAgent(first_provider, provider_model="model-a")

    with TestClient(app) as client:
        first = client.post("/projects/project-a/timeline/analyze", json=llm_request_payload())

    second_provider = CountingMockLLMProvider(llm_payload())
    app.state.timeline_agent = TimelineAgent(second_provider, provider_model="model-b")
    with TestClient(app) as client:
        second = client.post("/projects/project-a/timeline/analyze", json=llm_request_payload())

    assert first.status_code == 200
    assert second.status_code == 200
    assert first_provider.calls == 1
    assert second_provider.calls == 1


def test_timeline_api_rejects_invalid_llm_evidence_and_records_failure(tmp_path) -> None:  # type: ignore[no-untyped-def]
    app = create_app(database_url=f"sqlite+pysqlite:///{tmp_path / 'timeline.db'}")
    seed_chunk(
        app, chunk_id="chunk-a", project_id="project-a", text="Chen leaves before Lin arrives."
    )
    bad = llm_payload(evidence_ids=["invented_evidence_id"])
    app.state.timeline_agent = TimelineAgent(MockLLMProvider(bad), provider_model="mock-v2")

    with TestClient(app) as client:
        response = client.post("/projects/project-a/timeline/analyze", json=llm_request_payload())
        runs = client.get("/projects/project-a/agent-runs")

    assert response.status_code == 422
    assert "unknown evidence id" in response.json()["detail"]
    assert runs.json()[-1]["status"] == "FAILED"


def test_timeline_api_rejects_mismatched_existing_quote(tmp_path) -> None:  # type: ignore[no-untyped-def]
    app = create_app(database_url=f"sqlite+pysqlite:///{tmp_path / 'timeline.db'}")
    seed_chunk(
        app,
        chunk_id="chunk-a",
        project_id="project-a",
        text="Chen leaves before Lin arrives.",
    )
    app.state.timeline_agent = TimelineAgent(
        MockLLMProvider(llm_payload()), provider_model="mock-v2"
    )
    payload = llm_request_payload()
    events = payload["event_proposals"]
    assert isinstance(events, list)
    events[0]["evidence_refs"] = [{"chunk_id": "chunk-a", "quote_text": "not present"}]

    with TestClient(app) as client:
        result = client.post("/projects/project-a/timeline/analyze", json=payload)

    assert result.status_code == 422
    assert "quote_text does not match" in result.json()["detail"]


def test_timeline_api_records_timeout_and_rejects_malformed_provider_output(tmp_path) -> None:  # type: ignore[no-untyped-def]
    app = create_app(database_url=f"sqlite+pysqlite:///{tmp_path / 'timeline.db'}")
    seed_chunk(
        app, chunk_id="chunk-a", project_id="project-a", text="Chen leaves before Lin arrives."
    )
    app.state.timeline_agent = TimelineAgent(
        MockLLMProvider(mode=MockMode.TIMEOUT), provider_model="mock-v2"
    )

    with TestClient(app) as client:
        timeout = client.post("/projects/project-a/timeline/analyze", json=llm_request_payload())
    assert timeout.status_code == 422
    assert "timeout" in timeout.json()["detail"]

    app.state.timeline_agent = TimelineAgent(
        MockLLMProvider({}, mode=MockMode.SCHEMA_ERROR), provider_model="mock-v2b"
    )
    with TestClient(app) as client:
        malformed = client.post("/projects/project-a/timeline/analyze", json=llm_request_payload())
        runs = client.get("/projects/project-a/agent-runs")
    assert malformed.status_code == 422
    assert "mock schema error" in malformed.json()["detail"]
    assert [run["status"] for run in runs.json()] == ["FAILED", "FAILED"]


def test_timeline_api_rejects_out_of_bounds_llm_quote(tmp_path) -> None:  # type: ignore[no-untyped-def]
    app = create_app(database_url=f"sqlite+pysqlite:///{tmp_path / 'timeline.db'}")
    seed_chunk(app, chunk_id="chunk-a", project_id="project-a", text="short source")
    response = llm_payload()
    app.state.timeline_agent = TimelineAgent(MockLLMProvider(response), provider_model="mock-v2")

    payload = llm_request_payload()
    events = payload["event_proposals"]
    assert isinstance(events, list)
    events[0]["evidence_refs"] = [
        {"chunk_id": "chunk-a", "quote_start": 0, "quote_end": 100, "quote_text": "short source"}
    ]
    with TestClient(app) as client:
        result = client.post("/projects/project-a/timeline/analyze", json=payload)

    assert result.status_code == 422
    assert "quote range exceeds" in result.json()["detail"]


@pytest.mark.parametrize(
    "response",
    [
        {**llm_payload(), "confidence": 1.1},
        {**llm_payload(), "confidence": -0.1},
        {**llm_payload(), "relation": "DURING"},
        {**llm_payload(), "relation": "MAYBE_BEFORE"},
    ],
)
def test_timeline_api_rejects_invalid_llm_schema(
    tmp_path, response: dict[str, object]
) -> None:  # type: ignore[no-untyped-def]
    app = create_app(database_url=f"sqlite+pysqlite:///{tmp_path / 'timeline.db'}")
    seed_chunk(
        app,
        chunk_id="chunk-a",
        project_id="project-a",
        text="Chen leaves before Lin arrives.",
    )
    app.state.timeline_agent = TimelineAgent(MockLLMProvider(response), provider_model="mock-v2")

    with TestClient(app) as client:
        result = client.post("/projects/project-a/timeline/analyze", json=llm_request_payload())

    assert result.status_code == 422


class HttpErrorProvider:
    def structured_generate(self, request, output_model):  # type: ignore[no-untyped-def]
        request_for_error = httpx.Request("POST", "https://api.example/v1/chat/completions")
        response = httpx.Response(503, request=request_for_error)
        raise httpx.HTTPStatusError(
            "provider unavailable", request=request_for_error, response=response
        )


def test_timeline_api_records_http_provider_failure(tmp_path) -> None:  # type: ignore[no-untyped-def]
    app = create_app(database_url=f"sqlite+pysqlite:///{tmp_path / 'timeline.db'}")
    seed_chunk(app, chunk_id="chunk-a", project_id="project-a")
    app.state.timeline_agent = TimelineAgent(HttpErrorProvider(), provider_model="mock-http")

    with TestClient(app) as client:
        result = client.post("/projects/project-a/timeline/analyze", json=llm_request_payload())
        runs = client.get("/projects/project-a/agent-runs")

    assert result.status_code == 422
    assert runs.json()[-1]["status"] == "FAILED"


def test_timeline_api_rejects_missing_input_evidence_chunk(tmp_path) -> None:  # type: ignore[no-untyped-def]
    app = create_app(database_url=f"sqlite+pysqlite:///{tmp_path / 'timeline.db'}")
    payload = {"project_id": "project-a", "event_proposals": [event_payload("event-1", "missing")]}

    with TestClient(app) as client:
        result = client.post("/projects/project-a/timeline/analyze", json=payload)

    assert result.status_code == 409


def test_gate3_read_only_api_exposes_only_fresh_approved_bundle(tmp_path) -> None:  # type: ignore[no-untyped-def]
    app = create_app(database_url=f"sqlite+pysqlite:///{tmp_path / 'timeline-gate3.db'}")
    evidence = EvidenceRefV1(chunk_id="chunk-a", quote_text="bell rings")
    event = EventProposalV1(
        proposal_id="event-1",
        event_type="BELL",
        summary="The bell rings.",
        participant_ids=[],
        location_id=None,
        evidence_refs=[evidence],
        confidence=0.9,
        reality_layer=RealityLayer.PRIMARY,
    )
    timeline_input = TimelineAnalysisInputV1(
        schema_version="1.3",
        project_id="project-a",
        source_approved_bundle_id="gate2-bundle-1",
        source_review_run_id="gate2-review-1",
        event_proposals=[event],
    )
    proposal = TimelineAnalysisProposalV1(
        proposal_id="timeline-proposal-1",
        project_id="project-a",
        temporal_relations=[],
        conflicts=[],
        duplicate_candidates=[],
        evidence_refs=[evidence],
        confidence=0.9,
    )
    result, route = ReviewGate3Service().review(
        project_id="project-a",
        source_approved_proposal_bundle_id="gate2-bundle-1",
        timeline_run_id="timeline-run-1",
        reviewer_agent_run_id="gate3-agent-run-1",
        event_ids=["event-1"],
        temporal_relations=[],
        evidence_refs=[evidence],
        source_gate2_review_id="gate2-review-1",
        source_gate2_route_id="analysis-1",
    )
    session: Session = app.state.session_factory()
    try:
        TimelineGate3Repository(session).reserve_run(
            TimelineGate3RunV1(
                timeline_run_id="timeline-run-1",
                project_id="project-a",
                source_approved_proposal_bundle_id="gate2-bundle-1",
                source_gate2_review_id="gate2-review-1",
                source_gate2_route_id="analysis-1",
                idempotency_key="timeline-gate3-key-1",
                status=TimelineGate3RunStatus.APPROVED,
                timeline_input=timeline_input,
                timeline_proposal=proposal,
                timeline_agent_run_id="timeline-agent-run-1",
                gate3_result=result,
                gate3_route=route,
                approved_timeline_bundle=route.approved_timeline_bundle,
                provider_request_count=1,
            )
        )
    finally:
        session.close()

    with TestClient(app) as client:
        summary = client.get("/projects/project-a/timeline-gate3/gate2-bundle-1")
        review = client.get("/projects/project-a/timeline-gate3/gate2-bundle-1/review")
        bundle = client.get("/projects/project-a/timeline-gate3/gate2-bundle-1/approved-bundle")
        absent = client.get("/projects/project-a/timeline-gate3/missing/approved-bundle")

    assert summary.status_code == 200
    assert summary.json()["gate3_route"] == "APPROVED"
    assert review.status_code == 200
    assert review.json()["route"]["approved_timeline_bundle_id"]
    assert "quote_text" not in str(review.json())
    assert bundle.status_code == 200
    assert bundle.json()["bundle_id"] == route.approved_timeline_bundle_id
    assert "quote_text" not in str(bundle.json())
    assert absent.status_code == 409
