"""Run the wired production Narrative -> Timeline E2E in an isolated environment."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from comic_agent.config import get_settings  # noqa: E402

DEFAULT_SOURCE = ROOT / "tests" / "golden_novel" / "source.txt"
ARTIFACTS_ROOT = ROOT / "artifacts"
SEPARATOR = "=" * 60
TERMINAL_NARRATIVE = {"SUCCEEDED", "PARTIAL_FAILED", "FAILED"}
ALLOWED_RELATIONS = {"BEFORE", "AFTER", "SIMULTANEOUS", "OVERLAPS", "UNKNOWN"}
STAGES = (
    "TXT Import",
    "Gate 1",
    "Chunking",
    "Whole-document Narrative",
    "Gate 2",
    "Coordinator",
    "TimelineAgent",
    "Gate 3",
    "Approved Timeline Bundle",
)
COMPLETED = "COMPLETED"
BLOCKED_ON_HUMAN_REVIEW = "BLOCKED_ON_HUMAN_REVIEW"
REJECTED_BY_HUMAN = "REJECTED_BY_HUMAN"
FAILED = "FAILED"


class SafeLog:
    def __init__(self, path: Path) -> None:
        self._stream = path.open("a", encoding="utf-8")

    def write(self, message: str = "") -> None:
        print(message, flush=True)
        self._stream.write(message + "\n")
        self._stream.flush()

    def close(self) -> None:
        self._stream.close()


class E2EFailure(RuntimeError):
    def __init__(self, stage: str, message: str, category: str = "INTEGRATION") -> None:
        super().__init__(message)
        self.stage = stage
        self.category = category


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--port", type=int, default=8011)
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--resume-run")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def artifact_dir() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    path = ARTIFACTS_ROOT / f"production_e2e_{stamp}"
    path.mkdir(parents=True, exist_ok=False)
    return path


def free_port(preferred: int, log: SafeLog) -> int:
    for port in range(preferred, preferred + 100):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                if port == preferred:
                    log.write(f"Port {preferred} is already in use.")
                continue
            if port != preferred:
                log.write(f"Using isolated API port {port} instead.")
            return port
    raise E2EFailure("API", "No free localhost port found", "CONFIG")


def run_preflight(log: SafeLog, verbose: bool) -> None:
    log.write("\n[START] LLM Preflight")
    command = [sys.executable, str(ROOT / "scripts" / "test_llm_connection.py")]
    if verbose:
        command.append("--verbose")
    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    output_lines = completed.stdout.splitlines()
    if verbose:
        for line in output_lines:
            log.write(line)
    else:
        concise_markers = (
            "[PASS] DNS",
            "[PASS] TCP 443",
            "[PASS] HTTPS transport",
            "[PASS] Models API",
            "[FAIL] DNS",
            "[FAIL] TCP 443",
            "[FAIL] HTTPS transport",
            "[FAIL] Models API",
            "[WARN] Chat Completions attempt",
            "[PASS] Chat Completions attempt",
            "[FAIL] Chat Completions",
        )
        for line in output_lines:
            if line.startswith(concise_markers):
                log.write(line.replace("[PASS] HTTPS transport", "[PASS] HTTPS"))
    category = _preflight_category(output_lines)
    if completed.returncode != 0:
        log.write("\n[FAIL] LLM PREFLIGHT")
        log.write("\nSchool VPN / USTC connectivity is not ready.")
        log.write("\nProduction E2E was NOT started.")
        raise E2EFailure(
            "LLM Preflight",
            "USTC LLM connectivity preflight failed",
            category or "UNKNOWN_ERROR",
        )
    log.write("\n[PASS] LLM PREFLIGHT")
    log.write("USTC LLM is reachable.")


def _preflight_category(lines: list[str]) -> str | None:
    for line in reversed(lines):
        match = re.fullmatch(r"Result:\s*([A-Z0-9_]+)", line.strip())
        if match:
            return match.group(1)
    for line in reversed(lines):
        match = re.fullmatch(r"Category:\s*([A-Z0-9_]+)", line.strip())
        if match:
            return match.group(1)
    return None


def find_resume_database(run_id: str) -> Path | None:
    for candidate in sorted(ARTIFACTS_ROOT.glob("production_e2e_*/e2e.sqlite"), reverse=True):
        try:
            with sqlite3.connect(f"file:{candidate}?mode=ro", uri=True) as connection:
                found = connection.execute(
                    "SELECT 1 FROM narrative_analysis_runs WHERE analysis_run_id = ?", (run_id,)
                ).fetchone()
            if found:
                return candidate
        except sqlite3.Error:
            continue
    return None


def start_api(database: Path, port: int, output_dir: Path, log: SafeLog) -> subprocess.Popen[str]:
    env = os.environ.copy()
    relative_db = database.resolve().as_posix()
    env["DATABASE_URL"] = f"sqlite+pysqlite:///{relative_db}"
    stdout_path = output_dir / "api.stdout.log"
    stderr_path = output_dir / "api.stderr.log"
    stdout = stdout_path.open("w", encoding="utf-8")
    stderr = stderr_path.open("w", encoding="utf-8")
    log.write("\n[START] API")
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "comic_agent.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=ROOT,
        env=env,
        stdout=stdout,
        stderr=stderr,
        text=True,
    )
    process._e2e_streams = (stdout, stderr)  # type: ignore[attr-defined]
    return process


def wait_for_api(
    process: subprocess.Popen[str], base_url: str, output_dir: Path, log: SafeLog
) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            break
        try:
            if httpx.get(f"{base_url}/health", timeout=2).status_code == 200:
                log.write(f"[PASS] API ready: {base_url}")
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    stderr = tail(output_dir / "api.stderr.log", 30)
    if stderr:
        log.write(stderr)
    raise E2EFailure("API", "Isolated API did not become ready", "CONFIG")


def tail(path: Path, lines: int) -> str:
    if not path.exists():
        return ""
    return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])


class API:
    def __init__(self, base_url: str, log: SafeLog, verbose: bool) -> None:
        self.client = httpx.Client(base_url=base_url, timeout=60)
        self.log = log
        self.verbose = verbose

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self.client.request(method, path, **kwargs)
        if self.verbose:
            self.log.write(f"HTTP {method} {path}: {response.status_code}")
        if response.status_code >= 400:
            detail = response.text.replace("\r", " ").replace("\n", " ")[:500]
            raise E2EFailure("API", f"{method} {path}: HTTP {response.status_code}: {detail}")
        return response.json()

    def close(self) -> None:
        self.client.close()


def db_counts(database: Path, project_id: str, run_id: str | None) -> dict[str, int]:
    counts: dict[str, int] = {}
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
        for label, table in (
            ("documents", "source_documents"),
            ("chapters", "source_chapters"),
            ("chunks", "source_chunks"),
            ("narrative_analysis_runs", "narrative_analysis_runs"),
            ("event_proposals", "event_proposals"),
            ("timeline_proposals", "timeline_analysis_proposals"),
            ("gate3_runs", "timeline_gate3_runs"),
        ):
            counts[label] = connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE project_id = ?", (project_id,)
            ).fetchone()[0]
        counts["narrative_windows"] = (
            connection.execute(
                "SELECT COUNT(*) FROM narrative_analysis_windows WHERE analysis_run_id = ?",
                (run_id,),
            ).fetchone()[0]
            if run_id
            else 0
        )
    return counts


def window_audit(database: Path, run_id: str) -> list[dict[str, Any]]:
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT payload FROM narrative_analysis_windows WHERE analysis_run_id = ? "
            "ORDER BY window_index, mode",
            (run_id,),
        ).fetchall()
    return [json.loads(row["payload"]) for row in rows]


def gate3_payload(database: Path, project_id: str, bundle_id: str) -> dict[str, Any] | None:
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
        row = connection.execute(
            "SELECT payload FROM timeline_gate3_runs WHERE project_id = ? AND source_bundle_id = ?",
            (project_id, bundle_id),
        ).fetchone()
    return json.loads(row[0]) if row else None


def narrative_checkpoint_complete(run: dict[str, Any]) -> bool:
    """Return whether resume can consume persisted downstream state without requeueing work."""

    return run.get("status") == "SUCCEEDED" and run.get("review_gate2_ready") is True


def gate3_business_decision(review: dict[str, Any]) -> tuple[str, str | None]:
    """Separate the effective business decision from successful Gate 3 execution."""

    result = review.get("result")
    route = review.get("route")
    if not isinstance(result, dict) or not isinstance(route, dict):
        raise E2EFailure("Gate 3", "Persisted Gate 3 review is malformed", "DATABASE")
    automated = result.get("decision")
    effective = result.get("effective_decision") or route.get("route")
    human = result.get("human_review")
    human_decision = human.get("final_decision") if isinstance(human, dict) else None
    if automated not in {"APPROVED", "REJECTED", "NEEDS_HUMAN_REVIEW", "FAILED"}:
        raise E2EFailure("Gate 3", "Persisted Gate 3 decision is invalid", "DATABASE")
    if effective not in {"APPROVED", "REJECTED", "NEEDS_HUMAN_REVIEW", "FAILED"}:
        raise E2EFailure("Gate 3", "Persisted effective Gate 3 decision is invalid", "DATABASE")
    return str(effective), str(human_decision) if human_decision is not None else None


def poll_narrative(api: API, run_id: str, deadline: float, log: SafeLog) -> dict[str, Any]:
    previous: tuple[Any, ...] | None = None
    while time.monotonic() < deadline:
        run: dict[str, Any] = api.request("GET", f"/narrative-analysis-runs/{run_id}")
        state = (run["status"], run["windows_succeeded"], run["windows_failed"])
        if state != previous:
            log.write(
                f"Narrative: {state[0]} "
                f"(windows succeeded={state[1]}, failed={state[2]})"
            )
            previous = state
        if run["status"] in {"PARTIAL_FAILED", "FAILED"}:
            return run
        if run["status"] == "SUCCEEDED" and run.get("review_gate2_ready") is True:
            return run
        time.sleep(2)
    raise E2EFailure("Whole-document Narrative", "Overall workflow timeout", "TIMEOUT")


def validate_timeline(payload: dict[str, Any], chunks: dict[str, str]) -> dict[str, int]:
    proposal = payload.get("timeline_proposal")
    if not isinstance(proposal, dict):
        raise E2EFailure("TimelineAgent", "Gate 3 run has no persisted timeline proposal")
    relations = proposal.get("temporal_relations", [])
    for relation in relations:
        value = relation.get("relation")
        if value not in ALLOWED_RELATIONS:
            raise E2EFailure("TimelineAgent", f"Invalid temporal relation: {value}", "SCHEMA")
        evidence = relation.get("evidence_refs", [])
        if value != "UNKNOWN" and not evidence:
            raise E2EFailure("TimelineAgent", "Known relation has no evidence", "SCHEMA")
        for reference in evidence:
            chunk_id = reference.get("chunk_id")
            quote = reference.get("quote_text")
            if chunk_id not in chunks or (quote is not None and quote not in chunks[chunk_id]):
                raise E2EFailure(
                    "TimelineAgent",
                    "Timeline EvidenceRef is outside source evidence",
                    "SCHEMA",
                )
    return {
        "relations": len(relations),
        "conflicts": len(proposal.get("conflicts", [])),
        "duplicates": len(proposal.get("duplicate_candidates", [])),
    }


def write_result(path: Path, result: dict[str, Any]) -> None:
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


def stop_process(process: subprocess.Popen[str] | None) -> None:
    if process is None:
        return
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    for stream in getattr(process, "_e2e_streams", ()):
        stream.close()


def execute(
    args: argparse.Namespace, output_dir: Path, log: SafeLog, result: dict[str, Any]
) -> str:
    settings = get_settings()
    effective_timeline_model = settings.timeline_model or settings.storybible_model
    log.write("\n[CONFIG]")
    log.write(f"Narrative model: {settings.llm_model}")
    log.write(f"Timeline model: {effective_timeline_model}")
    source = args.source.resolve()
    if not args.resume_run:
        if not source.is_file() or source.suffix.lower() != ".txt":
            raise E2EFailure("Configuration", f"TXT source not found: {source}", "CONFIG")
        if not settings.enable_real_llm or not settings.timeline_llm_enabled:
            raise E2EFailure(
                "Configuration",
                "ENABLE_REAL_LLM and TIMELINE_LLM_ENABLED must both be true",
                "CONFIG",
            )
        if settings.llm_api_key is None or not settings.llm_api_key.get_secret_value():
            raise E2EFailure("Configuration", "LLM_API_KEY is not configured", "CONFIG")
        log.write("LLM_API_KEY: configured")
        run_preflight(log, args.verbose)
    else:
        log.write("Resume mode: persisted checkpoints will be inspected before any requeue")

    database = output_dir / "e2e.sqlite"
    if args.resume_run:
        existing = find_resume_database(args.resume_run)
        if existing is None:
            raise E2EFailure("Configuration", f"Resume run not found: {args.resume_run}", "CONFIG")
        shutil.copy2(existing, database)
        log.write(f"Resume source database: {existing}")
        log.write(f"Resuming in isolated database copy: {database}")
    result["artifact_paths"]["database"] = str(database)

    port = free_port(args.port, log)
    base_url = f"http://127.0.0.1:{port}"
    process: subprocess.Popen[str] | None = None
    api: API | None = None
    try:
        process = start_api(database, port, output_dir, log)
        wait_for_api(process, base_url, output_dir, log)
        api = API(base_url, log, args.verbose)
        status = api.request("GET", "/settings/llm/status")
        if not args.resume_run and (
            not status.get("enable_real_llm") or not status.get("api_key_non_empty")
        ):
            raise E2EFailure("Configuration", "Real LLM configuration is not enabled", "CONFIG")
        result["llm"] = {
            "provider": status.get("provider_name"),
            "narrative_model": status.get("model"),
            "timeline_model": effective_timeline_model,
            "mock_or_fallback_used": False,
        }

        if args.resume_run:
            run_id = args.resume_run
            current = api.request("GET", f"/narrative-analysis-runs/{run_id}")
            result.update(
                project_id=current["project_id"],
                document_id=current["document_id"],
                narrative_run_id=run_id,
            )
            existing_counts = db_counts(database, current["project_id"], run_id)
            if existing_counts["documents"] > 0:
                result["stage_status"]["TXT Import"] = "PASS"
            if existing_counts["chapters"] > 0 and existing_counts["chunks"] > 0:
                result["stage_status"]["Gate 1"] = "PASS"
                result["stage_status"]["Chunking"] = "PASS"
            log.write("\n[START] Whole-document Narrative resume")
            log.write(f"Run ID: {run_id}")
            if narrative_checkpoint_complete(current):
                log.write("[PASS] Persisted Narrative/Gate 2 checkpoint reused; no LLM requeue")
            else:
                raise E2EFailure(
                    "Whole-document Narrative",
                    "Resume requires unfinished Narrative work; "
                    "explicit fresh execution is required",
                    "RESUME_REQUIRES_LLM",
                )
        else:
            project_id = f"production-e2e-{uuid4().hex[:8]}"
            result["project_id"] = project_id
            api.request(
                "POST",
                "/projects",
                json={"project_id": project_id, "name": "Production E2E"},
            )
            with source.open("rb") as stream:
                imported = api.request(
                    "POST",
                    f"/projects/{project_id}/documents/import",
                    files={"file": (source.name, stream, "text/plain")},
                )
            document = imported["document"]
            result["document_id"] = document["document_id"]
            result["stage_status"]["TXT Import"] = "PASS"
            log.write("\n[PASS] Document Import")
            log.write(f"Document: {document['document_id']}")
            log.write(f"Chapters: {imported['chapters_count']}")
            log.write(f"Chunks: {imported['chunks_count']}")
            decision = imported.get("gate1", {}).get("decision")
            if decision != "APPROVED":
                raise E2EFailure("Gate 1", f"Gate 1 decision: {decision}", "GATE")
            result["stage_status"]["Gate 1"] = "PASS"
            result["stage_status"]["Chunking"] = "PASS"
            log.write("\n[PASS] Gate 1")
            log.write("Decision: APPROVED")
            log.write("[PASS] Chunking")
            created = api.request(
                "POST",
                f"/projects/{project_id}/documents/{document['document_id']}/narrative-analysis-runs",
                json={
                    "modes": ["event_extraction"],
                    "document_revision": document["revision"],
                    "real_llm_requested": True,
                },
            )
            run_id = created["analysis_run_id"]
            result["narrative_run_id"] = run_id
            log.write("\n[START] Whole-document Narrative")
            log.write(f"Run ID: {run_id}")

        deadline = time.monotonic() + args.timeout
        run = poll_narrative(api, run_id, deadline, log)
        counts = db_counts(database, result["project_id"], run_id)
        result["counts"].update(counts)
        if run["status"] != "SUCCEEDED":
            windows = window_audit(database, run_id)
            failures = [item for item in windows if item.get("status") == "FAILED"]
            first = failures[0] if failures else {}
            result["failure_category"] = first.get("failure_category") or run["status"]
            result["provider_attempts"] = sum(int(item.get("attempt_count", 0)) for item in windows)
            log.write("\n[FAIL] Whole-document Narrative")
            log.write(f"Run ID: {run_id}")
            log.write(f"Failure category: {result['failure_category']}")
            log.write(f"Error: {first.get('error_message') or 'Narrative run did not succeed'}")
            log.write(f"Windows succeeded: {run['windows_succeeded']}")
            log.write(f"Windows failed: {run['windows_failed']}")
            log.write(f"Provider attempts: {result['provider_attempts']}")
            if result["failure_category"] == "PROVIDER_CONNECTION_ERROR":
                log.write(
                    "USTC connectivity worked during preflight but provider failed during workflow."
                )
            raise E2EFailure(
                "Whole-document Narrative",
                first.get("error_message") or "Narrative run failed",
                result["failure_category"],
            )
        result["stage_status"]["Whole-document Narrative"] = "PASS"
        log.write("\n[PASS] Whole-document Narrative")
        log.write(f"Run: {run_id}")
        log.write(f"Windows: {run['windows_succeeded']}/{run['windows_total']}")
        log.write(f"Event proposals materialized: {counts['event_proposals']}")

        gate2 = api.request("GET", f"/narrative-analysis-runs/{run_id}/review-gate2")
        route = gate2["route"]
        decision = route["decision"]
        result["counts"]["gate2_runs"] = 1
        result["counts"]["approved_narrative_proposals"] = route["approved_count"]
        if decision != "APPROVED" or not route.get("approved_proposal_bundle"):
            category = "HUMAN_APPROVAL" if decision == "NEEDS_HUMAN_REVIEW" else "GATE"
            raise E2EFailure("Gate 2", f"Gate 2 decision: {decision}", category)
        result["stage_status"]["Gate 2"] = "PASS"
        bundle = route["approved_proposal_bundle"]
        bundle_id = bundle["bundle_id"]
        log.write("\n[PASS] Gate 2")
        log.write(f"Decision: {decision} (deterministic review)")
        log.write(f"Approved proposals: {route['approved_count']}")
        log.write(f"Rejected proposals: {route['rejected_count']}")

        gate3: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            response = api.client.get(
                f"/projects/{result['project_id']}/timeline-gate3/{bundle_id}"
            )
            if response.status_code == 200:
                gate3 = response.json()
                if gate3.get("gate3_ready"):
                    break
            elif response.status_code != 409:
                raise E2EFailure("Coordinator", f"Gate 3 status HTTP {response.status_code}")
            time.sleep(2)
        if gate3 is None:
            raise E2EFailure("Coordinator", "Timeline workflow was not triggered", "COORDINATOR")
        result["stage_status"]["Coordinator"] = "PASS"
        log.write("\n[PASS] Coordinator")
        log.write("Timeline workflow triggered")

        persisted = gate3_payload(database, result["project_id"], bundle_id)
        if persisted is None:
            raise E2EFailure("TimelineAgent", "Timeline Gate 3 persistence is missing", "DATABASE")
        timeline_input = persisted.get("timeline_input")
        if not isinstance(timeline_input, dict) or timeline_input.get("mode") != "LLM":
            raise E2EFailure("TimelineAgent", "Persisted Timeline mode is not LLM", "INTEGRATION")
        with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
            chunks = dict(
                connection.execute(
                    "SELECT chunk_id, text FROM source_chunks WHERE project_id = ?",
                    (result["project_id"],),
                ).fetchall()
            )
        timeline_counts = validate_timeline(persisted, chunks)
        proposal = persisted["timeline_proposal"]
        gate3_run_id = persisted.get("timeline_run_id")
        if not isinstance(gate3_run_id, str) or not gate3_run_id:
            raise E2EFailure("Gate 3", "Persisted Gate 3 run id is missing", "DATABASE")
        result["gate3_run_id"] = gate3_run_id
        result["timeline_run_id"] = gate3_run_id
        result["gate2_approved_bundle_id"] = bundle_id
        result["timeline_proposal_id"] = proposal["proposal_id"]
        result["counts"].update(timeline_counts)
        result["counts"]["gate3_runs"] = 1
        result["stage_status"]["TimelineAgent"] = "PASS"
        log.write("\n[PASS] TimelineAgent")
        log.write("Mode: LLM")
        log.write(f"Model: {result['llm']['timeline_model']}")
        log.write(f"Relations: {timeline_counts['relations']}")
        log.write(f"Conflicts: {timeline_counts['conflicts']}")
        log.write(f"Duplicates: {timeline_counts['duplicates']}")

        review = api.request(
            "GET", f"/projects/{result['project_id']}/timeline-gate3/{bundle_id}/review"
        )
        gate3_decision, human_decision = gate3_business_decision(review)
        result["stage_status"]["Gate 3"] = "PASS"
        result["gate3_execution"] = "PASS"
        result["gate3_decision"] = gate3_decision
        result["human_review_decision"] = human_decision
        log.write("\n[PASS] Gate 3 execution")
        log.write(f"Decision: {gate3_decision}")
        if human_decision is not None:
            log.write(f"Human review: {human_decision}")
        if gate3_decision == "NEEDS_HUMAN_REVIEW":
            issues = review["result"].get("issues", [])
            issue_ids = [item.get("issue_id") for item in issues if isinstance(item, dict)]
            result["gate3_issue_ids"] = [item for item in issue_ids if isinstance(item, str)]
            result["stage_status"]["Approved Timeline Bundle"] = BLOCKED_ON_HUMAN_REVIEW
            log.write("Approved Timeline Bundle: BLOCKED_ON_HUMAN_REVIEW")
            log.write(f"Project ID: {result['project_id']}")
            log.write(f"Production run ID: {run_id}")
            log.write(f"Gate 3 run ID: {gate3_run_id}")
            log.write(
                "Review endpoint: "
                f"/projects/{result['project_id']}/timeline-gate3/runs/{gate3_run_id}/review"
            )
            return BLOCKED_ON_HUMAN_REVIEW
        if gate3_decision == "REJECTED" and human_decision == "REJECTED":
            result["stage_status"]["Approved Timeline Bundle"] = "NOT_CREATED"
            log.write("Approved Timeline Bundle: NOT_CREATED")
            return REJECTED_BY_HUMAN
        if gate3_decision != "APPROVED":
            raise E2EFailure("Gate 3", f"Gate 3 decision: {gate3_decision}", "GATE")
        approved_response = api.client.get(
            f"/projects/{result['project_id']}/timeline-gate3/{bundle_id}/approved-bundle"
        )
        if approved_response.status_code == 409:
            result["stage_status"]["Approved Timeline Bundle"] = "FINALIZATION_REQUIRED"
            raise E2EFailure(
                "Approved Timeline Bundle",
                "Gate 3 is approved but bundle finalization must be retried through human review",
                "FINALIZATION_REQUIRED",
            )
        if approved_response.status_code != 200:
            raise E2EFailure(
                "Approved Timeline Bundle",
                f"Approved bundle HTTP {approved_response.status_code}",
                "API",
            )
        approved = approved_response.json()
        if not approved:
            raise E2EFailure("Approved Timeline Bundle", "Approved timeline bundle is empty")
        result["approved_timeline_bundle_id"] = approved.get("bundle_id")
        result["counts"]["approved_timeline_bundles"] = 1
        result["stage_status"]["Approved Timeline Bundle"] = "PASS"
        log.write("\n[PASS] Approved Timeline Bundle")
        return COMPLETED
    finally:
        if api is not None:
            api.close()
        stop_process(process)


def main() -> int:
    args = parse_args()
    output_dir = artifact_dir()
    log = SafeLog(output_dir / "run.log")
    result: dict[str, Any] = {
        "project_id": None,
        "document_id": None,
        "narrative_run_id": None,
        "timeline_proposal_id": None,
        "timeline_run_id": None,
        "gate3_run_id": None,
        "gate2_approved_bundle_id": None,
        "approved_timeline_bundle_id": None,
        "stage_status": {stage: "NOT REACHED" for stage in STAGES},
        "counts": {},
        "failure_stage": None,
        "failure_category": None,
        "artifact_paths": {
            "directory": str(output_dir),
            "database": str(output_dir / "e2e.sqlite"),
            "result": str(output_dir / "result.json"),
            "log": str(output_dir / "run.log"),
        },
    }
    exit_code = 1
    try:
        log.write(SEPARATOR)
        log.write("PRODUCTION E2E")
        log.write(SEPARATOR)
        result["result"] = execute(args, output_dir, log, result)
        exit_code = 0
    except KeyboardInterrupt:
        result["failure_stage"] = "Interrupted"
        result["failure_category"] = "INTERRUPTED"
        log.write("\nInterrupted by user.")
        log.write(f"Artifacts preserved at: {output_dir}")
        exit_code = 130
    except E2EFailure as exc:
        result["failure_stage"] = exc.stage
        result["failure_category"] = exc.category
        if (
            exc.stage in result["stage_status"]
            and result["stage_status"][exc.stage] == "NOT REACHED"
        ):
            result["stage_status"][exc.stage] = "FAIL"
        log.write(f"\nFirst blocker:\nStage: {exc.stage}\nCategory: {exc.category}\nError: {exc}")
        exit_code = 2 if exc.stage in {"Configuration", "LLM Preflight", "API"} else 1
    except Exception as exc:
        result["failure_stage"] = "Runner"
        result["failure_category"] = "UNEXPECTED"
        log.write(
            "\nFirst blocker:\n"
            f"Stage: Runner\nCategory: UNEXPECTED\nError: {type(exc).__name__}: {exc}"
        )
        exit_code = 1
    finally:
        if exit_code != 0:
            result["result"] = FAILED
        write_result(output_dir / "result.json", result)
        log.write(f"\n{SEPARATOR}\nFINAL RESULT\n{SEPARATOR}")
        for stage in STAGES:
            log.write(f"{stage + ':':30} {result['stage_status'][stage]}")
        log.write(f"\nResult: {result['result']}")
        log.write(f"\nArtifacts:\n{output_dir}")
        log.close()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
