"""Pages adapter: server-owned presets and scoped rendered page downloads."""

import io
import json
import zipfile
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response
from PIL import Image
from pydantic import ValidationError

from comic_agent.api.comic_production import (
    ProductionRepositoryDep,
    SourceRepositoryDep,
    _coordinator,
    _workspace_path,
    get_comic_run,
)
from comic_agent.config import get_settings
from comic_agent.schemas.comic_production import ComicProductionRequestV1, ComicProductionRunV1
from comic_agent.schemas.product import ProductGenerationRequestV1

router = APIRouter()


def _template() -> ComicProductionRequestV1:
    path = get_settings().product_request_template
    if path is None:
        raise HTTPException(503, "服务器尚未配置参考素材方案 PRODUCT_REQUEST_TEMPLATE")
    try:
        return ComicProductionRequestV1.model_validate_json(
            _workspace_path(path).read_text(encoding="utf-8")
        )
    except (OSError, ValidationError) as exc:
        raise HTTPException(503, "服务器参考素材方案不可用，请联系管理员") from exc


@router.get("/product-capabilities")
def capabilities() -> dict[str, object]:
    template = _template()
    if template.planner_mode != "DETERMINISTIC_EXTRACTIVE":
        raise HTTPException(503, "当前网页入口需要原文提取式分镜方案")
    return {
        "planner": template.planner_mode,
        "maxPages": 20,
        "referenceNames": [a.display_name or a.slot for a in template.selected_assets],
    }


@router.post("/projects/{project_id}/comic-runs/from-product", response_model=ComicProductionRunV1)
def create_product_run(
    project_id: str,
    payload: ProductGenerationRequestV1,
    source_repository: SourceRepositoryDep,
    production_repository: ProductionRepositoryDep,
) -> ComicProductionRunV1:
    template = _template()
    dimensions = {"portrait": (768, 1024), "landscape": (1024, 768), "square": (1024, 1024)}
    width, height = dimensions[payload.aspect_ratio]
    try:
        request = ComicProductionRequestV1.model_validate(
            {
                **template.model_dump(mode="json"),
                "document_id": payload.document_id,
                "chapter_ids": [],
                "max_pages": payload.max_pages,
                "comic_style": f"漫画风格：{payload.style}",
                "global_prompt": template.global_prompt + "\n用户创作要求：" + payload.prompt,
                "generation": {
                    **template.generation.model_dump(mode="json"),
                    "width": width,
                    "height": height,
                },
            }
        )
        return _coordinator(source_repository, production_repository).compile_and_enqueue(
            project_id=project_id, request=request
        )
    except (OSError, ValueError, KeyError) as exc:
        raise HTTPException(400, "生产任务编译失败，请核对原文与服务器参考素材配置") from exc


def _page_path(run: ComicProductionRunV1, number: int) -> Path:
    if run.status != "SUCCEEDED" or not run.run_root:
        raise HTTPException(409, "漫画尚未完成")
    pages = sorted(run.page_artifacts, key=lambda page: page.order)
    if number < 1 or number > len(pages):
        raise HTTPException(404, "页面不存在")
    root = Path(run.run_root).resolve()
    allowed = _workspace_path(get_settings().image_run_root).resolve()
    path = (root / pages[number - 1].file).resolve()
    if not root.is_relative_to(allowed) or not path.is_relative_to(root):
        raise HTTPException(403, "页面路径不在生产目录中")
    if not path.is_file():
        raise HTTPException(404, "页面文件不存在")
    return path


@router.get("/comic-runs/{run_id}/pages/{number}")
def page_image(
    run_id: str,
    number: int,
    source_repository: SourceRepositoryDep,
    production_repository: ProductionRepositoryDep,
) -> FileResponse:
    run = get_comic_run(run_id, source_repository, production_repository)
    return FileResponse(_page_path(run, number), media_type="image/png")


@router.get("/comic-runs/{run_id}/download")
def download(
    run_id: str,
    source_repository: SourceRepositoryDep,
    production_repository: ProductionRepositoryDep,
    format: Literal["pdf", "zip"] = "zip",
) -> Response:
    run = get_comic_run(run_id, source_repository, production_repository)
    paths = [_page_path(run, n + 1) for n in range(len(run.page_artifacts))]
    if not paths:
        raise HTTPException(409, "漫画尚未完成")
    output = io.BytesIO()
    if format == "zip":
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for number, path in enumerate(paths, 1):
                archive.write(path, f"page-{number:03d}.png")
            archive.writestr(
                "manifest.json", json.dumps({"run_id": run.run_id, "page_count": len(paths)})
            )
        media_type = "application/zip"
    else:
        images = []
        try:
            for path in paths:
                with Image.open(path) as image:
                    images.append(image.convert("RGB"))
            images[0].save(output, format="PDF", save_all=True, append_images=images[1:])
        finally:
            for converted in images:
                converted.close()
        media_type = "application/pdf"
    return Response(
        output.getvalue(),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="comic.{format}"'},
    )
