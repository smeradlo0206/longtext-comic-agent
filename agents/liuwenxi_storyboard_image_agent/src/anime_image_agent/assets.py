from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path
from typing import Literal, Protocol

from PIL import Image, ImageCms, ImageOps
from pydantic import Field, model_validator

from .io_utils import load_json, sha256_file
from .scene_contracts import Identifier, StrictModel


class AssetRecord(StrictModel):
    asset_id: Identifier
    role: Literal["identity_reference", "scene_reference", "style_reference"]
    relative_path: str = Field(min_length=1, max_length=1024)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    description: str = Field(min_length=1, max_length=2048)
    character_id: Identifier | None = None
    scene_id: Identifier | None = None
    view: str | None = Field(default=None, max_length=256)
    tags: list[str] = Field(default_factory=list, max_length=64)
    source: str | None = Field(default=None, max_length=2048)
    creator: str | None = Field(default=None, max_length=256)
    license: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def owner_matches_role(self) -> "AssetRecord":
        if self.role == "identity_reference" and not self.character_id:
            raise ValueError("identity_reference requires character_id")
        if self.role == "scene_reference" and not self.scene_id:
            raise ValueError("scene_reference requires scene_id")
        return self


class CharacterProfile(StrictModel):
    character_id: Identifier
    name: str = Field(min_length=1, max_length=256)
    description: str = Field(min_length=1, max_length=2048)
    canonical_asset_id: Identifier


class SceneProfile(StrictModel):
    scene_id: Identifier
    name: str = Field(min_length=1, max_length=256)
    description: str = Field(min_length=1, max_length=2048)
    canonical_asset_id: Identifier


class StyleProfile(StrictModel):
    style_id: Identifier
    description: str = Field(min_length=1, max_length=2048)
    canonical_asset_id: Identifier


class AssetProfile(StrictModel):
    schema_name: Literal["PresetAssetManifestV1"] = "PresetAssetManifestV1"
    schema_version: Literal["1.0"] = "1.0"
    profile_id: Identifier
    default_scene_id: Identifier
    default_style_id: Identifier
    characters: list[CharacterProfile] = Field(min_length=1, max_length=128)
    scenes: list[SceneProfile] = Field(min_length=1, max_length=128)
    styles: list[StyleProfile] = Field(min_length=1, max_length=32)
    assets: list[AssetRecord] = Field(min_length=1, max_length=1024)


class ResolvedAsset(StrictModel):
    record: AssetRecord
    source_path: str
    normalized_path: str
    normalized_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class AssetRepository(Protocol):
    def get_profile(self, profile_id: str) -> AssetProfile: ...
    def get_character(self, profile_id: str, character_id: str) -> CharacterProfile: ...
    def get_scene(self, profile_id: str, scene_id: str) -> SceneProfile: ...
    def get_style(self, profile_id: str) -> StyleProfile: ...
    def resolve_asset(self, profile_id: str, asset_id: str) -> ResolvedAsset: ...


class PresetAssetRepository:
    def __init__(self, root: Path, cache_root: Path) -> None:
        self.root = root.resolve()
        self.cache_root = cache_root.resolve()
        self._profiles: dict[str, AssetProfile] = {}

    def get_profile(self, profile_id: str) -> AssetProfile:
        if profile_id in self._profiles:
            return self._profiles[profile_id]
        manifest = self._profile_root(profile_id) / "manifest.json"
        if not manifest.is_file():
            raise FileNotFoundError(f"asset manifest not found: {manifest}")
        profile = AssetProfile.model_validate(load_json(manifest))
        if profile.profile_id != profile_id:
            raise ValueError(f"manifest profile_id {profile.profile_id!r} does not match {profile_id!r}")
        self._validate_profile(profile)
        self._profiles[profile_id] = profile
        return profile

    def get_character(self, profile_id: str, character_id: str) -> CharacterProfile:
        profile = self.get_profile(profile_id)
        return _find(profile.characters, "character_id", character_id, "character")

    def get_scene(self, profile_id: str, scene_id: str) -> SceneProfile:
        profile = self.get_profile(profile_id)
        return _find(profile.scenes, "scene_id", scene_id, "scene")

    def get_style(self, profile_id: str) -> StyleProfile:
        profile = self.get_profile(profile_id)
        return _find(profile.styles, "style_id", profile.default_style_id, "style")

    def resolve_asset(self, profile_id: str, asset_id: str) -> ResolvedAsset:
        profile = self.get_profile(profile_id)
        record: AssetRecord = _find(profile.assets, "asset_id", asset_id, "asset")
        source = self._safe_asset_path(profile_id, record.relative_path)
        if not source.is_file():
            raise FileNotFoundError(f"asset file not found: {source}")
        source_sha = sha256_file(source)
        if source_sha != record.sha256:
            raise ValueError(f"asset checksum mismatch for {asset_id}: expected {record.sha256}, got {source_sha}")
        normalized = self._normalize(source, source_sha)
        return ResolvedAsset(
            record=record,
            source_path=str(source),
            normalized_path=str(normalized),
            normalized_sha256=sha256_file(normalized),
        )

    def validate_profile(self, profile_id: str) -> AssetProfile:
        profile = self.get_profile(profile_id)
        for asset in profile.assets:
            self.resolve_asset(profile_id, asset.asset_id)
        return profile

    def _profile_root(self, profile_id: str) -> Path:
        candidate = (self.root / profile_id).resolve()
        _require_within(candidate, self.root)
        return candidate

    def _safe_asset_path(self, profile_id: str, relative_path: str) -> Path:
        profile_root = self._profile_root(profile_id)
        candidate = (profile_root / relative_path).resolve()
        _require_within(candidate, profile_root)
        return candidate

    def _validate_profile(self, profile: AssetProfile) -> None:
        asset_ids = [asset.asset_id for asset in profile.assets]
        if len(asset_ids) != len(set(asset_ids)):
            raise ValueError("asset_ids must be unique")
        for collection, field in (
            (profile.characters, "character_id"),
            (profile.scenes, "scene_id"),
            (profile.styles, "style_id"),
        ):
            values = [getattr(item, field) for item in collection]
            if len(values) != len(set(values)):
                raise ValueError(f"{field} values must be unique")
        asset_by_id = {asset.asset_id: asset for asset in profile.assets}
        for character in profile.characters:
            asset = asset_by_id.get(character.canonical_asset_id)
            if asset is None or asset.role != "identity_reference" or asset.character_id != character.character_id:
                raise ValueError(f"invalid canonical asset for character {character.character_id}")
        for scene in profile.scenes:
            asset = asset_by_id.get(scene.canonical_asset_id)
            if asset is None or asset.role != "scene_reference" or asset.scene_id != scene.scene_id:
                raise ValueError(f"invalid canonical asset for scene {scene.scene_id}")
        for style in profile.styles:
            asset = asset_by_id.get(style.canonical_asset_id)
            if asset is None or asset.role != "style_reference":
                raise ValueError(f"invalid canonical asset for style {style.style_id}")
        if profile.default_scene_id not in {item.scene_id for item in profile.scenes}:
            raise ValueError("default_scene_id does not exist")
        if profile.default_style_id not in {item.style_id for item in profile.styles}:
            raise ValueError("default_style_id does not exist")

    def _normalize(self, source: Path, source_sha: str) -> Path:
        destination = self.cache_root / source_sha[:2] / f"{source_sha}.png"
        if destination.is_file():
            return destination
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
        with Image.open(source) as opened:
            image = ImageOps.exif_transpose(opened)
            alpha = image.getchannel("A") if "A" in image.getbands() else None
            icc = image.info.get("icc_profile")
            if icc:
                try:
                    source_profile = ImageCms.ImageCmsProfile(io.BytesIO(icc))
                    target_profile = ImageCms.createProfile("sRGB")
                    image = ImageCms.profileToProfile(
                        image.convert("RGB"), source_profile, target_profile, outputMode="RGB"
                    )
                except (OSError, ValueError):
                    image = image.convert("RGB")
            else:
                image = image.convert("RGB")
            if alpha is not None:
                background = Image.new("RGB", image.size, (238, 238, 238))
                background.paste(image, mask=alpha)
                image = background
            if max(image.size) > 1024:
                image.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
            image.save(temporary, format="PNG", optimize=True)
        temporary.replace(destination)
        return destination


def select_panel_assets(
    repository: AssetRepository,
    profile_id: str,
    character_ids: list[str],
    scene_id: str | None = None,
) -> list[ResolvedAsset]:
    profile = repository.get_profile(profile_id)
    selected: list[ResolvedAsset] = []
    for character_id in character_ids[:2]:
        character = repository.get_character(profile_id, character_id)
        selected.append(repository.resolve_asset(profile_id, character.canonical_asset_id))
    if len(selected) < 3:
        scene = repository.get_scene(profile_id, scene_id or profile.default_scene_id)
        selected.append(repository.resolve_asset(profile_id, scene.canonical_asset_id))
    if len(selected) < 3:
        style = repository.get_style(profile_id)
        selected.append(repository.resolve_asset(profile_id, style.canonical_asset_id))
    return selected[:3]


def _find(items: list, field: str, expected: str, kind: str):
    for item in items:
        if getattr(item, field) == expected:
            return item
    raise KeyError(f"unknown {kind}: {expected}")


def _require_within(candidate: Path, parent: Path) -> None:
    if candidate != parent and parent not in candidate.parents:
        raise ValueError(f"path escapes asset profile: {candidate}")
