from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from PIL import Image, ImageStat

from .config import PROFILE, Settings
from .contracts import (
    ArtifactV1,
    GeneratedImageV1,
    GenerationMetadataV1,
    ImageResultV1,
    QueueRecordV1,
    ResultStatus,
)
from .io_utils import atomic_write_json, now, sha256_file


class ImageValidationError(RuntimeError):
    pass


def inspect_png(path: Path) -> dict[str, Any]:
    try:
        with Image.open(path) as source:
            source.load()
            image_format = source.format
            image = source.convert("RGB")
    except Exception as error:
        raise ImageValidationError(f"image cannot be decoded: {error}") from error
    variance = [float(value) for value in ImageStat.Stat(image).var]
    if image_format != "PNG":
        raise ImageValidationError(f"expected PNG, got {image_format}")
    if image.size != (PROFILE.width, PROFILE.height):
        raise ImageValidationError(
            f"expected {PROFILE.width}x{PROFILE.height}, got {image.width}x{image.height}"
        )
    if sum(variance) <= 0:
        raise ImageValidationError("generated image is blank")
    return {
        "width": image.width,
        "height": image.height,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "pixel_variance": [round(value, 3) for value in variance],
    }


class ArtifactStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def request_root(self, record: QueueRecordV1) -> Path:
        job = record.job
        return (
            self.settings.output_root
            / job.project_id
            / job.chapter_id
            / job.scene_id
            / job.panel_id
            / job.request_id
        )

    def attempt_root(self, record: QueueRecordV1) -> Path:
        return self.request_root(record) / f"attempt-{record.attempt:02d}"

    def committed_result_path(self, record: QueueRecordV1) -> Path:
        return self.attempt_root(record) / "result.json"

    def load_committed_result(self, record: QueueRecordV1) -> ImageResultV1 | None:
        path = self.committed_result_path(record)
        if not path.is_file():
            return None
        return ImageResultV1.model_validate_json(path.read_text(encoding="utf-8"))

    def commit_success(
        self,
        record: QueueRecordV1,
        scratch_image: Path,
        generation_metadata: dict[str, Any],
    ) -> ImageResultV1:
        existing = self.load_committed_result(record)
        if existing is not None:
            return existing

        metrics = inspect_png(scratch_image)
        destination_root = self.attempt_root(record)
        destination_root.mkdir(parents=True, exist_ok=True)
        image_path = destination_root / "image.png"
        temporary_image = destination_root / f".image.{os.getpid()}.tmp"
        try:
            with scratch_image.open("rb") as source, temporary_image.open("wb") as destination:
                shutil.copyfileobj(source, destination, length=1024 * 1024)
                destination.flush()
                os.fsync(destination.fileno())
            os.replace(temporary_image, image_path)
        finally:
            temporary_image.unlink(missing_ok=True)

        committed_metrics = inspect_png(image_path)
        if committed_metrics["sha256"] != metrics["sha256"]:
            raise ImageValidationError("persistent image checksum differs from scratch image")

        atomic_write_json(destination_root / "request.json", record.job)
        image_id = _image_id(record)
        metadata = GenerationMetadataV1.model_validate(generation_metadata)
        generated = GeneratedImageV1(
            image_id=image_id,
            prompt_id=record.job.prompt_spec.prompt_id,
            artifact=ArtifactV1(
                uri=str(image_path),
                sha256=committed_metrics["sha256"],
                width=committed_metrics["width"],
                height=committed_metrics["height"],
                bytes=committed_metrics["bytes"],
                pixel_variance=committed_metrics["pixel_variance"],
            ),
            metadata=metadata,
        )
        job = record.job
        result = ImageResultV1(
            request_id=job.request_id,
            project_id=job.project_id,
            chapter_id=job.chapter_id,
            scene_id=job.scene_id,
            panel_id=job.panel_id,
            sequence_no=job.sequence_no,
            status=ResultStatus.SUCCEEDED,
            attempts=record.attempt,
            generated_image=generated,
            completed_at=now(),
        )
        atomic_write_json(self.committed_result_path(record), result)
        return result


def _image_id(record: QueueRecordV1) -> str:
    suffix = f".a{record.attempt}"
    if len(record.job.request_id) + len(suffix) <= 128:
        return record.job.request_id + suffix
    return f"img-{record.job_sha256[:24]}-a{record.attempt}"
