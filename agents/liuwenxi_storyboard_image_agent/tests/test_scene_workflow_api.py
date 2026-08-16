from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from anime_image_agent.api import create_app
from anime_image_agent.scene_contracts import SceneJobStatus
from anime_image_agent.scene_coordinator import SceneCoordinator
from anime_image_agent.scene_generation import (
    FakeSceneGenerator,
    ScenePromptTooLongError,
    _encode_prompt_to_cpu,
    _prepare_qwen_edit_condition_images,
    classify_scene_generation_error,
)
from anime_image_agent.scene_store import SceneStore

from .scene_helpers import make_asset_repository, make_scene_settings, scene_job, upstream_envelope


def test_qwen_edit_condition_images_match_pipeline_preprocessing() -> None:
    from PIL import Image

    class ImageProcessor:
        def __init__(self) -> None:
            self.calls = []

        def resize(self, image, height, width):
            self.calls.append((image.size, height, width))
            return image.resize((width, height))

    class Pipeline:
        image_processor = ImageProcessor()

    images = [Image.new("RGB", (800, 400)), Image.new("RGB", (400, 800))]
    prepared = _prepare_qwen_edit_condition_images(Pipeline(), images)

    assert Pipeline.image_processor.calls == [
        ((800, 400), 256, 544),
        ((400, 800), 544, 256),
    ]
    assert [image.size for image in prepared] == [(544, 256), (256, 544)]


def test_conditioning_embeddings_are_encoded_in_inference_mode_and_moved_to_cpu() -> None:
    torch = pytest.importorskip("torch")

    class Tokenizer:
        def __call__(self, *args, **kwargs):
            return {"input_ids": [11, 12, 13]}

    class Processor:
        tokenizer = Tokenizer()

    class Pipeline:
        processor = Processor()

        def encode_prompt(self, **kwargs):
            assert torch.is_inference_mode_enabled()
            embeddings = torch.ones((1, 4, 8), requires_grad=True)
            mask = torch.tensor([[1, 1, 1, 0]])
            return embeddings, mask

    embeddings, mask, token_count = _encode_prompt_to_cpu(
        Pipeline(),
        prompt="test",
        images=[],
        device=torch.device("cpu"),
        max_sequence_length=8,
    )
    assert embeddings.device.type == "cpu"
    assert embeddings.requires_grad is False
    assert mask.device.type == "cpu"
    assert token_count == 3

    class PipelineWithoutMask(Pipeline):
        def encode_prompt(self, **kwargs):
            assert torch.is_inference_mode_enabled()
            return torch.ones((1, 4, 8)), None

    _, generated_mask, _ = _encode_prompt_to_cpu(
        PipelineWithoutMask(),
        prompt="test",
        images=[],
        device=torch.device("cpu"),
        max_sequence_length=8,
    )
    assert generated_mask.tolist() == [[1, 1, 1, 1]]

    with pytest.raises(ScenePromptTooLongError):
        _encode_prompt_to_cpu(
            Pipeline(),
            prompt="test",
            images=[],
            device=torch.device("cpu"),
            max_sequence_length=2,
        )
    error = classify_scene_generation_error(
        ScenePromptTooLongError("too long"), "CONDITIONING_FAILED"
    )
    assert error.code == "PROMPT_TOO_LONG"
    assert error.retryable is False


def test_scene_store_idempotency_and_fake_workflow(tmp_path) -> None:
    settings = make_scene_settings(tmp_path)
    repository = make_asset_repository(settings)
    store = SceneStore(settings.scene_db)
    job = scene_job(panels=3)
    first, created = store.submit(job)
    second, created_again = store.submit(job)
    assert created and not created_again
    assert first.request_sha256 == second.request_sha256

    coordinator = SceneCoordinator(
        settings,
        backend="fake",
        store=store,
        repository=repository,
        generator=FakeSceneGenerator(),
    )
    assert coordinator.run(drain=True) == 1
    result = store.result(job.request_id)
    assert result.status == SceneJobStatus.SUCCEEDED
    assert [panel.artifact.width for panel in result.panels] == [1664, 928, 1328]
    assert all(panel.metadata.seed == panel.generation_spec.seed for panel in result.panels)


def test_partial_failure_and_resume_skip_success(tmp_path) -> None:
    settings = make_scene_settings(tmp_path)
    repository = make_asset_repository(settings)
    store = SceneStore(settings.scene_db)
    job = scene_job(panels=2)
    store.submit(job)
    coordinator = SceneCoordinator(
        settings,
        backend="fake",
        store=store,
        repository=repository,
        generator=FakeSceneGenerator({"panel-01"}),
    )
    coordinator.run(drain=True)
    result = store.result(job.request_id)
    assert result.status == SceneJobStatus.PARTIAL_FAILED
    assert [panel.status.value for panel in result.panels] == ["SUCCEEDED", "FAILED"]


def test_api_submission_conflict_result_and_artifact(tmp_path) -> None:
    settings = make_scene_settings(tmp_path)
    repository = make_asset_repository(settings)
    store = SceneStore(settings.scene_db)
    coordinator = SceneCoordinator(
        settings,
        backend="fake",
        store=store,
        repository=repository,
        generator=FakeSceneGenerator(),
    )
    app = create_app(
        settings,
        backend="fake",
        start_coordinator=False,
        coordinator=coordinator,
    )
    envelope = upstream_envelope()
    with TestClient(app) as client:
        response = client.post("/v1/scene-jobs", json=envelope.model_dump(mode="json"))
        assert response.status_code == 202
        assert response.json()["idempotent"] is False
        assert client.post("/v1/scene-jobs", json=envelope.model_dump(mode="json")).json()["idempotent"] is True

        changed_payload = envelope.model_dump(mode="json")
        changed_payload["events"][0]["action"] = "changed only in an envelope field lost by V1 mapping"
        assert client.post("/v1/scene-jobs", json=changed_payload).status_code == 409
        assert client.get(f"/v1/scene-jobs/{envelope.request_id}/result").status_code == 202

        coordinator.run(drain=True)
        result_response = client.get(f"/v1/scene-jobs/{envelope.request_id}/result")
        assert result_response.status_code == 200
        image_id = result_response.json()["panels"][0]["artifact"]["image_id"]
        artifact = client.get(f"/v1/artifacts/{image_id}")
        assert artifact.status_code == 200
        assert artifact.headers["content-type"] == "image/png"
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready").status_code == 200


def test_http_boundary_has_one_task_ingress_and_rejects_internal_scene_job(tmp_path) -> None:
    settings = make_scene_settings(tmp_path)
    repository = make_asset_repository(settings)
    coordinator = SceneCoordinator(
        settings,
        backend="fake",
        store=SceneStore(settings.scene_db),
        repository=repository,
        generator=FakeSceneGenerator(),
    )
    app = create_app(
        settings,
        backend="fake",
        start_coordinator=False,
        coordinator=coordinator,
    )

    write_routes = {
        (route.path, method)
        for route in app.routes
        for method in (route.methods or set())
        if method in {"POST", "PUT", "PATCH", "DELETE"}
    }
    assert write_routes == {("/v1/scene-jobs", "POST")}

    openapi = app.openapi()
    request_schema = openapi["paths"]["/v1/scene-jobs"]["post"]["requestBody"]["content"][
        "application/json"
    ]["schema"]
    assert request_schema["$ref"].endswith("/UpstreamSceneEnvelopeV1")

    with TestClient(app) as client:
        response = client.post("/v1/scene-jobs", json=scene_job().model_dump(mode="json"))
    assert response.status_code == 422


def test_wave_handles_32_panels_and_isolates_same_panel_ids(tmp_path) -> None:
    settings = make_scene_settings(tmp_path)
    repository = make_asset_repository(settings)
    store = SceneStore(settings.scene_db)
    large = scene_job("scene-large", panels=32)
    store.submit(large)
    coordinator = SceneCoordinator(
        settings,
        backend="fake",
        store=store,
        repository=repository,
        generator=FakeSceneGenerator(),
    )
    assert coordinator.run_once() == 1
    assert store.result("scene-large").status == SceneJobStatus.SUCCEEDED

    first = scene_job("same-panel-a")
    second = scene_job("same-panel-b")
    store.submit(first)
    store.submit(second)
    assert coordinator.run_once() == 2
    first_result = store.result(first.request_id)
    second_result = store.result(second.request_id)
    assert first_result.status == second_result.status == SceneJobStatus.SUCCEEDED
    assert first_result.panels[0].artifact.image_id != second_result.panels[0].artifact.image_id
    assert first_result.panels[0].artifact.sha256 != second_result.panels[0].artifact.sha256
