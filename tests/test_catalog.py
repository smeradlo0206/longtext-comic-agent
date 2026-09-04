from pathlib import Path

import pytest
from PIL import Image

from flux2_agent.catalog import (
    build_catalog,
    load_catalog,
    update_reference_metadata,
    write_catalog,
)


def test_catalog_assigns_legacy_id_to_wechat_image(tmp_path: Path) -> None:
    root = tmp_path / "inputs" / "references"
    root.mkdir(parents=True)
    Image.new("RGB", (64, 32), "white").save(root / "微信图片_1.png")

    destination = write_catalog(tmp_path)
    catalog = load_catalog(tmp_path)

    assert destination.is_file()
    assert catalog.schema_version == "2.0"
    assert catalog.references[0].asset_id == "wechat-001"
    assert catalog.references[0].width == 64


def test_catalog_accepts_uploaded_reference(tmp_path: Path) -> None:
    root = tmp_path / "inputs" / "references"
    root.mkdir(parents=True)
    Image.new("RGB", (64, 32), "white").save(root / "character.jpg")

    catalog = build_catalog(tmp_path)

    assert catalog.references[0].asset_id == "asset-001"


def test_catalog_preserves_ids_when_new_file_sorts_first(tmp_path: Path) -> None:
    root = tmp_path / "inputs" / "references"
    root.mkdir(parents=True)
    Image.new("RGB", (64, 32), "white").save(root / "微信图片_1.png")
    write_catalog(tmp_path)
    Image.new("RGB", (32, 64), "black").save(root / "000-new.jpg")

    catalog = build_catalog(tmp_path)

    by_name = {item.filename: item.asset_id for item in catalog.references}
    assert by_name["微信图片_1.png"] == "wechat-001"
    assert by_name["000-new.jpg"] == "asset-001"


def test_catalog_rejects_unexpected_files(tmp_path: Path) -> None:
    root = tmp_path / "inputs" / "references"
    root.mkdir(parents=True)
    Image.new("RGB", (64, 32), "white").save(root / "微信图片_1.png")
    (root / "old-notes.txt").write_text("legacy", encoding="utf-8")

    try:
        build_catalog(tmp_path)
    except ValueError as error:
        assert "unexpected files" in str(error)
    else:
        raise AssertionError("unexpected reference-directory file was accepted")


def test_catalog_rejects_nested_directories(tmp_path: Path) -> None:
    root = tmp_path / "inputs" / "references"
    root.mkdir(parents=True)
    Image.new("RGB", (64, 32), "white").save(root / "character.png")
    (root / "nested").mkdir()

    try:
        build_catalog(tmp_path)
    except ValueError as error:
        assert "unexpected files" in str(error)
    else:
        raise AssertionError("nested reference directory was accepted")


def test_catalog_preserves_approved_canonical_metadata_until_file_changes(
    tmp_path: Path,
) -> None:
    root = tmp_path / "inputs" / "references"
    root.mkdir(parents=True)
    source = root / "character.png"
    Image.new("RGB", (64, 32), "white").save(source)
    write_catalog(tmp_path)

    reviewed = update_reference_metadata(
        tmp_path,
        "asset-001",
        lifecycle="approved",
        entity_id="character.lead",
        intended_role="character_identity",
        variant="base",
        is_canonical=True,
    )
    preserved = build_catalog(tmp_path)

    assert reviewed.references[0].approved_at is not None
    assert preserved.references[0].lifecycle == "approved"
    assert preserved.references[0].is_canonical is True

    Image.new("RGB", (64, 32), "black").save(source)
    changed = build_catalog(tmp_path)
    assert changed.references[0].lifecycle == "candidate"
    assert changed.references[0].entity_id is None
    assert changed.references[0].is_canonical is False


def test_reference_review_rejects_canonical_candidate(tmp_path: Path) -> None:
    root = tmp_path / "inputs" / "references"
    root.mkdir(parents=True)
    Image.new("RGB", (64, 32), "white").save(root / "character.png")
    write_catalog(tmp_path)

    with pytest.raises(ValueError, match="canonical references must be approved"):
        update_reference_metadata(
            tmp_path,
            "asset-001",
            lifecycle="candidate",
            entity_id="character.lead",
            intended_role="character_identity",
            is_canonical=True,
        )
