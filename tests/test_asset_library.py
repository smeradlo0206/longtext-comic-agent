"""Regression tests for the bounded, local-only asset-intake lane."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from comic_agent.main import create_app
from comic_agent.schemas import AssetManifestV1, AssetType, ReviewStatus, RightsStatus, UseMode
from comic_agent.services.asset_library import (
    DEFAULT_MAX_FILE_BYTES,
    MAX_LIBRARY_BYTES,
    AssetIntakeError,
    AssetLibraryPaths,
    AssetLibraryService,
    ControlledQuery,
    WikimediaCommonsSource,
    classify_license,
)


class FakeClient:
    """HTTP seam which returns pre-built responses and makes no network request."""

    def __init__(self, responses: dict[str, httpx.Response]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def get(self, url: str, **kwargs: object) -> httpx.Response:
        self.calls.append(url)
        response = self.responses.get(url)
        if response is None:
            raise AssertionError(f"unexpected HTTP URL {url}")
        return response


def response(
    url: str, *, content: bytes = b"asset", content_type: str = "image/jpeg", status: int = 200
) -> httpx.Response:
    return httpx.Response(
        status,
        content=content,
        headers={"content-type": content_type},
        request=httpx.Request("GET", url),
    )


def manifest(**overrides: object) -> AssetManifestV1:
    data: dict[str, object] = {
        "asset_id": "asset-test",
        "source_id": "File:Pose.jpg",
        "source_site": "Wikimedia Commons",
        "source_api_or_package_url": "https://commons.wikimedia.org/w/api.php",
        "original_asset_url": "https://upload.wikimedia.org/example/pose.jpg",
        "original_page_url": "https://commons.wikimedia.org/wiki/File:Pose.jpg",
        "creator": "A creator",
        "title": "Pose",
        "license_code": "CC0 1.0",
        "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
        "attribution_text": "A creator, CC0",
        "asset_type": AssetType.POSE_REFERENCE,
        "use_mode": UseMode.PRODUCTION_CANDIDATE,
        "rights_status": RightsStatus.NEEDS_HUMAN_REVIEW,
        "review_status": ReviewStatus.PENDING,
        "tags": [
            "standing",
            "modern",
            "single_person",
            "source:wikimedia_commons",
            "license:cc0_1_0",
        ],
        "search_query": "human pose standing",
        "collected_at": datetime(2026, 8, 17, tzinfo=UTC),
    }
    data.update(overrides)
    return AssetManifestV1.model_validate(data)


def service(tmp_path: Path, client: FakeClient | None = None) -> AssetLibraryService:
    return AssetLibraryService(AssetLibraryPaths(tmp_path / "asset_library"), client=client)


@pytest.mark.parametrize(
    ("license_code", "expected"),
    [
        ("CC0 1.0", (UseMode.PRODUCTION_CANDIDATE, RightsStatus.VERIFIED_CC0)),
        ("PDM", (UseMode.PRODUCTION_CANDIDATE, RightsStatus.VERIFIED_PUBLIC_DOMAIN)),
        ("CC BY 4.0", (UseMode.PRODUCTION_CANDIDATE, RightsStatus.ATTRIBUTION_REQUIRED)),
        ("CC BY-SA 4.0", (UseMode.REFERENCE_ONLY, RightsStatus.NEEDS_HUMAN_REVIEW)),
        ("GPL-3.0", (UseMode.REFERENCE_ONLY, RightsStatus.NEEDS_HUMAN_REVIEW)),
        ("OGA-BY 3.0", (UseMode.REFERENCE_ONLY, RightsStatus.NEEDS_HUMAN_REVIEW)),
        ("CC BY-NC 4.0", (UseMode.REFERENCE_ONLY, RightsStatus.REJECTED)),
        ("CC BY-ND 4.0", (UseMode.REFERENCE_ONLY, RightsStatus.REJECTED)),
        ("custom", (UseMode.REFERENCE_ONLY, RightsStatus.REJECTED)),
        (None, None),
    ],
)
def test_license_classification_is_narrow_and_auditable(
    license_code: str | None, expected: object
) -> None:
    assert classify_license(license_code) == expected


def test_manifest_is_versioned_and_rejects_unsafe_paths_and_secret_fields() -> None:
    assert manifest().schema_version == "1.0"
    with pytest.raises(ValidationError, match="safe relative"):
        manifest(local_relative_path="../secret.jpg", checksum="a" * 64, bytes_size=1)
    source_size_only = manifest(bytes_size=123)
    assert source_size_only.bytes_size == 123 and source_size_only.local_relative_path is None
    with pytest.raises(ValidationError):
        AssetManifestV1.model_validate({**manifest().model_dump(), "api_key": "secret"})


def test_manifest_requires_controlled_tag_dimensions() -> None:
    with pytest.raises(ValidationError, match="era"):
        manifest(tags=["standing", "single_person", "source:x", "license:cc0"])


def test_discovery_uses_only_metadata_and_rejects_missing_license_details() -> None:
    api_url = "https://commons.wikimedia.org/w/api.php"
    page = {
        "title": "File:Pose.jpg",
        "imageinfo": [
            {
                "mime": "image/jpeg",
                "url": "https://upload.wikimedia.org/example/pose.jpg",
                "size": 123,
                "extmetadata": {
                    "LicenseShortName": {"value": "CC0 1.0"},
                    "LicenseUrl": {"value": "https://creativecommons.org/publicdomain/zero/1.0/"},
                    "Artist": {"value": "<b>A creator</b>"},
                },
            }
        ],
    }
    client = FakeClient(
        {
            api_url: httpx.Response(
                200, json={"query": {"pages": {"1": page}}}, request=httpx.Request("GET", api_url)
            )
        }
    )
    query = ControlledQuery(
        "pose", ("standing", "modern", "single_person"), AssetType.POSE_REFERENCE
    )
    records = WikimediaCommonsSource(client).discover(query, 1)
    assert records[0].rights_status == RightsStatus.NEEDS_HUMAN_REVIEW
    assert records[0].creator == "A creator"
    invalid = {
        **page,
        "imageinfo": [
            {**page["imageinfo"][0], "extmetadata": {"LicenseShortName": {"value": "CC0"}}}
        ],
    }
    client = FakeClient(
        {
            api_url: httpx.Response(
                200,
                json={"query": {"pages": {"1": invalid}}},
                request=httpx.Request("GET", api_url),
            )
        }
    )
    assert WikimediaCommonsSource(client).discover(query, 1) == []


def test_discovery_bounds_long_official_metadata_before_manifest_storage() -> None:
    api_url = "https://commons.wikimedia.org/w/api.php"
    page = {
        "title": "File:Pose.jpg",
        "imageinfo": [
            {
                "mime": "image/jpeg",
                "url": "https://upload.wikimedia.org/example/pose.jpg",
                "size": 123,
                "extmetadata": {
                    "LicenseShortName": {"value": "CC0 1.0"},
                    "LicenseUrl": {"value": "https://creativecommons.org/publicdomain/zero/1.0/"},
                    "Artist": {"value": "A creator"},
                    "ImageDescription": {"value": "x" * 1000},
                },
            }
        ],
    }
    client = FakeClient(
        {
            api_url: httpx.Response(
                200,
                json={"query": {"pages": {"1": page}}},
                request=httpx.Request("GET", api_url),
            )
        }
    )
    query = ControlledQuery(
        "pose", ("standing", "modern", "single_person"), AssetType.POSE_REFERENCE
    )
    records = WikimediaCommonsSource(client).discover(query, 1)
    assert records[0].title is not None and len(records[0].title) == 500


def test_discovery_sanitizes_official_http_failure_without_persisting_response_details() -> None:
    api_url = "https://commons.wikimedia.org/w/api.php"
    client = FakeClient(
        {
            api_url: httpx.Response(
                429,
                content=b"rate-limit source response must not surface",
                request=httpx.Request("GET", api_url),
            )
        }
    )
    query = ControlledQuery(
        "pose", ("standing", "modern", "single_person"), AssetType.POSE_REFERENCE
    )
    with pytest.raises(AssetIntakeError, match="metadata request failed") as error:
        WikimediaCommonsSource(client).discover(query, 1)
    assert "rate-limit" not in str(error.value)


def test_download_blocks_unknown_host_redirect_mime_and_per_file_limit(tmp_path: Path) -> None:
    unknown = service(
        tmp_path, FakeClient({"https://evil.example/x": response("https://evil.example/x")})
    )
    with pytest.raises(AssetIntakeError, match="allowed official"):
        unknown._fetch_allowed_binary("https://evil.example/x", DEFAULT_MAX_FILE_BYTES)
    redirect_url = "https://upload.wikimedia.org/example/redirect"
    redirect = service(tmp_path, FakeClient({redirect_url: response(redirect_url, status=302)}))
    with pytest.raises(AssetIntakeError, match="redirected"):
        redirect._fetch_allowed_binary(redirect_url, DEFAULT_MAX_FILE_BYTES)
    bad_mime_url = "https://upload.wikimedia.org/example/bad"
    bad_mime = service(
        tmp_path, FakeClient({bad_mime_url: response(bad_mime_url, content_type="text/html")})
    )
    with pytest.raises(AssetIntakeError, match="content type"):
        bad_mime._fetch_allowed_binary(bad_mime_url, DEFAULT_MAX_FILE_BYTES)
    large_url = "https://upload.wikimedia.org/example/large"
    large = service(tmp_path, FakeClient({large_url: response(large_url, content=b"x" * 6)}))
    with pytest.raises(AssetIntakeError, match="per-file"):
        large._fetch_allowed_binary(large_url, 5)


def test_checksum_dedup_and_ten_gib_quota_are_enforced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = "https://upload.wikimedia.org/example/pose.jpg"
    client = FakeClient({url: response(url, content=b"same")})
    library = service(tmp_path, client)
    existing = manifest(
        asset_id="asset-old",
        local_relative_path="incoming/production_candidate/asset-old.jpg",
        checksum=hashlib.sha256(b"same").hexdigest(),
        bytes_size=4,
    )
    library.paths.ensure_layout()
    library.paths.resolve_relative(existing.local_relative_path or "").write_bytes(b"same")
    library.save_manifest(existing)
    updated = library._download_one(manifest(asset_id="asset-new"), max_file_bytes=10)
    assert updated.local_relative_path == existing.local_relative_path
    monkeypatch.setattr(library, "_library_bytes", lambda: MAX_LIBRARY_BYTES)
    quota_url = "https://upload.wikimedia.org/example/quota.jpg"
    client.responses[quota_url] = response(quota_url, content=b"other")
    with pytest.raises(AssetIntakeError, match="quota"):
        library._download_one(
            manifest(asset_id="asset-quota", original_asset_url=quota_url), max_file_bytes=10
        )


def test_download_retains_manifest_when_optional_thumbnail_metadata_fails(tmp_path: Path) -> None:
    url = "https://upload.wikimedia.org/example/pose.jpg"
    api_url = "https://commons.wikimedia.org/w/api.php"
    thumbnail_url = "https://upload.wikimedia.org/example/thumbnail.jpg"
    client = FakeClient(
        {
            url: response(url, content=b"asset"),
            api_url: httpx.Response(
                200,
                json={"query": {"pages": {"1": {"imageinfo": [{"thumburl": thumbnail_url}]}}}},
                request=httpx.Request("GET", api_url),
            ),
            thumbnail_url: httpx.Response(429, request=httpx.Request("GET", thumbnail_url)),
        }
    )
    library = service(tmp_path, client)
    updated = library._download_one(manifest(), max_file_bytes=10)
    assert updated.local_relative_path is not None
    assert updated.thumbnail_relative_path is None
    library.save_manifest(updated)
    assert library.load_manifests()[0].checksum == hashlib.sha256(b"asset").hexdigest()


def test_manifest_recovery_review_transition_moves_but_never_deletes(tmp_path: Path) -> None:
    library = service(tmp_path)
    downloaded = manifest(
        local_relative_path="incoming/production_candidate/asset-test.jpg",
        checksum="b" * 64,
        bytes_size=3,
    )
    library.paths.ensure_layout()
    source = library.paths.resolve_relative(downloaded.local_relative_path or "")
    source.write_bytes(b"jpg")
    library.save_manifest(downloaded)
    assert library.load_manifests() == [downloaded]
    approved = library.review_asset("asset-test", ReviewStatus.APPROVED, "keep")
    assert approved.local_relative_path == "approved/asset-test.jpg"
    assert library.paths.resolve_relative(approved.local_relative_path or "").read_bytes() == b"jpg"
    rejected = library.review_asset("asset-test", ReviewStatus.REJECTED, "not suitable")
    assert rejected.local_relative_path == "rejected/asset-test.jpg"
    assert library.paths.resolve_relative(rejected.local_relative_path or "").is_file()
    report = library.report()
    assert report["total_files"] == 1
    assert report["total_bytes"] == 3
    assert report["downloaded_candidate_count"] == 1


def test_review_console_is_loopback_only_and_has_no_generation_or_story_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    library = service(tmp_path)
    library.save_manifest(manifest())
    monkeypatch.setattr("comic_agent.api.assets._service", lambda: library)
    app = create_app(database_url=f"sqlite+pysqlite:///{tmp_path / 'api.db'}")
    with TestClient(app) as client:
        page = client.get("/console/assets/")
        assert page.status_code == 200
        assert "保留" in page.text and "仅参考" in page.text and "拒绝" in page.text
        assert "StoryBible" not in page.text
        assert "Prompt" not in page.text
        assert "provider" not in page.text.lower()
        assert (
            client.post(
                "/console/assets/review/asset-test",
                data={"decision": "REFERENCE_ONLY", "note": "manual"},
            ).status_code
            == 200
        )
