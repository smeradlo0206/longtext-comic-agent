"""Run the real-LLM event-to-timeline demo without using Swagger.

Start the API first with ``scripts/run_local_ustc.ps1`` in a separate terminal.
This script imports the bundled test novel, runs one real event-extraction batch,
then sends the resulting event proposals to TimelineAgent in LLM mode.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = PROJECT_ROOT / "tests" / "golden_novel" / "source.txt"
DEFAULT_OUTPUT = PROJECT_ROOT / "artifacts" / "timeline_llm_demo_result.json"


def _request(
    client: httpx.Client,
    method: str,
    path: str,
    **kwargs: Any,
) -> Any:
    response = client.request(method, path, **kwargs)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = response.text[:500].replace("\n", " ")
        message = f"{method} {path} failed: HTTP {response.status_code}: {detail}"
        raise RuntimeError(message) from exc
    return response.json()


def _select_chunks(client: httpx.Client, project_id: str, limit: int = 3) -> list[dict[str, Any]]:
    chapters = _request(client, "GET", f"/projects/{project_id}/chapters")
    selected: list[dict[str, Any]] = []
    for chapter in chapters:
        chunks = _request(client, "GET", f"/chapters/{chapter['chapter_id']}/chunks")
        for chunk in chunks:
            selected.append(chunk)
            if len(selected) == limit:
                return selected
    return selected


def _final_summary(
    timeline: dict[str, Any], event_count: int, chunk_ids: list[str]
) -> dict[str, Any]:
    return {
        "project_id": timeline["project_id"],
        "timeline_proposal_id": timeline["proposal_id"],
        "input_event_count": event_count,
        "input_chunk_ids": chunk_ids,
        "temporal_relations": timeline.get("temporal_relations", []),
        "conflicts": timeline.get("conflicts", []),
        "duplicate_candidates": timeline.get("duplicate_candidates", []),
        "evidence_refs": timeline.get("evidence_refs", []),
        "confidence": timeline.get("confidence"),
    }


def run(api_base_url: str, source_path: Path, output_path: Path) -> dict[str, Any]:
    project_id = f"timeline-llm-demo-{uuid4().hex[:8]}"
    with httpx.Client(base_url=api_base_url.rstrip("/"), timeout=180) as client:
        status = _request(client, "GET", "/settings/llm/status")
        if not status.get("enable_real_llm") or not status.get("api_key_non_empty"):
            raise RuntimeError(
                "Real LLM is not enabled or LLM_API_KEY is empty in the running API."
            )

        _request(
            client,
            "POST",
            "/projects",
            json={"project_id": project_id, "name": "Automated Timeline LLM Demo"},
        )
        with source_path.open("rb") as source_file:
            imported = _request(
                client,
                "POST",
                f"/projects/{project_id}/documents/import",
                files={"file": (source_path.name, source_file, "text/plain")},
            )
        if not imported.get("analysis_eligible"):
            raise RuntimeError("The imported document was not approved for analysis.")

        chunks = _select_chunks(client, project_id)
        if len(chunks) < 2:
            raise RuntimeError("The test novel must produce at least two chunks.")
        chunk_ids = [str(chunk["chunk_id"]) for chunk in chunks]
        event_run = _request(
            client,
            "POST",
            f"/projects/{project_id}/agent-runs/narrative-analyst",
            json={
                "mode": "event_extraction",
                "chunk_ids": chunk_ids,
                "real_llm_requested": True,
            },
        )
        proposal = event_run.get("proposal")
        events = proposal.get("events", []) if isinstance(proposal, dict) else []
        if len(events) < 2:
            raise RuntimeError(
                "Real event extraction returned fewer than two events; "
                "Timeline LLM needs an event pair."
            )

        timeline = _request(
            client,
            "POST",
            f"/projects/{project_id}/timeline/analyze",
            json={
                "project_id": project_id,
                "mode": "LLM",
                "event_proposals": events,
                "claim_proposals": [],
                "state_change_proposals": [],
            },
        )

    result = _final_summary(timeline, len(events), chunk_ids)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    source_path = args.source.resolve()
    output_path = args.output.resolve()
    if not source_path.is_file():
        print(f"Source TXT not found: {source_path}", file=sys.stderr)
        return 1

    try:
        result = run(args.api_base_url, source_path, output_path)
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        print(f"Timeline demo failed: {exc}", file=sys.stderr)
        return 1

    print("Timeline LLM demo succeeded.")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"Full result saved to: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
