from __future__ import annotations

import json

import pytest

from anime_image_agent.contracts import ImageErrorV1
from anime_image_agent.queue import QueueConflictError, QueueStore

from .helpers import make_settings, valid_job


def test_submission_is_idempotent_but_conflicting_content_is_rejected(tmp_path) -> None:
    queue = QueueStore(make_settings(tmp_path))
    job = valid_job()
    first = queue.enqueue(job)
    second = queue.enqueue(job)
    assert first.state == second.state == "inbox"

    changed_prompt = job.prompt_spec.model_copy(update={"positive_prompt": "不同的提示词"})
    changed_job = job.model_copy(update={"prompt_spec": changed_prompt})
    with pytest.raises(QueueConflictError):
        queue.enqueue(changed_job)


def test_queue_orders_by_sequence_and_retries_three_attempts(tmp_path) -> None:
    settings = make_settings(tmp_path)
    queue = QueueStore(settings)
    queue.enqueue(valid_job("request-003", 3))
    queue.enqueue(valid_job("request-001", 1))
    queue.enqueue(valid_job("request-002", 2))
    accepted, rejected = queue.ingest()
    assert (accepted, rejected) == (3, 0)

    records = queue.select_wave(3)
    assert [record.job.sequence_no for record in records] == [1, 2, 3]
    error = ImageErrorV1(code="GENERATION_FAILED", message="injected", retryable=True)
    request_id = records[0].job.request_id
    assert queue.retry_or_fail(request_id, error)
    assert queue.status(request_id).record.attempt == 2
    queue.select_wave(1)
    assert queue.retry_or_fail(request_id, error)
    assert queue.status(request_id).record.attempt == 3
    queue.select_wave(1)
    assert not queue.retry_or_fail(request_id, error)
    status = queue.status(request_id)
    assert status.state == "failed"
    assert status.result is not None
    assert status.result.attempts == 3


def test_non_retryable_error_is_rejected(tmp_path) -> None:
    queue = QueueStore(make_settings(tmp_path))
    queue.enqueue(valid_job())
    queue.ingest()
    record = queue.select_wave(1)[0]
    error = ImageErrorV1(code="PROMPT_TOO_LONG", message="too long", retryable=False)
    assert not queue.retry_or_fail(record.job.request_id, error)
    assert queue.status(record.job.request_id).state == "rejected"


def test_malformed_direct_inbox_file_is_quarantined(tmp_path) -> None:
    queue = QueueStore(make_settings(tmp_path))
    source = queue.settings.queue_root / "inbox" / "broken.json"
    source.write_text(json.dumps({"schema_name": "ImageJobV1", "bad": True}), encoding="utf-8")
    accepted, rejected = queue.ingest()
    assert (accepted, rejected) == (0, 1)
    assert list((queue.settings.queue_root / "invalid").glob("broken.*.json"))


def test_running_task_is_recovered_with_new_attempt(tmp_path) -> None:
    queue = QueueStore(make_settings(tmp_path))
    queue.enqueue(valid_job())
    queue.ingest()
    queue.select_wave(1)
    assert queue.recover_running() == 1
    status = queue.status("request-001")
    assert status.state == "ready"
    assert status.record.attempt == 2


def test_direct_duplicate_of_terminal_request_is_not_requeued(tmp_path) -> None:
    queue = QueueStore(make_settings(tmp_path))
    job = valid_job()
    queue.enqueue(job)
    queue.ingest()
    record = queue.select_wave(1)[0]
    queue.retry_or_fail(
        record.job.request_id,
        ImageErrorV1(code="INVALID_PROMPT", message="rejected", retryable=False),
    )

    duplicate = queue.settings.queue_root / "inbox" / "direct-duplicate.json"
    duplicate.write_text(job.model_dump_json(indent=2), encoding="utf-8")
    assert queue.ingest() == (1, 0)
    assert queue.status(job.request_id).state == "rejected"
    assert queue.ready_count() == 0
