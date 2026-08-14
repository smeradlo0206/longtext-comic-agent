"""Chapter-scoped, Gate 1-authorized Narrative Analyst coordination tests."""

from pathlib import Path

from fastapi.testclient import TestClient

from comic_agent.main import create_app

PROJECT = {
    "id": "coord-project",
    "name": "Coordinator Project",
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

TEXT = "第一章 甲\n\n甲段落。\n\n第二章 乙\n\n乙段落。\n"
ALL_MODES = {
    "entity_extraction",
    "event_extraction",
    "claim_extraction",
    "knowledge_state_extraction",
    "state_change_extraction",
    "relationship_signal_extraction",
}


def _client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(database_url=f"sqlite+pysqlite:///{tmp_path / 'coord.db'}"))


def _import(client: TestClient) -> tuple[str, dict[str, object]]:
    assert client.post("/projects", json=PROJECT).status_code == 201
    response = client.post(
        "/projects/coord-project/documents/import",
        files={"file": ("coord.txt", TEXT.encode("utf-8"), "text/plain")},
    )
    assert response.status_code == 201
    payload = response.json()
    return payload["document"]["document_id"], payload


def test_default_modes_and_selected_chapter_are_gate1_authorized(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        document_id, _ = _import(client)
        selection = client.get(
            f"/projects/coord-project/documents/{document_id}/narrative-analysis-chapters"
        ).json()
        first_chapter_id = selection["chapters"][0]["chapter_id"]
        response = client.post(
            f"/projects/coord-project/documents/{document_id}/narrative-analysis-runs",
            json={"chapter_ids": [first_chapter_id]},
        )

    assert response.status_code == 201
    run = response.json()
    assert set(run["modes"]) == ALL_MODES
    assert run["windows_total"] >= 1
    assert run["selected_chapter_ids"] == [first_chapter_id]


def test_explicit_mode_subset_is_preserved(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        document_id, _ = _import(client)
        selection = client.get(
            f"/projects/coord-project/documents/{document_id}/narrative-analysis-chapters"
        ).json()
        chapter_id = selection["chapters"][1]["chapter_id"]
        response = client.post(
            f"/projects/coord-project/documents/{document_id}/narrative-analysis-runs",
            json={"chapter_ids": [chapter_id], "modes": ["state_change_extraction"]},
        )

    assert response.status_code == 201
    assert response.json()["modes"] == ["state_change_extraction"]


def test_unapproved_or_forged_selection_is_rejected_before_analysis(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        document_id, _ = _import(client)
        bad_chapter = client.post(
            f"/projects/coord-project/documents/{document_id}/narrative-analysis-runs",
            json={"chapter_ids": ["forged-chapter"]},
        )
        bad_mode = client.post(
            f"/projects/coord-project/documents/{document_id}/narrative-analysis-runs",
            json={"chapter_ids": [], "modes": ["relationship_signal_extraction"]},
        )

    assert bad_chapter.status_code == 400
    assert "chapter" in bad_chapter.json()["detail"].lower()
    assert bad_mode.status_code in {400, 422}
