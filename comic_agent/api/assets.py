"""Loopback-only local review page for reference-asset manifests."""

from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from comic_agent.schemas.assets import ReviewStatus
from comic_agent.services.asset_library import AssetIntakeError, AssetLibraryService

router = APIRouter()
_LOOPBACK_CLIENTS = frozenset({"127.0.0.1", "::1", "localhost", "testclient"})


def _require_loopback(request: Request) -> None:
    """Reject remote review access even if a server is started with a wrong bind."""

    host = request.client.host if request.client else ""
    if host not in _LOOPBACK_CLIENTS:
        raise HTTPException(status_code=403, detail="asset review is available only on loopback")


def _service() -> AssetLibraryService:
    return AssetLibraryService()


def _matching(manifest_tags: list[str], requested: str | None) -> bool:
    return requested is None or requested in manifest_tags


@router.get("/console/assets/", response_class=HTMLResponse)
def asset_review_console(
    request: Request,
    era: str | None = None,
    tag: str | None = None,
    source: str | None = None,
    license_code: str | None = None,
    status: ReviewStatus | None = None,
    max_bytes: int | None = None,
) -> HTMLResponse:
    """Render a small escaped local review page; no third-party upload is involved."""

    _require_loopback(request)
    manifests = _service().load_manifests()
    records = [
        manifest
        for manifest in manifests
        if _matching(manifest.tags, era)
        and _matching(manifest.tags, tag)
        and (source is None or manifest.source_site == source)
        and (license_code is None or manifest.license_code == license_code)
        and (status is None or manifest.review_status == status)
        and (max_bytes is None or (manifest.bytes_size or 0) <= max_bytes)
    ]
    cards = "".join(_render_card(manifest) for manifest in records)
    styles = (
        "body{font-family:sans-serif;margin:2rem}.grid{display:grid;"
        "grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:1rem}"
        "article{border:1px solid #ccc;padding:1rem}img{width:100%;height:200px;"
        "object-fit:contain;background:#f5f5f5}.meta{overflow-wrap:anywhere}"
    )
    filters = "".join(
        (
            f'<label>时代 <input name="era" value="{escape(era or "")}"></label>',
            f'<label>标签 <input name="tag" value="{escape(tag or "")}"></label>',
            f'<label>来源 <input name="source" value="{escape(source or "")}"></label>',
            '<label>许可证 <input name="license_code" '
            f'value="{escape(license_code or "")}"></label>',
            '<label>最大字节 <input name="max_bytes" type="number"></label>',
            "<button>筛选</button>",
        )
    )
    body = (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        f"<title>本地素材审核</title><style>{styles}</style></head><body>"
        "<h1>人物姿势与神态素材待审</h1>"
        "<p>仅本机审核；保留、仅参考、拒绝都会保留文件与审计记录。</p>"
        f'<form method="get">{filters}</form><section class="grid">'
        f"{cards or '<p>没有符合条件的素材。</p>'}</section></body></html>"
    )
    return HTMLResponse(body)


@router.get("/console/assets/file/{asset_id}")
def local_asset_file(request: Request, asset_id: str) -> FileResponse:
    """Serve only an already-local, manifest-addressed file to the loopback page."""

    _require_loopback(request)
    service = _service()
    manifest = next((item for item in service.load_manifests() if item.asset_id == asset_id), None)
    if manifest is None or manifest.local_relative_path is None:
        raise HTTPException(status_code=404, detail="local asset not found")
    try:
        relative_path = manifest.thumbnail_relative_path or manifest.local_relative_path
        path = service.paths.resolve_relative(relative_path)
    except AssetIntakeError as error:
        raise HTTPException(status_code=400, detail="invalid local asset path") from error
    if not path.is_file():
        raise HTTPException(status_code=404, detail="local asset file not found")
    return FileResponse(Path(path))


@router.post("/console/assets/review/{asset_id}")
def review_asset(
    request: Request,
    asset_id: str,
    decision: Annotated[ReviewStatus, Form()],
    note: Annotated[str, Form()] = "",
) -> RedirectResponse:
    """Persist a reviewer decision and move a file without deleting it."""

    _require_loopback(request)
    try:
        _service().review_asset(asset_id, decision, note)
    except AssetIntakeError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return RedirectResponse(url="/console/assets/", status_code=303)


def _render_card(manifest: object) -> str:
    """Render untrusted metadata through HTML escaping rather than string injection."""

    # Kept local so the service remains transport/UI independent.
    from comic_agent.schemas.assets import AssetManifestV1

    assert isinstance(manifest, AssetManifestV1)
    image = (
        f'<img src="/console/assets/file/{escape(manifest.asset_id)}" alt="本地素材缩略图">'
        if manifest.local_relative_path
        else "<div>尚未下载；仅有待审元数据。</div>"
    )
    tag_text = ", ".join(escape(tag) for tag in manifest.tags)
    metadata = "<br>".join(
        (
            f"来源：{escape(manifest.source_site)}",
            f"作者：{escape(manifest.creator or '未声明')}",
            f"许可证：{escape(manifest.license_code or '未声明')}",
            f"大小：{manifest.bytes_size or 0} bytes",
            f"标签：{tag_text}",
            (
                f'<a href="{escape(manifest.original_page_url, quote=True)}" '
                'rel="noreferrer">原始页面</a>'
            ),
        )
    )
    form = (
        f'<form method="post" action="/console/assets/review/{escape(manifest.asset_id)}">'
        '<input name="note" maxlength="2000" placeholder="审核备注">'
        '<button name="decision" value="APPROVED">保留</button>'
        '<button name="decision" value="REFERENCE_ONLY">仅参考</button>'
        '<button name="decision" value="REJECTED">拒绝</button></form>'
    )
    return f'<article>{image}<div class="meta">{metadata}</div>{form}</article>'
