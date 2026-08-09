"""API boundaries for candidate curation and canonical StoryBible resources."""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from comic_agent.agents.storybible_curator import StoryBibleCurator
from comic_agent.database.models import SourceChunkModel
from comic_agent.main import create_app
from comic_agent.providers.mocks import MockLLMProvider
from comic_agent.schemas.source import SourceChunkV1


def candidate_payload(
    *,
    project_id: str = "project-a",
    proposal_id: str = "proposal-a",
    plan_id: str = "plan-a",
    content_hash: str = "hash-a",
) -> dict[str, Any]:
    """Return a complete mock provider response backed by one source chunk."""

    evidence = {"chunk_id": "chunk-a"}
    profile = {
        "profile_id": "profile-a",
        "project_id": project_id,
        "entity_kind": "PERSON",
        "canonical_name": "Lin Xia",
        "aliases": ["Xia"],
        "evidence_refs": [evidence],
    }
    state = {
        "state_id": "state-a",
        "project_id": project_id,
        "profile_id": "profile-a",
        "state": {"location": "market"},
        "triggering_event_id": "event-a",
        "valid_from_event_id": "event-a",
        "evidence_refs": [evidence],
    }
    updates = [
        {
            "update_id": f"update-{proposal_id}-profile-a",
            "project_id": project_id,
            "profile": profile,
            "evidence_refs": [evidence],
        },
        {
            "update_id": f"update-{proposal_id}-state-a",
            "project_id": project_id,
            "state": state,
            "evidence_refs": [evidence],
        },
    ]
    return {
        "proposal_id": proposal_id,
        "project_id": project_id,
        "status": "CANDIDATE",
        "commit_plan": {
            "commit_plan_id": plan_id,
            "project_id": project_id,
            "source_proposal_id": proposal_id,
            "content_hash": content_hash,
            "updates": updates,
            "evidence_refs": [evidence],
        },
        "evidence_refs": [evidence],
        "confidence": 0.9,
    }


class RecordingMockLLMProvider(MockLLMProvider):
    """Mock provider that retains the bounded context passed to the agent."""

    def __init__(self, response: dict[str, Any]) -> None:
        super().__init__(response)
        self.requests: list[dict[str, object]] = []

    def structured_generate(
        self,
        request: dict[str, object],
        output_model: type[Any],
    ) -> Any:
        self.requests.append(request)
        return super().structured_generate(request, output_model)


def seed_chunk(
    app: FastAPI,
    *,
    chunk_id: str = "chunk-a",
    project_id: str = "project-a",
) -> None:
    """Persist real evidence for proposal and commit validation."""

    chunk = SourceChunkV1(
        chunk_id=chunk_id,
        document_id=f"document-{project_id}",
        chapter_id=f"chapter-{project_id}",
        project_id=project_id,
        order=0,
        text="Lin Xia waits at the market.",
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


@pytest.fixture()
def storybible_client(tmp_path: Path) -> Iterator[TestClient]:
    """Serve the real API with a deterministic, network-free curator provider."""

    app = create_app(database_url=f"sqlite+pysqlite:///{tmp_path / 'api.db'}")
    seed_chunk(app)
    seed_chunk(app, chunk_id="chunk-b", project_id="project-b")
    app.state.storybible_curator = StoryBibleCurator(
        MockLLMProvider(candidate_payload())
    )
    with TestClient(app) as client:
        yield client


def curate(client: TestClient) -> dict[str, Any]:
    response = client.post(
        "/projects/project-a/storybible/curate",
        json={"project_id": "project-a", "source_chunk_ids": ["chunk-a"]},
    )
    assert response.status_code == 200
    return response.json()


def approve(client: TestClient) -> dict[str, Any]:
    response = client.post(
        "/projects/project-a/storybible/commit-plans/plan-a",
        json={"status": "APPROVED"},
    )
    assert response.status_code == 200
    return response.json()


def test_curation_persists_only_a_candidate_plan(storybible_client: TestClient) -> None:
    """Removing the candidate-only boundary would expose a profile before approval."""

    proposal = curate(storybible_client)

    assert proposal["status"] == "CANDIDATE"
    assert proposal["commit_plan"]["commit_plan_id"] == "plan-a"
    assert (
        storybible_client.get(
            "/projects/project-a/storybible/profiles/profile-a"
        ).status_code
        == 404
    )


def test_curation_rebuilds_canonical_context_from_project_scoped_storage(
    storybible_client: TestClient,
) -> None:
    """Caller-supplied canonical values must not be forwarded to the curator."""

    curate(storybible_client)
    approve(storybible_client)
    provider = RecordingMockLLMProvider(
        candidate_payload(proposal_id="proposal-b", plan_id="plan-b", content_hash="hash-b")
    )
    app = cast(FastAPI, storybible_client.app)
    app.state.storybible_curator = StoryBibleCurator(provider)

    response = storybible_client.post(
        "/projects/project-a/storybible/curate",
        json={
            "project_id": "project-a",
            "source_chunk_ids": ["chunk-a"],
            "profiles": [
                {
                    "profile_id": "profile-a",
                    "project_id": "project-a",
                    "entity_kind": "PERSON",
                    "canonical_name": "Forged Lin Xia",
                    "evidence_refs": [{"chunk_id": "chunk-a"}],
                }
            ],
            "states": [
                {
                    "state_id": "forged-state",
                    "project_id": "project-a",
                    "profile_id": "profile-a",
                    "state": {"location": "forged"},
                    "evidence_refs": [{"chunk_id": "chunk-a"}],
                }
            ],
            "relationships": [
                {
                    "relationship_id": "forged-relationship",
                    "project_id": "project-a",
                    "source_profile_id": "profile-a",
                    "target_profile_id": "other-profile",
                    "relationship_type": "ALLY",
                    "evidence_refs": [{"chunk_id": "chunk-a"}],
                }
            ],
            "world_rules": [
                {
                    "rule_id": "forged-rule",
                    "project_id": "project-a",
                    "name": "Forged rule",
                    "statement": "Forged canonical context must be ignored.",
                    "evidence_refs": [{"chunk_id": "chunk-a"}],
                }
            ],
        },
    )

    assert response.status_code == 200
    context = json.loads(str(provider.requests[0]["messages"][1]["content"]))
    assert [profile["profile_id"] for profile in context["profiles"]] == ["profile-a"]
    assert context["profiles"][0]["canonical_name"] == "Lin Xia"
    assert [state["state_id"] for state in context["states"]] == ["state-a"]
    assert context["relationships"] == []
    assert context["world_rules"] == []


def test_curation_rejects_different_proposals_that_reuse_a_content_hash(
    storybible_client: TestClient,
) -> None:
    """A provider hash collision must not substitute another proposal's commit plan."""

    curate(storybible_client)
    app = cast(FastAPI, storybible_client.app)
    app.state.storybible_curator = StoryBibleCurator(
        MockLLMProvider(
            candidate_payload(proposal_id="proposal-b", plan_id="plan-b", content_hash="hash-a")
        )
    )

    response = storybible_client.post(
        "/projects/project-a/storybible/curate",
        json={"project_id": "project-a", "source_chunk_ids": ["chunk-a"]},
    )

    assert response.status_code == 422
    assert "content_hash" in response.json()["detail"]


def test_curation_rejects_context_for_another_project(
    storybible_client: TestClient,
) -> None:
    """A body project id must not select resources outside the path project."""

    response = storybible_client.post(
        "/projects/project-b/storybible/curate",
        json={"project_id": "project-a", "source_chunk_ids": ["chunk-a"]},
    )

    assert response.status_code == 409


@pytest.mark.parametrize(
    "foreign_context",
    [
        {"source_chunk_ids": ["chunk-b"]},
        {
            "profiles": [
                {
                    "profile_id": "profile-b",
                    "project_id": "project-b",
                    "entity_kind": "PERSON",
                    "canonical_name": "Outsider",
                    "evidence_refs": [{"chunk_id": "chunk-a"}],
                }
            ]
        },
        {
            "entity_proposals": [
                {
                    "proposal_id": "entity-b",
                    "entity_type": "CHARACTER",
                    "canonical_name": "Outsider",
                    "evidence_refs": [{"chunk_id": "chunk-b"}],
                    "confidence": 0.8,
                }
            ]
        },
    ],
)
def test_curation_rejects_nested_context_from_another_project(
    storybible_client: TestClient,
    foreign_context: dict[str, Any],
) -> None:
    """Correct top-level ownership must not conceal foreign bounded resources."""

    response = storybible_client.post(
        "/projects/project-a/storybible/curate",
        json={"project_id": "project-a", **foreign_context},
    )

    assert response.status_code == 409


def test_commit_requires_explicit_approval(storybible_client: TestClient) -> None:
    """Candidate or rejected approval data must never trigger canonical writes."""

    curate(storybible_client)
    response = storybible_client.post(
        "/projects/project-a/storybible/commit-plans/plan-a",
        json={"status": "CANDIDATE"},
    )

    assert response.status_code == 403
    assert (
        storybible_client.get(
            "/projects/project-a/storybible/profiles/profile-a"
        ).status_code
        == 404
    )


def test_commit_endpoint_is_idempotent(storybible_client: TestClient) -> None:
    """Retrying the approved plan must return the same committed representation."""

    curate(storybible_client)

    first = approve(storybible_client)
    second = approve(storybible_client)

    assert first == second
    assert first["commit_plan_id"] == "plan-a"


def test_commit_plan_does_not_cross_project_boundaries(
    storybible_client: TestClient,
) -> None:
    """Knowing another project's plan id must not make it committable."""

    curate(storybible_client)
    response = storybible_client.post(
        "/projects/project-b/storybible/commit-plans/plan-a",
        json={"status": "APPROVED"},
    )

    assert response.status_code == 404
    assert (
        storybible_client.get(
            "/projects/project-a/storybible/profiles/profile-a"
        ).status_code
        == 404
    )


def test_profile_endpoints_do_not_cross_project_boundaries(
    storybible_client: TestClient,
) -> None:
    """Collection and item retrieval must apply the path project to every query."""

    curate(storybible_client)
    approve(storybible_client)

    own_list = storybible_client.get("/projects/project-a/storybible/profiles")
    other_list = storybible_client.get("/projects/project-b/storybible/profiles")
    other_item = storybible_client.get(
        "/projects/project-b/storybible/profiles/profile-a"
    )

    assert own_list.status_code == 200
    assert [profile["profile_id"] for profile in own_list.json()] == ["profile-a"]
    assert other_list.json() == []
    assert other_item.status_code == 404


def test_profile_states_are_project_scoped_and_filter_by_event_id(
    storybible_client: TestClient,
) -> None:
    """State retrieval must honor both profile ownership and an event-id bound."""

    curate(storybible_client)
    approve(storybible_client)

    at_event = storybible_client.get(
        "/projects/project-a/storybible/profiles/profile-a/states",
        params={"event_id": "event-a"},
    )
    at_other_event = storybible_client.get(
        "/projects/project-a/storybible/profiles/profile-a/states",
        params={"event_id": "event-b"},
    )
    other_project = storybible_client.get(
        "/projects/project-b/storybible/profiles/profile-a/states",
        params={"event_id": "event-a"},
    )

    assert at_event.status_code == 200
    assert [state["state_id"] for state in at_event.json()] == ["state-a"]
    assert at_other_event.json() == []
    assert other_project.status_code == 404
