"""Local FLUX.2 Klein image Provider backed by the existing GPU workflow."""

from __future__ import annotations

import gc
from pathlib import Path
from typing import Any, overload

from PIL import Image

from comic_agent.providers.image import ImageResult
from comic_agent.schemas.image_workflow import GenerationSettings, PlannedShot


def load_reference(path: Path) -> Image.Image:
    """Load a reference as RGB and flatten transparency deterministically."""

    with Image.open(path) as source:
        if source.mode == "RGBA":
            background = Image.new("RGBA", source.size, (238, 238, 238, 255))
            return Image.alpha_composite(background, source).convert("RGB")
        return source.convert("RGB")


class LocalFlux2ImageProvider:
    """Provider implementation with a legacy in-memory method for the queue runner."""

    provider_name = "local-flux2-klein"

    def __init__(
        self,
        settings: GenerationSettings,
        *,
        model_path: Path | None = None,
        offline: bool = False,
    ) -> None:
        self.settings = settings
        self.model_source = str(model_path.resolve()) if model_path else settings.model_id
        self.offline = offline
        self._pipeline: Any | None = None

    def load(self) -> None:
        import torch
        from diffusers import Flux2KleinPipeline

        if not torch.cuda.is_available():
            raise RuntimeError("FLUX.2 generation requires an available CUDA GPU")
        self._pipeline = Flux2KleinPipeline.from_pretrained(  # type: ignore[no-untyped-call]
            self.model_source,
            torch_dtype=torch.bfloat16,
            local_files_only=self.offline,
        ).to(self.settings.device)

    @overload
    def generate(
        self,
        request: PlannedShot,
        seed: int,
        *,
        continuity_path: Path | None = None,
    ) -> Image.Image: ...

    @overload
    def generate(
        self,
        request: dict[str, object],
        seed: None = None,
        *,
        continuity_path: Path | None = None,
    ) -> ImageResult: ...

    def generate(
        self,
        request: PlannedShot | dict[str, object],
        seed: int | None = None,
        *,
        continuity_path: Path | None = None,
    ) -> Image.Image | ImageResult:
        """Generate through the provider contract or the legacy in-memory queue call."""

        if isinstance(request, dict):
            return self._generate_provider_request(request)
        if seed is None:
            raise ValueError("an explicit seed is required for an in-memory FLUX.2 call")
        return self._generate_image(request, seed, continuity_path=continuity_path)

    def edit(self, request: dict[str, object]) -> ImageResult:
        """Run the same reference-conditioned path for a provider edit request."""

        return self._generate_provider_request(request)

    def _generate_provider_request(self, request: dict[str, object]) -> ImageResult:
        shot = request.get("shot")
        seed = request.get("seed")
        output_path = request.get("output_path")
        continuity_path = request.get("continuity_path")
        if not isinstance(shot, PlannedShot):
            raise ValueError("local FLUX.2 request requires a validated PlannedShot")
        if not isinstance(seed, int):
            raise ValueError("local FLUX.2 request requires an integer seed")
        if not isinstance(output_path, Path):
            raise ValueError("local FLUX.2 request requires a Path output_path")
        if continuity_path is not None and not isinstance(continuity_path, Path):
            raise ValueError("continuity_path must be a Path when provided")
        image = self._generate_image(shot, seed, continuity_path=continuity_path)
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            image.save(output_path, format="PNG", optimize=True)
            width, height = image.size
        finally:
            image.close()
        output_path.chmod(0o600)
        return ImageResult(
            storage_uri=output_path.resolve().as_uri(),
            width=width,
            height=height,
            metadata={
                "provider": self.provider_name,
                "model_source": self.model_source,
                "seed": seed,
                "shot_id": shot.shot_id,
            },
        )

    def _generate_image(
        self,
        shot: PlannedShot,
        seed: int,
        *,
        continuity_path: Path | None = None,
    ) -> Image.Image:
        import torch

        if self._pipeline is None:
            raise RuntimeError("provider must be loaded before generation")
        references = [load_reference(reference.path) for reference in shot.references]
        if continuity_path is not None:
            references.append(load_reference(continuity_path))
        try:
            generator = torch.Generator(device=self.settings.device).manual_seed(seed)
            generated = self._pipeline(
                image=references or None,
                prompt=shot.prompt,
                width=self.settings.width,
                height=self.settings.height,
                num_inference_steps=self.settings.steps,
                guidance_scale=self.settings.guidance_scale,
                generator=generator,
            ).images[0]
            if not isinstance(generated, Image.Image):
                raise TypeError("FLUX.2 Provider returned a non-image result")
            return generated
        finally:
            for image in references:
                image.close()

    def close(self) -> None:
        if self._pipeline is None:
            return
        import torch

        self._pipeline = None
        gc.collect()
        torch.cuda.empty_cache()

    def __enter__(self) -> LocalFlux2ImageProvider:
        self.load()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


Flux2Backend = LocalFlux2ImageProvider
