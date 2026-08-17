"""Bounded local intake for human-reviewed public reference assets.

This module is deliberately separate from agents, StoryBible, and image providers.
It only handles manifests and local files under the asset-library root.
"""

from __future__ import annotations

import hashlib
import mimetypes
import re
import shutil
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from html import unescape
from pathlib import Path, PurePosixPath
from typing import Any, Protocol, cast
from urllib.parse import urlparse

import httpx

from comic_agent.schemas.assets import (
    AssetManifestV1,
    AssetType,
    ReviewStatus,
    RightsStatus,
    UseMode,
)

DEFAULT_ASSET_LIBRARY_ROOT = Path("D:/107/asset_library")
MAX_LIBRARY_BYTES = 10 * 1024**3
DEFAULT_MAX_FILE_BYTES = 25 * 1024**2
ALLOWED_IMAGE_MIME_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
ALLOWED_DOWNLOAD_DOMAINS = frozenset({"upload.wikimedia.org"})
WIKIMEDIA_API_URL = "https://commons.wikimedia.org/w/api.php"


@dataclass(frozen=True)
class ControlledQuery:
    """A static search phrase and the minimum tags applied to discovered results."""

    query: str
    tags: tuple[str, ...]
    asset_type: AssetType


CONTROLLED_QUERIES: tuple[ControlledQuery, ...] = (
    ControlledQuery(
        "human pose standing", ("standing", "modern", "single_person"), AssetType.POSE_REFERENCE
    ),
    ControlledQuery(
        "human pose walking", ("walking", "modern", "side_view"), AssetType.POSE_REFERENCE
    ),
    ControlledQuery(
        "human pose sitting", ("sitting", "modern", "single_person"), AssetType.POSE_REFERENCE
    ),
    ControlledQuery(
        "human facial expression happy",
        ("happy", "neutral", "close_up"),
        AssetType.EXPRESSION_REFERENCE,
    ),
    ControlledQuery(
        "human facial expression angry",
        ("angry", "neutral", "close_up"),
        AssetType.EXPRESSION_REFERENCE,
    ),
    ControlledQuery(
        "human facial expression sad",
        ("sad", "neutral", "close_up"),
        AssetType.EXPRESSION_REFERENCE,
    ),
    ControlledQuery(
        "historical person bowing", ("bowing", "ancient", "single_person"), AssetType.POSE_REFERENCE
    ),
    ControlledQuery(
        "historical person holding sword",
        ("holding_sword", "ancient", "single_person"),
        AssetType.POSE_REFERENCE,
    ),
    ControlledQuery(
        "historical person kneeling",
        ("kneeling", "ancient", "single_person"),
        AssetType.POSE_REFERENCE,
    ),
    ControlledQuery(
        "two people confrontation",
        ("two_person_confrontation", "neutral", "two_person"),
        AssetType.POSE_REFERENCE,
    ),
)


class AssetIntakeError(ValueError):
    """Safe, per-item intake error that never includes remote response bodies."""


class HttpClient(Protocol):
    """Small HTTP seam so unit tests never perform network activity."""

    def get(self, url: str, **kwargs: Any) -> httpx.Response: ...


def _now() -> datetime:
    return datetime.now(UTC)


def _clean_metadata(value: object) -> str | None:
    """Convert Commons metadata into bounded plain text, never preserving raw HTML."""

    if not isinstance(value, str):
        return None
    text = re.sub(r"<[^>]*>", "", unescape(value)).strip()
    return text or None


def _metadata_value(
    metadata: Mapping[str, object], key: str, *, max_chars: int = 1000
) -> str | None:
    """Read bounded plain metadata without retaining an unbounded API field."""

    item = metadata.get(key)
    if isinstance(item, Mapping):
        value = _clean_metadata(item.get("value"))
        return value[:max_chars] if value is not None else None
    return None


def classify_license(license_code: str | None) -> tuple[UseMode, RightsStatus] | None:
    """Map a confirmed license to the project's intentionally narrow intake policy."""

    if not license_code:
        return None
    compact = re.sub(r"\s+", " ", license_code.upper()).strip()
    if "CC0" in compact:
        return (UseMode.PRODUCTION_CANDIDATE, RightsStatus.VERIFIED_CC0)
    if compact in {"PDM", "PUBLIC DOMAIN", "PUBLICDOMAIN", "PD"} or compact.startswith("PD-"):
        return (UseMode.PRODUCTION_CANDIDATE, RightsStatus.VERIFIED_PUBLIC_DOMAIN)
    if (
        compact.startswith("CC BY")
        and "SA" not in compact
        and "NC" not in compact
        and "ND" not in compact
    ):
        return (UseMode.PRODUCTION_CANDIDATE, RightsStatus.ATTRIBUTION_REQUIRED)
    if any(marker in compact for marker in ("CC BY-SA", "GPL", "OGA-BY")):
        return (UseMode.REFERENCE_ONLY, RightsStatus.NEEDS_HUMAN_REVIEW)
    return (UseMode.REFERENCE_ONLY, RightsStatus.REJECTED)


def safe_relative_path(relative_path: str) -> PurePosixPath:
    """Validate a manifest path before resolving it below the library root."""

    path = PurePosixPath(relative_path.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or path == PurePosixPath("."):
        raise AssetIntakeError("unsafe relative asset path")
    return path


@dataclass(frozen=True)
class AssetLibraryPaths:
    """Fixed directory layout for local-only raw assets and mutable manifests."""

    root: Path = DEFAULT_ASSET_LIBRARY_ROOT

    @property
    def manifests(self) -> Path:
        return self.root / "manifests"

    @property
    def thumbnails(self) -> Path:
        return self.root / "thumbnails"

    @property
    def production_candidates(self) -> Path:
        return self.root / "incoming" / "production_candidate"

    @property
    def attribution_review(self) -> Path:
        return self.root / "incoming" / "attribution_review"

    @property
    def reference_only(self) -> Path:
        return self.root / "incoming" / "reference_only"

    @property
    def approved(self) -> Path:
        return self.root / "approved"

    @property
    def rejected(self) -> Path:
        return self.root / "rejected"

    @property
    def review_console(self) -> Path:
        return self.root / "review_console"

    def ensure_layout(self) -> None:
        for path in (
            self.manifests,
            self.thumbnails,
            self.production_candidates,
            self.attribution_review,
            self.reference_only,
            self.approved,
            self.rejected,
            self.review_console,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def resolve_relative(self, relative_path: str) -> Path:
        candidate = (self.root / safe_relative_path(relative_path)).resolve()
        try:
            candidate.relative_to(self.root.resolve())
        except ValueError as error:
            raise AssetIntakeError("asset path escapes library root") from error
        return candidate


class WikimediaCommonsSource:
    """Official MediaWiki Action API adapter; it never scrapes Commons HTML."""

    source_site = "Wikimedia Commons"
    source_api_or_package_url = WIKIMEDIA_API_URL

    def __init__(self, client: HttpClient) -> None:
        self._client = client

    def discover(self, controlled_query: ControlledQuery, limit: int) -> list[AssetManifestV1]:
        """Discover licensed image candidates using ImageInfo/extmetadata only."""

        try:
            response = self._client.get(
                WIKIMEDIA_API_URL,
                params={
                    "action": "query",
                    "format": "json",
                    "generator": "search",
                    "gsrsearch": controlled_query.query,
                    "gsrnamespace": "6",
                    "gsrlimit": str(min(limit, 50)),
                    "prop": "imageinfo",
                    "iiprop": "url|size|mime|extmetadata",
                    "iiextmetadatafilter": (
                        "LicenseShortName|LicenseUrl|Artist|Credit|ImageDescription"
                    ),
                    "iiextmetadatalanguage": "en",
                    "iiurlwidth": "360",
                },
                follow_redirects=False,
                timeout=20.0,
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise AssetIntakeError("Wikimedia Commons metadata request failed") from error
        payload = response.json()
        pages = payload.get("query", {}).get("pages", {})
        if not isinstance(pages, Mapping):
            return []
        candidates: list[AssetManifestV1] = []
        for page in sorted(pages.values(), key=lambda item: str(item.get("title", ""))):
            manifest = self._manifest_from_page(page, controlled_query)
            if manifest is not None:
                candidates.append(manifest)
        return candidates[:limit]

    def thumbnail_url(self, source_id: str) -> str | None:
        """Read a thumbnail URL from the same documented API, not an HTML page."""

        try:
            response = self._client.get(
                WIKIMEDIA_API_URL,
                params={
                    "action": "query",
                    "format": "json",
                    "titles": source_id,
                    "prop": "imageinfo",
                    "iiprop": "url|mime",
                    "iiurlwidth": "360",
                },
                follow_redirects=False,
                timeout=20.0,
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise AssetIntakeError("Wikimedia Commons thumbnail metadata request failed") from error
        pages = response.json().get("query", {}).get("pages", {})
        if not isinstance(pages, Mapping):
            return None
        for page in pages.values():
            imageinfo = page.get("imageinfo")
            if isinstance(imageinfo, list) and imageinfo and isinstance(imageinfo[0], Mapping):
                thumbnail = imageinfo[0].get("thumburl")
                return thumbnail if isinstance(thumbnail, str) else None
        return None

    def _manifest_from_page(
        self, page: object, controlled_query: ControlledQuery
    ) -> AssetManifestV1 | None:
        if not isinstance(page, Mapping):
            return None
        title = page.get("title")
        imageinfo = page.get("imageinfo")
        if not isinstance(title, str) or not isinstance(imageinfo, list) or not imageinfo:
            return None
        info = imageinfo[0]
        if not isinstance(info, Mapping):
            return None
        mime = info.get("mime")
        url = info.get("url")
        if mime not in ALLOWED_IMAGE_MIME_TYPES or not isinstance(url, str):
            return None
        source_bytes_size = info.get("size")
        if not isinstance(source_bytes_size, int) or source_bytes_size < 0:
            return None
        extmetadata = info.get("extmetadata")
        metadata = extmetadata if isinstance(extmetadata, Mapping) else {}
        license_code = _metadata_value(metadata, "LicenseShortName")
        license_url = _metadata_value(metadata, "LicenseUrl")
        classification = classify_license(license_code)
        if classification is None or license_url is None:
            return None
        assert license_code is not None
        use_mode, rights_status = classification
        # NC/ND/custom/missing licenses are never persisted as downloadable assets.
        if rights_status == RightsStatus.REJECTED:
            return None
        source_id = title
        asset_id = "asset-" + hashlib.sha256(source_id.encode("utf-8")).hexdigest()[:24]
        page_url = "https://commons.wikimedia.org/wiki/" + title.replace(" ", "_")
        safe_license_tag = re.sub(r"[^a-z0-9]+", "_", license_code.lower()).strip("_")
        return AssetManifestV1(
            asset_id=asset_id,
            source_id=source_id,
            source_site=self.source_site,
            source_api_or_package_url=self.source_api_or_package_url,
            original_asset_url=url,
            original_page_url=page_url,
            creator=_metadata_value(metadata, "Artist", max_chars=500),
            title=_metadata_value(metadata, "ImageDescription", max_chars=500) or title[:500],
            license_code=license_code,
            license_url=license_url,
            attribution_text=_metadata_value(metadata, "Credit", max_chars=1000)
            or _metadata_value(metadata, "Artist", max_chars=1000),
            asset_type=controlled_query.asset_type,
            use_mode=use_mode,
            # These controlled searches deliberately return human pose/expression
            # references.  License metadata is retained above, while likeness,
            # trademark, and private-place risk always remains human-review-only.
            rights_status=RightsStatus.NEEDS_HUMAN_REVIEW,
            bytes_size=source_bytes_size,
            tags=[
                *controlled_query.tags,
                "source:wikimedia_commons",
                f"license:{safe_license_tag}",
            ],
            search_query=controlled_query.query,
            collected_at=_now(),
        )


class AssetLibraryService:
    """Idempotent manifest, download, report, and review operations for local assets."""

    def __init__(
        self, paths: AssetLibraryPaths | None = None, client: HttpClient | None = None
    ) -> None:
        self.paths = paths or AssetLibraryPaths()
        self._client: HttpClient = cast(
            HttpClient,
            client or httpx.Client(headers={"User-Agent": "longtext-comic-agent/asset-intake"}),
        )

    def discover(
        self,
        *,
        limit: int = 150,
        source: str = "wikimedia_commons",
        tags: set[str] | None = None,
        dry_run: bool = True,
    ) -> list[AssetManifestV1]:
        """Discover only official-API candidates; dry-run does not write manifests."""

        if source != "wikimedia_commons":
            raise AssetIntakeError("only the Wikimedia Commons official API is enabled")
        if not 1 <= limit <= 300:
            raise AssetIntakeError("limit must be between 1 and 300")
        adapter = WikimediaCommonsSource(self._client)
        per_query = max(
            1, min(30, (limit + len(CONTROLLED_QUERIES) - 1) // len(CONTROLLED_QUERIES))
        )
        found: dict[str, AssetManifestV1] = {}
        for controlled_query in CONTROLLED_QUERIES:
            if tags is not None and not tags.intersection(controlled_query.tags):
                continue
            for manifest in adapter.discover(controlled_query, per_query):
                found.setdefault(manifest.asset_id, manifest)
                if len(found) >= limit:
                    break
            if len(found) >= limit:
                break
        manifests = list(found.values())
        if not dry_run:
            self.paths.ensure_layout()
            for manifest in manifests:
                self.save_manifest(manifest)
        return manifests

    def load_manifests(self) -> list[AssetManifestV1]:
        """Load recoverable JSON manifests in stable order without scanning other data."""

        if not self.paths.manifests.exists():
            return []
        manifests: list[AssetManifestV1] = []
        for path in sorted(self.paths.manifests.glob("*.json")):
            manifests.append(AssetManifestV1.model_validate_json(path.read_text(encoding="utf-8")))
        return sorted(manifests, key=lambda manifest: manifest.asset_id)

    def save_manifest(self, manifest: AssetManifestV1) -> Path:
        """Write one portable manifest atomically; source binary files are never in Git."""

        self.paths.ensure_layout()
        path = self.paths.manifests / f"{manifest.asset_id}.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(path)
        return path

    def download_pending(
        self, *, max_files: int = 300, max_file_bytes: int = DEFAULT_MAX_FILE_BYTES
    ) -> list[AssetManifestV1]:
        """Download only explicitly eligible manifests, once, with quota and type checks."""

        if not 1 <= max_files <= 300 or max_file_bytes <= 0:
            raise AssetIntakeError("download limits are outside the bounded intake policy")
        self.paths.ensure_layout()
        downloaded: list[AssetManifestV1] = []
        for manifest in self.load_manifests():
            if len(downloaded) >= max_files:
                break
            if not self._download_eligible(manifest):
                continue
            try:
                updated = self._download_one(manifest, max_file_bytes=max_file_bytes)
            except AssetIntakeError:
                # An item-level error is intentionally retained pending human review.
                continue
            self.save_manifest(updated)
            downloaded.append(updated)
        return downloaded

    def review_asset(
        self, asset_id: str, decision: ReviewStatus, note: str | None = None
    ) -> AssetManifestV1:
        """Apply a human decision by moving, never deleting, a local asset."""

        if decision not in {
            ReviewStatus.APPROVED,
            ReviewStatus.REFERENCE_ONLY,
            ReviewStatus.REJECTED,
        }:
            raise AssetIntakeError("review decision must be approved, reference-only, or rejected")
        manifest = self._manifest_by_id(asset_id)
        updated = manifest.model_copy(
            update={
                "review_status": decision,
                "reviewed_at": _now(),
                "reviewer_note": note or None,
                "use_mode": (
                    UseMode.REFERENCE_ONLY
                    if decision == ReviewStatus.REFERENCE_ONLY
                    else manifest.use_mode
                ),
                "rights_status": (
                    RightsStatus.REJECTED
                    if decision == ReviewStatus.REJECTED
                    else manifest.rights_status
                ),
            }
        )
        if manifest.local_relative_path:
            source = self.paths.resolve_relative(manifest.local_relative_path)
            if source.exists():
                destination_dir = {
                    ReviewStatus.APPROVED: self.paths.approved,
                    ReviewStatus.REFERENCE_ONLY: self.paths.reference_only,
                    ReviewStatus.REJECTED: self.paths.rejected,
                }[decision]
                destination = destination_dir / source.name
                if destination.exists() and destination != source:
                    raise AssetIntakeError(
                        "review destination already contains an asset with this name"
                    )
                destination_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(source), str(destination))
                updated = updated.model_copy(
                    update={
                        "local_relative_path": destination.relative_to(self.paths.root).as_posix()
                    }
                )
        self.save_manifest(updated)
        return updated

    def report(self) -> dict[str, object]:
        """Return a source-free, stable inventory summary for local human review."""

        manifests = self.load_manifests()
        local_files = [
            path
            for directory in (
                self.paths.production_candidates,
                self.paths.attribution_review,
                self.paths.reference_only,
                self.paths.approved,
                self.paths.rejected,
                self.paths.thumbnails,
            )
            if directory.exists()
            for path in directory.rglob("*")
            if path.is_file()
        ]
        checksum_counts = Counter(manifest.checksum for manifest in manifests if manifest.checksum)
        tag_counts = Counter(tag for manifest in manifests for tag in manifest.tags)
        rejected_reasons = Counter(
            manifest.reviewer_note or "license_or_review_rejected"
            for manifest in manifests
            if manifest.review_status == ReviewStatus.REJECTED
            or manifest.rights_status == RightsStatus.REJECTED
        )
        return {
            "total_files": len(local_files),
            "manifest_count": len(manifests),
            "total_bytes": sum(path.stat().st_size for path in local_files),
            "downloaded_candidate_count": sum(
                1 for manifest in manifests if manifest.local_relative_path
            ),
            "estimated_pending_asset_bytes": sum(
                manifest.bytes_size or 0
                for manifest in manifests
                if manifest.local_relative_path is None
            ),
            "by_source": dict(
                sorted(Counter(manifest.source_site for manifest in manifests).items())
            ),
            "by_license": dict(
                sorted(
                    Counter(manifest.license_code or "MISSING" for manifest in manifests).items()
                )
            ),
            "by_tag": dict(sorted(tag_counts.items())),
            "by_review_status": dict(
                sorted(Counter(manifest.review_status for manifest in manifests).items())
            ),
            "missing_metadata": [
                manifest.asset_id
                for manifest in manifests
                if not manifest.license_code
                or not manifest.license_url
                or not manifest.original_page_url
                or not manifest.creator
            ],
            "duplicate_checksums": sorted(
                checksum for checksum, count in checksum_counts.items() if count > 1
            ),
            "rejected_reasons": dict(sorted(rejected_reasons.items())),
        }

    def _download_eligible(self, manifest: AssetManifestV1) -> bool:
        return (
            manifest.review_status == ReviewStatus.PENDING
            and manifest.use_mode == UseMode.PRODUCTION_CANDIDATE
            and manifest.license_code is not None
            and (classification := classify_license(manifest.license_code)) is not None
            and classification[1]
            in {
                RightsStatus.VERIFIED_CC0,
                RightsStatus.VERIFIED_PUBLIC_DOMAIN,
                RightsStatus.ATTRIBUTION_REQUIRED,
            }
            and bool(manifest.original_asset_url)
            and bool(manifest.license_url)
            and bool(manifest.original_page_url)
            and bool(manifest.creator)
        )

    def _download_one(self, manifest: AssetManifestV1, *, max_file_bytes: int) -> AssetManifestV1:
        assert manifest.original_asset_url is not None
        payload, mime = self._fetch_allowed_binary(manifest.original_asset_url, max_file_bytes)
        checksum = hashlib.sha256(payload).hexdigest()
        existing = next(
            (
                item
                for item in self.load_manifests()
                if item.checksum == checksum and item.local_relative_path
            ),
            None,
        )
        if existing is not None:
            return manifest.model_copy(
                update={
                    "checksum": checksum,
                    "bytes_size": len(payload),
                    "local_relative_path": existing.local_relative_path,
                }
            )
        suffix = (
            mimetypes.guess_extension(mime)
            or Path(urlparse(manifest.original_asset_url).path).suffix
        )
        if suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
            raise AssetIntakeError("downloaded asset has unsupported extension")
        destination = self._download_destination(manifest, suffix)
        remaining = MAX_LIBRARY_BYTES - self._library_bytes()
        if len(payload) > remaining:
            raise AssetIntakeError("asset library quota would be exceeded")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
        try:
            thumbnail_relative_path = self._download_thumbnail(
                manifest, max_file_bytes=min(max_file_bytes, 2 * 1024**2)
            )
        except AssetIntakeError:
            # A thumbnail is a local review convenience, not a license/evidence
            # prerequisite. Retain the auditable original rather than orphaning it.
            thumbnail_relative_path = None
        return manifest.model_copy(
            update={
                "local_relative_path": destination.relative_to(self.paths.root).as_posix(),
                "thumbnail_relative_path": thumbnail_relative_path,
                "checksum": checksum,
                "bytes_size": len(payload),
            }
        )

    def _download_thumbnail(self, manifest: AssetManifestV1, *, max_file_bytes: int) -> str | None:
        if manifest.source_site != WikimediaCommonsSource.source_site:
            return None
        thumbnail_url = WikimediaCommonsSource(self._client).thumbnail_url(manifest.source_id)
        if not thumbnail_url:
            return None
        payload, mime = self._fetch_allowed_binary(thumbnail_url, max_file_bytes)
        suffix = mimetypes.guess_extension(mime) or ".jpg"
        path = self.paths.thumbnails / f"{manifest.asset_id}{suffix}"
        remaining = MAX_LIBRARY_BYTES - self._library_bytes()
        if len(payload) > remaining:
            raise AssetIntakeError("asset library quota would be exceeded")
        path.write_bytes(payload)
        return path.relative_to(self.paths.root).as_posix()

    def _fetch_allowed_binary(self, url: str, max_file_bytes: int) -> tuple[bytes, str]:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in ALLOWED_DOWNLOAD_DOMAINS:
            raise AssetIntakeError("download URL is not an allowed official media host")
        try:
            response = self._client.get(url, follow_redirects=False, timeout=30.0)
            if 300 <= response.status_code < 400:
                raise AssetIntakeError("redirected downloads are not followed")
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise AssetIntakeError("official asset download request failed") from error
        content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
        if content_type not in ALLOWED_IMAGE_MIME_TYPES:
            raise AssetIntakeError("downloaded content type is not an allowed image")
        declared_size = response.headers.get("content-length")
        if declared_size is not None and (
            not declared_size.isdigit() or int(declared_size) > max_file_bytes
        ):
            raise AssetIntakeError("downloaded file exceeds the per-file limit")
        payload = response.content
        if len(payload) == 0 or len(payload) > max_file_bytes:
            raise AssetIntakeError("downloaded file exceeds the per-file limit")
        return payload, content_type

    def _download_destination(self, manifest: AssetManifestV1, suffix: str) -> Path:
        license_classification = classify_license(manifest.license_code)
        is_cc0_or_public_domain = license_classification is not None and license_classification[
            1
        ] in {RightsStatus.VERIFIED_CC0, RightsStatus.VERIFIED_PUBLIC_DOMAIN}
        base = (
            self.paths.production_candidates
            if is_cc0_or_public_domain
            else self.paths.attribution_review
        )
        return base / f"{manifest.asset_id}{suffix.lower()}"

    def _library_bytes(self) -> int:
        if not self.paths.root.exists():
            return 0
        return sum(path.stat().st_size for path in self.paths.root.rglob("*") if path.is_file())

    def _manifest_by_id(self, asset_id: str) -> AssetManifestV1:
        for manifest in self.load_manifests():
            if manifest.asset_id == asset_id:
                return manifest
        raise AssetIntakeError("asset manifest was not found")


def reference_only_manifest(
    *, source_site: str, original_page_url: str, search_query: str, note: str
) -> AssetManifestV1:
    """Create a no-download link record for sources outside the verified intake path."""

    digest = hashlib.sha256(f"{source_site}|{original_page_url}".encode()).hexdigest()[:24]
    return AssetManifestV1(
        asset_id=f"reference-{digest}",
        source_id=original_page_url,
        source_site=source_site,
        source_api_or_package_url=original_page_url,
        original_page_url=original_page_url,
        asset_type=AssetType.OTHER_REFERENCE,
        use_mode=UseMode.REFERENCE_ONLY,
        rights_status=RightsStatus.NEEDS_HUMAN_REVIEW,
        review_status=ReviewStatus.REFERENCE_ONLY,
        tags=[
            "standing",
            "neutral",
            "single_person",
            f"source:{source_site.lower().replace(' ', '_')}",
            "license:unverified",
        ],
        search_query=search_query,
        collected_at=_now(),
        reviewed_at=_now(),
        reviewer_note=note,
    )
