from pathlib import Path

from comic_agent.config import Settings


def test_local_runtime_paths_default_to_project_relative_locations(monkeypatch) -> None:
    monkeypatch.delenv("WORKSPACE_ROOT", raising=False)
    monkeypatch.delenv("IMAGE_QUEUE_ROOT", raising=False)
    monkeypatch.delenv("IMAGE_RUN_ROOT", raising=False)
    monkeypatch.delenv("FLUX_MODEL_PATH", raising=False)

    settings = Settings(_env_file=None)

    assert settings.workspace_root == Path(".")
    assert settings.image_queue_root == Path("queue")
    assert settings.image_run_root == Path("runs")
    assert settings.flux_model_path == Path("models/FLUX.2-klein-4B")
