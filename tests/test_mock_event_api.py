from fastapi.testclient import TestClient

from comic_agent.main import create_app

PROJECT = {
    "id": "project-1",
    "name": "Mock Event Demo",
    "project_type": "LONG_NOVEL",
    "fidelity_mode": "CANON_STRICT",
    "output_format": "PAGES",
    "reading_direction": "LTR",
    "allow_new_events": False,
    "allow_new_dialogue": False,
    "allow_event_reordering": False,
    "allow_visual_compression": True,
    "allow_dialogue_splitting": True,
    "require_source_traceability": True,
    "max_auto_repairs": 3,
    "budget_limit": 100,
}


def test_uploaded_chunk_can_run_through_mock_event_workflow(tmp_path) -> None:  # type: ignore[no-untyped-def]
    app = create_app(database_url=f"sqlite+pysqlite:///{tmp_path / 'api.db'}")
    with TestClient(app) as client:
        assert client.post("/projects", json=PROJECT).status_code == 201
        response = client.post(
            "/projects/project-1/documents/import",
            files={"file": ("source.txt", b"Chapter 1\n\nExact source text.", "text/plain")},
        )
        assert response.status_code == 201

        chapters = client.get("/projects/project-1/chapters").json()
        chunks = client.get(f"/chapters/{chapters[0]['chapter_id']}/chunks").json()
        proposal_response = client.post(f"/chunks/{chunks[0]['chunk_id']}/mock-event")
        repeated_response = client.post(f"/chunks/{chunks[0]['chunk_id']}/mock-event")

    assert proposal_response.status_code == 200
    assert repeated_response.status_code == 200
    proposal = proposal_response.json()
    evidence = proposal["evidence_refs"][0]
    assert proposal["event_type"] == "MOCK_EVENT"
    assert evidence["chunk_id"] == chunks[0]["chunk_id"]
    assert evidence["quote_start"] == 0
    assert evidence["quote_end"] == len(chunks[0]["text"])
    assert evidence["quote_text"] == chunks[0]["text"]

    with TestClient(app) as client:
        by_id_response = client.get(f"/event-proposals/{proposal['proposal_id']}")
        chunk_proposals_response = client.get(
            f"/chunks/{chunks[0]['chunk_id']}/event-proposals"
        )
        chunk_runs_response = client.get(f"/chunks/{chunks[0]['chunk_id']}/agent-runs")

    assert by_id_response.status_code == 200
    assert by_id_response.json() == proposal
    assert chunk_proposals_response.status_code == 200
    assert chunk_proposals_response.json() == [proposal]
    assert chunk_runs_response.status_code == 200
    runs = chunk_runs_response.json()
    assert len(runs) == 2
    assert {run["status"] for run in runs} == {"SUCCEEDED"}
    assert {run["source_chunk_id"] for run in runs} == {chunks[0]["chunk_id"]}
    assert {run["output_proposal_id"] for run in runs} == {proposal["proposal_id"]}

    with TestClient(app) as client:
        run_response = client.get(f"/agent-runs/{runs[0]['agent_run_id']}")

    assert run_response.status_code == 200
    assert run_response.json() == runs[0]
