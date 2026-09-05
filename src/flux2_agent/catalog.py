from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from tempfile import gettempdir
from typing import Literal

from PIL import Image

from .locking import exclusive_lock
from .models import ReferenceCatalog, ReferenceImage, ReferenceRole

IMAGE_MIME_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


@contextmanager
def _catalog_locked(workspace: Path) -> Iterator[None]:
    lock_id = hashlib.sha256(str(workspace.resolve()).encode()).hexdigest()[:16]
    lock_path = Path(gettempdir()) / f"flux2-reference-catalog-{lock_id}.lock"
    lock_path.touch(mode=0o600, exist_ok=True)
    lock_path.chmod(0o600)
    with exclusive_lock(lock_path):
        yield


def _persist_catalog(workspace: Path, catalog: ReferenceCatalog) -> Path:
    destination = workspace.resolve() / "inputs" / "references" / "manifest.json"
    temporary = workspace.resolve() / f".reference-manifest-{uuid.uuid4().hex}.tmp"
    temporary.write_text(
        json.dumps(catalog.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.chmod(0o600)
    os.replace(temporary, destination)
    destination.chmod(0o600)
    return destination


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_catalog(workspace: Path) -> ReferenceCatalog:
    workspace = workspace.resolve()
    reference_root = workspace / "inputs" / "references"
    manifest_path = reference_root / "manifest.json"
    unexpected = sorted(
        path.name
        for path in reference_root.iterdir()
        if path.name != "manifest.json"
        and (
            path.is_symlink()
            or not path.is_file()
            or path.suffix.lower() not in IMAGE_MIME_TYPES
        )
    )
    if unexpected:
        raise ValueError(f"unexpected files in reference directory: {unexpected}")
    candidates_by_name = {
        path.name: path
        for path in reference_root.iterdir()
        if path.is_file()
        and not path.is_symlink()
        and path.suffix.lower() in IMAGE_MIME_TYPES
    }
    if not candidates_by_name:
        raise ValueError(f"no reference images found in {reference_root}")

    existing: ReferenceCatalog | None = None
    if manifest_path.is_file():
        existing = ReferenceCatalog.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
    existing_by_filename = (
        {item.filename: item for item in existing.references}
        if existing
        else {}
    )
    existing_order = (
        [
            item.filename
            for item in existing.references
            if item.filename in candidates_by_name
        ]
        if existing
        else []
    )
    new_names = sorted(set(candidates_by_name) - set(existing_order))
    candidates = [
        candidates_by_name[name] for name in [*existing_order, *new_names]
    ]
    used_ids = {item.asset_id for item in existing_by_filename.values()}

    def allocate_asset_id(path: Path) -> str:
        prefix = "wechat" if path.name.startswith("微信图片") else "asset"
        indexes = [
            int(match.group(1))
            for asset_id in used_ids
            if (match := re.fullmatch(rf"{prefix}-(\d+)", asset_id))
        ]
        index = max(indexes, default=0) + 1
        asset_id = f"{prefix}-{index:03d}"
        used_ids.add(asset_id)
        return asset_id

    references: list[ReferenceImage] = []
    for path in candidates:
        previous = existing_by_filename.get(path.name)
        asset_id = previous.asset_id if previous else allocate_asset_id(path)
        used_ids.add(asset_id)
        digest = sha256_file(path)
        with Image.open(path) as image:
            width, height = image.size
            image.verify()
        references.append(
            ReferenceImage(
                asset_id=asset_id,
                filename=path.name,
                relative_path=path.relative_to(workspace).as_posix(),
                sha256=digest,
                mime_type=IMAGE_MIME_TYPES[path.suffix.lower()],
                width=width,
                height=height,
                bytes=path.stat().st_size,
                lifecycle=(
                    previous.lifecycle
                    if previous is not None and previous.sha256 == digest
                    else "candidate"
                ),
                entity_id=(
                    previous.entity_id
                    if previous is not None and previous.sha256 == digest
                    else None
                ),
                intended_role=(
                    previous.intended_role
                    if previous is not None and previous.sha256 == digest
                    else None
                ),
                variant=(
                    previous.variant
                    if previous is not None and previous.sha256 == digest
                    else "base"
                ),
                is_canonical=(
                    previous.is_canonical
                    if previous is not None and previous.sha256 == digest
                    else False
                ),
                approved_at=(
                    previous.approved_at
                    if previous is not None and previous.sha256 == digest
                    else None
                ),
                notes=(
                    previous.notes
                    if previous is not None and previous.sha256 == digest
                    else None
                ),
            )
        )
    return ReferenceCatalog(references=references)


def write_catalog(workspace: Path) -> Path:
    with _catalog_locked(workspace):
        return _persist_catalog(workspace, build_catalog(workspace))


def update_reference_metadata(
    workspace: Path,
    asset_id: str,
    *,
    lifecycle: Literal["candidate", "approved", "rejected"],
    entity_id: str | None = None,
    intended_role: ReferenceRole | None = None,
    variant: str = "base",
    is_canonical: bool = False,
    notes: str | None = None,
) -> ReferenceCatalog:
    """Review one immutable reference and persist its production-library metadata."""

    workspace = workspace.resolve()
    with _catalog_locked(workspace):
        catalog = load_catalog(workspace)
        matches = [item for item in catalog.references if item.asset_id == asset_id]
        if not matches:
            raise KeyError(f"reference asset not found: {asset_id}")
        approved_at = datetime.now(UTC) if lifecycle == "approved" else None
        updated = ReferenceImage.model_validate(
            matches[0].model_dump(mode="python")
            | {
                "lifecycle": lifecycle,
                "entity_id": entity_id,
                "intended_role": intended_role,
                "variant": variant,
                "is_canonical": is_canonical,
                "approved_at": approved_at,
                "notes": notes,
            }
        )
        references = [
            updated if item.asset_id == asset_id else item
            for item in catalog.references
        ]
        if is_canonical:
            references = [
                item.model_copy(update={"is_canonical": False})
                if item.asset_id != asset_id
                and item.entity_id == entity_id
                and item.intended_role == intended_role
                else item
                for item in references
            ]
        result = ReferenceCatalog(references=references)
        _persist_catalog(workspace, result)
        return result


def load_catalog(workspace: Path, *, verify_files: bool = True) -> ReferenceCatalog:
    workspace = workspace.resolve()
    manifest_path = workspace / "inputs" / "references" / "manifest.json"
    catalog = ReferenceCatalog.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    if verify_files:
        verify_catalog(workspace, catalog)
    return catalog


def verify_catalog(workspace: Path, catalog: ReferenceCatalog) -> None:
    workspace = workspace.resolve()
    reference_root = (workspace / "inputs" / "references").resolve()
    catalog_paths: set[Path] = set()
    for item in catalog.references:
        path = (workspace / item.relative_path).resolve()
        if reference_root not in path.parents:
            raise ValueError(f"reference escapes inputs/references: {item.relative_path}")
        if not path.is_file():
            raise FileNotFoundError(f"reference is missing: {path}")
        if path.stat().st_size != item.bytes or sha256_file(path) != item.sha256:
            raise ValueError(f"reference changed after cataloging: {path.name}")
        catalog_paths.add(path)

    actual_paths = {
        path.resolve()
        for path in reference_root.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_MIME_TYPES
    }
    if actual_paths != catalog_paths:
        raise ValueError("reference directory and manifest differ; run the catalog command")
    unexpected = sorted(
        path.name
        for path in reference_root.iterdir()
        if path.is_file()
        and path.name != "manifest.json"
        and path.suffix.lower() not in IMAGE_MIME_TYPES
    )
    if unexpected:
        raise ValueError(f"unexpected files in reference directory: {unexpected}")
