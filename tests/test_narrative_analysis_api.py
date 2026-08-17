"""API contracts for whole-document NarrativeAnalyst tasks."""

from pathlib import Path

from fastapi.testclient import TestClient

from comic_agent.config import get_settings
from comic_agent.main import create_app
from comic_agent.schemas.timeline import TimelineAnalysisInputV1, TimelineAnalysisProposalV1
from comic_agent.workflows.narrative_analyst_workflow import NarrativeAnalystWorkflow


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("ENABLE_REAL_LLM", "false")
    monkeypatch.setenv("INTERNAL_DEMO_REQUIRE_ACCESS_CODE", "false")
    get_settings.cache_clear()
    return TestClient(create_app(database_url=f"sqlite+pysqlite:///{tmp_path / 'analysis_api.db'}"))


def _import_document(client: TestClient) -> str:
    created = client.post(
        "/projects", json={"project_id": "project-1", "name": "Synthetic Project"}
    )
    assert created.status_code == 201
    imported = client.post(
        "/projects/project-1/documents/import",
        files={"file": ("synthetic.txt", b"Chapter 1\n\nSynthetic sentence.", "text/plain")},
    )
    assert imported.status_code == 201
    return imported.json()["document"]["document_id"]


def test_whole_document_analysis_api_is_dry_run_by_default_and_sanitized(
    tmp_path, monkeypatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    document_id = _import_document(client)

    documents = client.get("/projects/project-1/documents")
    assert documents.status_code == 200
    assert documents.json() == [
        {
            "document_id": document_id,
            "filename": "synthetic.txt",
            "revision": 1,
        }
    ]

    created = client.post(
        f"/projects/project-1/documents/{document_id}/narrative-analysis-runs",
        json={"modes": ["event_extraction", "entity_extraction"]},
    )

    assert created.status_code == 201
    payload = created.json()
    assert payload["document_id"] == document_id
    assert payload["real_llm_requested"] is False
    assert payload["concurrency"] == 1
    assert payload["windows_total"] == 2
    assert "text" not in payload
    assert "raw_output" not in payload
    run_id = payload["analysis_run_id"]

    progress = client.get(f"/narrative-analysis-runs/{run_id}")
    result = client.get(f"/narrative-analysis-runs/{run_id}/result")
    review = client.get(f"/narrative-analysis-runs/{run_id}/review-gate2")
    bundle = client.get(f"/narrative-analysis-runs/{run_id}/approved-proposal-bundle")
    resumed = client.post(f"/narrative-analysis-runs/{run_id}/resume")

    assert progress.status_code == 200
    assert progress.json()["status"] == "SUCCEEDED"
    assert progress.json()["windows_succeeded"] == 2
    assert progress.json()["windows_failed"] == 0
    assert progress.json()["review_gate2_ready"] is True
    assert progress.json()["review_gate2_route_decision"] == "APPROVED"
    assert result.status_code == 200
    assert result.json()["events"] == []
    assert result.json()["knowledge_states"] == []
    assert "Synthetic sentence." not in result.text
    assert review.status_code == 200
    assert review.json()["route"]["decision"] == "APPROVED"
    assert review.json()["result"]["approved_count"] == 0
    assert bundle.status_code == 200
    assert bundle.json()["approved_proposals"] == []
    assert resumed.status_code == 202


def test_recovery_bundle_is_unavailable_without_a_fresh_approved_attempt(
    tmp_path, monkeypatch
) -> None:
    """The root run's route must never substitute for a recovery-approved bundle."""

    client = _client(tmp_path, monkeypatch)
    document_id = _import_document(client)
    created = client.post(
        f"/projects/project-1/documents/{document_id}/narrative-analysis-runs",
        json={"modes": ["event_extraction"]},
    )
    run_id = created.json()["analysis_run_id"]

    recovery = client.get(f"/narrative-analysis-runs/{run_id}/recovery")
    bundle = client.get(f"/narrative-analysis-runs/{run_id}/recovery/approved-proposal-bundle")

    assert recovery.status_code == 200
    assert recovery.json()["approved_bundle_available"] is False
    assert bundle.status_code == 409
    assert "approved proposal bundle" in bundle.json()["detail"].lower()


def test_whole_document_analysis_api_rejects_manual_chunk_ids(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    document_id = _import_document(client)

    response = client.post(
        f"/projects/project-1/documents/{document_id}/narrative-analysis-runs",
        json={"modes": ["event_extraction"], "chunk_ids": ["chunk-should-not-be-accepted"]},
    )

    assert response.status_code == 422


def test_whole_document_analysis_rejects_real_request_when_server_llm_is_disabled(
    tmp_path, monkeypatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    document_id = _import_document(client)

    response = client.post(
        f"/projects/project-1/documents/{document_id}/narrative-analysis-runs",
        json={"modes": ["event_extraction"], "real_llm_requested": True},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Real LLM is disabled by server settings; restart the API with ENABLE_REAL_LLM=true"
    )


class _FakeEventProvider:
    def __init__(self) -> None:
        self.calls = 0

    def structured_generate(self, request, output_model):  # type: ignore[no-untyped-def]
        self.calls += 1
        context = request["input_context"]
        assert isinstance(context, dict)
        chunks = context["source_chunks"]
        assert isinstance(chunks, list)
        first_chunk = chunks[0]
        assert isinstance(first_chunk, dict)
        return output_model.model_validate(
            {
                "batch_id": "event-batch-whole-1",
                "events": [
                    {
                        "proposal_id": "event-whole-1",
                        "event_type": "synthetic_action",
                        "summary": "Synthetic action",
                        "participant_ids": [],
                        "actor_resolution_status": "UNKNOWN",
                        "evidence_refs": [
                            {
                                "chunk_id": first_chunk["chunk_id"],
                                "quote_text": "Synthetic",
                            }
                        ],
                        "confidence": 0.8,
                        "reality_layer": "PRIMARY",
                    }
                ],
            }
        )


class _FakeOrderedNarrativeProvider:
    """Produces two evidence-backed events through the real Narrative workflow."""

    def __init__(self) -> None:
        self.calls = 0

    def structured_generate(self, request, output_model):  # type: ignore[no-untyped-def]
        self.calls += 1
        chunk = request["input_context"]["source_chunks"][0]
        return output_model.model_validate(
            {
                "batch_id": "ordered-events-batch",
                "events": [
                    {
                        "proposal_id": "event-poster",
                        "event_type": "arrival",
                        "summary": "Xiaolin posts a poster.",
                        "participant_ids": [],
                        "actor_resolution_status": "UNKNOWN",
                        "evidence_refs": [
                            {
                                "chunk_id": chunk["chunk_id"],
                                "quote_text": "小林先到礼堂张贴海报",
                            }
                        ],
                        "confidence": 0.9,
                        "reality_layer": "PRIMARY",
                    },
                    {
                        "proposal_id": "event-umbrella",
                        "event_type": "arrival",
                        "summary": "Xiaozhou arrives with an umbrella.",
                        "participant_ids": [],
                        "actor_resolution_status": "UNKNOWN",
                        "evidence_refs": [
                            {
                                "chunk_id": chunk["chunk_id"],
                                "quote_text": "十分钟后，小周带着雨伞赶来",
                            }
                        ],
                        "confidence": 0.9,
                        "reality_layer": "PRIMARY",
                    },
                ],
            }
        )


class _FakeTimelineRunner:
    """Timeline interface fake that proves the worker supplied Gate 2 provenance only."""

    def __init__(self) -> None:
        self.calls = 0
        self.source_bundle_ids: list[str | None] = []

    def run(
        self,
        input_context: TimelineAnalysisInputV1,
        *,
        source_chunks: list[object],
    ) -> TimelineAnalysisProposalV1:
        self.calls += 1
        self.source_bundle_ids.append(input_context.source_approved_bundle_id)
        assert [event.proposal_id for event in input_context.event_proposals] == [
            "event-poster",
            "event-umbrella",
        ]
        assert len(source_chunks) == 1
        evidence = input_context.event_proposals[0].evidence_refs
        return TimelineAnalysisProposalV1(
            proposal_id="timeline-ordered-1",
            project_id=input_context.project_id,
            temporal_relations=[
                {
                    "proposal_id": "relation-ordered-1",
                    "source_event_id": "event-poster",
                    "target_event_id": "event-umbrella",
                    "relation": "BEFORE",
                    "evidence_refs": evidence,
                    "confidence": 0.9,
                }
            ],
            conflicts=[],
            duplicate_candidates=[],
            evidence_refs=evidence,
            confidence=0.9,
        )


def test_import_to_narrative_gate2_timeline_gate3_uses_only_approved_provenance(
    tmp_path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("ENABLE_REAL_LLM", "true")
    monkeypatch.setenv("INTERNAL_DEMO_REQUIRE_ACCESS_CODE", "false")
    get_settings.cache_clear()
    narrative_provider = _FakeOrderedNarrativeProvider()
    timeline_runner = _FakeTimelineRunner()
    app = create_app(database_url=f"sqlite+pysqlite:///{tmp_path / 'full_chain.db'}")
    app.state.narrative_analyst_provider = narrative_provider
    app.state.timeline_runner = timeline_runner
    client = TestClient(app)
    created = client.post(
        "/projects",
        json={"project_id": "project-1", "name": "Timeline Chain Project"},
    )
    assert created.status_code == 201
    imported = client.post(
        "/projects/project-1/documents/import",
        files={
            "file": (
                "ordered.txt",
                "第一章\n\n小林先到礼堂张贴海报。十分钟后，小周带着雨伞赶来。".encode(),
                "text/plain",
            )
        },
    )
    assert imported.status_code == 201
    document_id = imported.json()["document"]["document_id"]

    started = client.post(
        f"/projects/project-1/documents/{document_id}/narrative-analysis-runs",
        json={"modes": ["event_extraction"], "real_llm_requested": True},
    )
    assert started.status_code == 201
    run_id = started.json()["analysis_run_id"]
    gate2_bundle = client.get(
        f"/narrative-analysis-runs/{run_id}/approved-proposal-bundle"
    )
    assert gate2_bundle.status_code == 200
    bundle_id = gate2_bundle.json()["bundle_id"]
    summary = client.get(f"/projects/project-1/timeline-gate3/{bundle_id}")
    review = client.get(f"/projects/project-1/timeline-gate3/{bundle_id}/review")
    approved = client.get(
        f"/projects/project-1/timeline-gate3/{bundle_id}/approved-bundle"
    )

    assert narrative_provider.calls == 1
    assert timeline_runner.calls == 1
    assert timeline_runner.source_bundle_ids == [bundle_id]
    assert summary.status_code == 200
    assert summary.json()["timeline_status"] == "APPROVED"
    assert review.status_code == 200
    assert review.json()["route"]["route"] == "APPROVED"
    assert "quote_text" not in review.text
    assert approved.status_code == 200
    assert approved.json()["source_approved_proposal_bundle_id"] == bundle_id
    assert "quote_text" not in approved.text

    resumed = client.post(f"/narrative-analysis-runs/{run_id}/resume")
    assert resumed.status_code == 202
    assert timeline_runner.calls == 1


def test_whole_document_worker_uses_the_same_injected_provider_as_manual_mode(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("ENABLE_REAL_LLM", "true")
    monkeypatch.setenv("INTERNAL_DEMO_REQUIRE_ACCESS_CODE", "false")
    get_settings.cache_clear()
    provider = _FakeEventProvider()
    app = create_app(database_url=f"sqlite+pysqlite:///{tmp_path / 'analysis_provider_api.db'}")
    app.state.narrative_analyst_provider = provider
    client = TestClient(app)
    document_id = _import_document(client)

    monkeypatch.setattr(
        NarrativeAnalystWorkflow,
        "_build_provider",
        lambda _: (_ for _ in ()).throw(AssertionError("unexpected provider fallback")),
    )
    created = client.post(
        f"/projects/project-1/documents/{document_id}/narrative-analysis-runs",
        json={"modes": ["event_extraction"], "real_llm_requested": True},
    )

    assert created.status_code == 201
    run_id = created.json()["analysis_run_id"]
    progress = client.get(f"/narrative-analysis-runs/{run_id}")
    result = client.get(f"/narrative-analysis-runs/{run_id}/result")
    windows = client.get(f"/narrative-analysis-runs/{run_id}/windows")
    review = client.get(f"/narrative-analysis-runs/{run_id}/review-gate2")
    bundle = client.get(f"/narrative-analysis-runs/{run_id}/approved-proposal-bundle")

    assert provider.calls == 1
    assert progress.json()["status"] == "SUCCEEDED"
    assert progress.json()["review_gate2_route_decision"] == "APPROVED"
    assert result.json()["events"][0]["agent_run_ids"]
    assert review.status_code == 200
    assert review.json()["result"]["approved_count"] == 1
    assert bundle.status_code == 200
    assert (
        bundle.json()["approved_proposals"][0]["source"]["proposal"]["proposal_id"]
        == "event-whole-1"
    )
    assert windows.status_code == 200
    window = windows.json()["items"][0]
    assert window["agent_run_id"] == result.json()["events"][0]["agent_run_ids"][0]
    assert window["attempt_count"] == 1
    assert window["effective_max_chars_per_chunk"] == 1200
    assert window["previous_failure_category"] is None
    assert window["owned_chunk_ids"] == window["chunk_ids"]
    assert window["parent_window_id"] is None
    assert window["split_reason"] is None
    assert "Synthetic sentence." not in windows.text
    assert "raw_output" not in windows.text


def test_recovery_endpoint_exposes_only_fresh_approved_bundle(tmp_path, monkeypatch) -> None:
    """A rejected root route may expose only its subsequent fresh recovery bundle."""

    class _RecoveryProvider(_FakeEventProvider):
        def structured_generate(self, request, output_model):  # type: ignore[no-untyped-def]
            self.calls += 1
            chunk = request["input_context"]["source_chunks"][0]
            quote = "absent" if self.calls == 1 else "Synthetic"
            proposal_id = "root-rejected" if self.calls == 1 else "fresh-approved"
            return output_model.model_validate(
                {
                    "batch_id": f"batch-{self.calls}",
                    "events": [
                        {
                            "proposal_id": proposal_id,
                            "event_type": "synthetic_action",
                            "summary": "Synthetic action",
                            "participant_ids": [],
                            "actor_resolution_status": "UNKNOWN",
                            "evidence_refs": [
                                {"chunk_id": chunk["chunk_id"], "quote_text": quote}
                            ],
                            "confidence": 0.8,
                            "reality_layer": "PRIMARY",
                        }
                    ],
                }
            )

    class _RecoveryTimelineRunner:
        def __init__(self) -> None:
            self.calls = 0
            self.bundle_ids: list[str | None] = []

        def run(
            self,
            input_context: TimelineAnalysisInputV1,
            *,
            source_chunks: list[object],
        ) -> TimelineAnalysisProposalV1:
            self.calls += 1
            self.bundle_ids.append(input_context.source_approved_bundle_id)
            evidence = input_context.event_proposals[0].evidence_refs
            return TimelineAnalysisProposalV1(
                proposal_id="timeline-fresh-recovery",
                project_id=input_context.project_id,
                temporal_relations=[],
                conflicts=[],
                duplicate_candidates=[],
                evidence_refs=evidence,
                confidence=0.9,
            )

    monkeypatch.setenv("ENABLE_REAL_LLM", "true")
    monkeypatch.setenv("INTERNAL_DEMO_REQUIRE_ACCESS_CODE", "false")
    get_settings.cache_clear()
    provider = _RecoveryProvider()
    timeline_runner = _RecoveryTimelineRunner()
    app = create_app(database_url=f"sqlite+pysqlite:///{tmp_path / 'recovery_api.db'}")
    app.state.narrative_analyst_provider = provider
    app.state.timeline_runner = timeline_runner
    client = TestClient(app)
    document_id = _import_document(client)

    created = client.post(
        f"/projects/project-1/documents/{document_id}/narrative-analysis-runs",
        json={"modes": ["event_extraction"], "real_llm_requested": True},
    )
    run_id = created.json()["analysis_run_id"]
    recovery = client.get(f"/narrative-analysis-runs/{run_id}/recovery")
    bundle = client.get(f"/narrative-analysis-runs/{run_id}/recovery/approved-proposal-bundle")
    root_review = client.get(f"/narrative-analysis-runs/{run_id}/review-gate2")

    assert provider.calls == 2
    assert timeline_runner.calls == 1
    assert recovery.status_code == 200
    assert recovery.json()["approved_bundle_available"] is True
    assert bundle.status_code == 200
    proposal = bundle.json()["approved_proposals"][0]["source"]["proposal"]
    assert proposal["proposal_id"] == "fresh-approved"
    assert "root-rejected" not in bundle.text
    assert "Synthetic sentence." not in bundle.text
    assert "raw_output" not in bundle.text
    assert root_review.json()["route"]["decision"] == "REJECTED"
    assert timeline_runner.bundle_ids == [bundle.json()["bundle_id"]]
