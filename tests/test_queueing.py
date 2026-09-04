import io
from pathlib import Path

import pytest
from PIL import Image

from flux2_agent.catalog import write_catalog
from flux2_agent.cli import load_job_source
from flux2_agent.models import (
    GenerationSettings,
    SelectedAsset,
    Shot,
    ShotReference,
    WorkflowJob,
)
from flux2_agent.queueing import QueueStore, run_queue_worker


def workflow_job(job_id: str, asset_id: str = "asset-001") -> WorkflowJob:
    selected = SelectedAsset(
        slot="CHAR_A",
        asset_id=asset_id,
        entity_id="character.lead",
        role="character_identity",
        description="lead identity",
    )
    reference = ShotReference(
        slot="CHAR_A",
        asset_id=asset_id,
        role="character_identity",
        purpose="identity",
    )
    return WorkflowJob(
        job_id=job_id,
        source_script=f"story for {job_id}",
        comic_style="完整上色的连续漫画",
        global_prompt="one panel",
        selected_assets=[selected],
        generation=GenerationSettings(width=256, height=256, attempts=1),
        shots=[Shot(shot_id="shot-001", prompt="CHAR_A walks", references=[reference])],
    )


def test_queue_claims_by_priority_and_preserves_attempt_history(tmp_path: Path) -> None:
    store = QueueStore(tmp_path / "queue")
    store.enqueue(workflow_job("normal"), priority=100)
    store.enqueue(workflow_job("urgent"), priority=10)

    first = store.claim_next("worker-1")

    assert first is not None
    assert first.queue_id == "urgent"
    assert first.status == "running"
    assert first.attempts == 1

    failed = store.fail(first, "temporary failure")
    assert failed.status == "failed"
    assert failed.history[0].status == "failed"

    pending = store.retry("urgent")
    second = store.claim_next("worker-2")

    assert pending.status == "pending"
    assert second is not None
    assert second.queue_id == "urgent"
    assert second.attempts == 2
    run_root = tmp_path / "runs" / "urgent"
    run_root.mkdir(parents=True)
    succeeded = store.succeed(second, run_root)
    assert succeeded.status == "succeeded"
    assert [attempt.status for attempt in succeeded.history] == ["failed", "succeeded"]


def test_queue_rejects_duplicate_job_id(tmp_path: Path) -> None:
    store = QueueStore(tmp_path / "queue")
    store.enqueue(workflow_job("duplicate"))

    with pytest.raises(ValueError, match="already exists"):
        store.enqueue(workflow_job("duplicate"))


def test_queue_can_cancel_and_recover_interrupted_jobs(tmp_path: Path) -> None:
    store = QueueStore(tmp_path / "queue")
    store.enqueue(workflow_job("cancel-me"))
    cancelled = store.cancel("cancel-me")
    assert cancelled.status == "cancelled"

    store.enqueue(workflow_job("recover-me"))
    running = store.claim_next("worker-crashed")
    assert running is not None

    recovered = store.recover_running()

    assert [item.queue_id for item in recovered] == ["recover-me"]
    item = store.get("recover-me")
    assert item.status == "pending"
    assert item.history[0].status == "interrupted"


def test_queue_repairs_interrupted_state_transition(tmp_path: Path) -> None:
    store = QueueStore(tmp_path / "queue")
    store.enqueue(workflow_job("transition"))
    running = store.claim_next("worker-1")
    assert running is not None
    running_path = store.root / "running" / "transition.json"
    pending_path = store.root / "pending" / "transition.json"
    running_path.replace(pending_path)

    repaired = store.get("transition")

    assert repaired.status == "running"
    assert running_path.is_file()
    assert not pending_path.exists()


def test_worker_drains_two_jobs_with_one_model_load(
    tmp_path: Path,
    monkeypatch,
) -> None:
    reference_root = tmp_path / "inputs" / "references"
    reference_root.mkdir(parents=True)
    Image.new("RGB", (16, 16), "white").save(reference_root / "character.png")
    write_catalog(tmp_path)
    store = QueueStore(tmp_path / "queue")
    store.enqueue(workflow_job("second"), priority=100)
    store.enqueue(workflow_job("first"), priority=10)

    class FakeBackend:
        instances = 0
        loads = 0
        closes = 0

        def __init__(self, settings, **kwargs) -> None:
            type(self).instances += 1
            self.settings = settings
            self.model_source = settings.model_id

        def load(self) -> None:
            type(self).loads += 1

        def close(self) -> None:
            type(self).closes += 1

        def generate(self, shot, seed, *, continuity_path=None) -> Image.Image:
            color = "red" if seed % 2 else "blue"
            return Image.new("RGB", (16, 16), color)

    monkeypatch.setattr("flux2_agent.queueing.Flux2Backend", FakeBackend)

    completed = run_queue_worker(
        store,
        tmp_path,
        tmp_path / "runs",
        offline=True,
        worker_id="test-worker",
    )

    assert [item.queue_id for item in completed] == ["first", "second"]
    assert all(item.status == "succeeded" for item in completed)
    assert FakeBackend.instances == 1
    assert FakeBackend.loads == 1
    assert FakeBackend.closes == 1
    for item in completed:
        assert item.run_root is not None
        run_root = Path(item.run_root)
        assert (run_root / "shot-001.png").is_file()
        assert (run_root / "result.json").is_file()


def test_worker_failure_does_not_block_next_job(
    tmp_path: Path,
    monkeypatch,
) -> None:
    reference_root = tmp_path / "inputs" / "references"
    reference_root.mkdir(parents=True)
    Image.new("RGB", (16, 16), "white").save(reference_root / "character.png")
    write_catalog(tmp_path)
    store = QueueStore(tmp_path / "queue")
    store.enqueue(workflow_job("invalid", asset_id="asset-999"), priority=10)
    store.enqueue(workflow_job("valid"), priority=20)

    class FakeBackend:
        def __init__(self, settings, **kwargs) -> None:
            self.settings = settings

        def load(self) -> None:
            pass

        def close(self) -> None:
            pass

        def generate(self, shot, seed, *, continuity_path=None) -> Image.Image:
            return Image.new("RGB", (16, 16), "white")

    monkeypatch.setattr("flux2_agent.queueing.Flux2Backend", FakeBackend)

    completed = run_queue_worker(store, tmp_path, tmp_path / "runs")

    assert [(item.queue_id, item.status) for item in completed] == [
        ("invalid", "failed"),
        ("valid", "succeeded"),
    ]
    assert "unknown asset IDs" in (completed[0].error or "")


def test_upstream_can_submit_job_through_stdin(monkeypatch) -> None:
    expected = workflow_job("stdin-job")
    monkeypatch.setattr("sys.stdin", io.StringIO(expected.model_dump_json()))

    loaded = load_job_source("-")

    assert loaded == expected
