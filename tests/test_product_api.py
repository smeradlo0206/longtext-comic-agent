import io
import json
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from comic_agent.api.product import _page_path
from comic_agent.config import get_settings
from comic_agent.main import create_app
from comic_agent.schemas.comic_production import ComicProductionRunV1
from flux2_agent.catalog import load_catalog, write_catalog
from flux2_agent.planning import build_plan
from flux2_agent.queueing import QueueStore
from flux2_agent.workflow import run_workflow


@pytest.fixture()
def product_client(tmp_path, monkeypatch):
    refs = tmp_path / "inputs" / "references"
    refs.mkdir(parents=True)
    Image.new("RGB", (16, 16), "white").save(refs / "room.png")
    write_catalog(tmp_path)
    template = {
        "document_id": "AUTO",
        "comic_style": "test manga",
        "global_prompt": "one panel",
        "selected_assets": [
            {
                "slot": "SCENE_ROOM",
                "asset_id": "asset-001",
                "entity_id": "location.room",
                "role": "scene",
                "description": "a quiet room",
                "display_name": "客厅",
            }
        ],
        "generation": {"width": 256, "height": 256, "steps": 1, "attempts": 1},
        "visual_qa": {"enabled": False},
    }
    path = tmp_path / "preset.json"
    path.write_text(json.dumps(template), encoding="utf-8")
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("IMAGE_QUEUE_ROOT", "queue")
    monkeypatch.setenv("IMAGE_RUN_ROOT", "runs")
    monkeypatch.setenv("PRODUCT_REQUEST_TEMPLATE", str(path))
    monkeypatch.setenv("CORS_ORIGINS", '["https://example.github.io"]')
    get_settings.cache_clear()
    app = create_app(f"sqlite+pysqlite:///{tmp_path / 'product.db'}")
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.state.engine.dispose()
        get_settings.cache_clear()


def create_run(client):
    assert client.post("/projects", json={"project_id": "pages-test", "name": "客厅"}).is_success
    source = "第一章 客厅\n\n" + "\n\n".join(
        f"第{i}分钟，客厅窗边的茶杯映着阳光。" for i in range(12)
    )
    imported = client.post(
        "/projects/pages-test/documents/import",
        files={"file": ("story.txt", source.encode(), "text/plain")},
    )
    assert imported.is_success, imported.text
    payload = {
        "document_id": imported.json()["document"]["document_id"],
        "prompt": "宁静的画面",
        "style": "水彩",
        "max_pages": 2,
        "aspect_ratio": "landscape",
    }
    response = client.post("/projects/pages-test/comic-runs/from-product", json=payload)
    assert response.is_success, response.text
    return response.json(), payload


def test_pages_upload_queue_result_images_and_downloads(product_client, tmp_path):
    client = product_client
    assert client.get("/product-capabilities").json()["referenceNames"] == ["客厅"]
    run, payload = create_run(client)
    run_id = run["run_id"]
    assert run["status"] == "QUEUED"
    repeat = client.post("/projects/pages-test/comic-runs/from-product", json=payload)
    assert repeat.json()["run_id"] == run_id
    queue = QueueStore(tmp_path / "queue")
    assert len(queue.list_items("pending")) == 1
    assert client.get(f"/comic-runs/{run_id}/download").status_code == 409
    assert client.get(f"/comic-runs/{run_id}/pages/1").status_code == 409
    item = queue.claim_next("test-worker")
    assert item is not None
    assert item.job.generation.width == 1024
    assert item.job.generation.height == 768
    assert "宁静的画面" in item.job.global_prompt
    assert client.get(f"/comic-runs/{run_id}").json()["status"] == "RUNNING"
    assert client.post(f"/comic-runs/{run_id}/cancel").status_code == 409

    class FakeBackend:
        settings = item.job.generation

        def generate(self, shot, seed, *, continuity_path=None):
            return Image.new("RGB", (16, 16), (seed % 255, 64, 128))

    plan = build_plan(tmp_path, item.job, load_catalog(tmp_path))
    output = run_workflow(item.job, plan, tmp_path / "runs", backend=FakeBackend())
    queue.succeed(item, output)
    completed = client.get(f"/comic-runs/{run_id}").json()
    assert completed["status"] == "SUCCEEDED"
    assert len(completed["page_artifacts"]) == 2
    assert (output / "production-manifest.json").is_file()
    image = client.get(f"/comic-runs/{run_id}/pages/1")
    assert image.headers["content-type"] == "image/png"
    Image.open(io.BytesIO(image.content)).verify()
    assert client.get(f"/comic-runs/{run_id}/pages/999").status_code == 404
    archive = client.get(f"/comic-runs/{run_id}/download?format=zip")
    with zipfile.ZipFile(io.BytesIO(archive.content)) as zf:
        assert zf.namelist() == ["page-001.png", "page-002.png", "manifest.json"]
    pdf = client.get(f"/comic-runs/{run_id}/download?format=pdf")
    assert pdf.content.startswith(b"%PDF-")
    assert pdf.headers["content-type"] == "application/pdf"
    assert client.get(f"/comic-runs/{run_id}/download?format=exe").status_code == 422
    model = ComicProductionRunV1.model_validate(completed)
    unsafe_page = model.page_artifacts[0].model_copy(update={"file": "../../outside.png"})
    unsafe = model.model_copy(update={"page_artifacts": [unsafe_page]})
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as error:
        _page_path(unsafe, 1)
    assert error.value.status_code == 403


def test_pages_cancel_retry_and_cors(product_client, tmp_path):
    client = product_client
    run, _ = create_run(client)
    run_id = run["run_id"]
    queue = QueueStore(tmp_path / "queue")
    item = queue.claim_next("test")
    queue.fail(item, "test failure")
    assert client.get(f"/comic-runs/{run_id}").json()["status"] == "FAILED"
    assert client.post(f"/comic-runs/{run_id}/retry").json()["status"] == "QUEUED"
    assert client.post(f"/comic-runs/{run_id}/cancel").json()["status"] == "CANCELLED"
    assert client.post(f"/comic-runs/{run_id}/retry").status_code == 409
    preflight = client.options(
        "/projects",
        headers={
            "Origin": "https://example.github.io",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "https://example.github.io"
    assert (
        "access-control-allow-origin"
        not in client.get(
            "/product-capabilities", headers={"Origin": "https://untrusted.example"}
        ).headers
    )


def test_missing_preset_and_invalid_input(product_client, monkeypatch):
    client = product_client
    run, payload = create_run(client)
    assert run["status"] == "QUEUED"
    assert (
        client.post(
            "/projects/pages-test/comic-runs/from-product", json={**payload, "max_pages": 999}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/projects/pages-test/comic-runs/from-product",
            json={**payload, "document_id": "other-document"},
        ).status_code
        == 400
    )
    monkeypatch.setenv("PRODUCT_REQUEST_TEMPLATE", "missing.json")
    get_settings.cache_clear()
    assert client.get("/product-capabilities").status_code == 503


def test_pages_browser_upload_read_download_and_resume(product_client, tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    product = Path(__file__).resolve().parents[1] / "web_product"
    client = product_client
    errors = []
    with playwright.sync_playwright() as driver:
        browser = driver.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(accept_downloads=True)
        page.on("pageerror", lambda error: errors.append(str(error)))

        def serve(route):
            url = urlsplit(route.request.url)
            if url.netloc == "api.example":
                headers = {k: v for k, v in route.request.headers.items() if k != "host"}
                response = client.request(
                    route.request.method,
                    url.path + ("?" + url.query if url.query else ""),
                    headers=headers,
                    content=route.request.post_data_buffer,
                )
                route.fulfill(
                    status=response.status_code,
                    body=response.content,
                    headers={
                        **dict(response.headers),
                        "access-control-allow-origin": "https://pages.example",
                    },
                )
                return
            path = url.path.removeprefix("/comic/") or "index.html"
            if path == "js/deploy-config.js":
                route.fulfill(
                    content_type="application/javascript",
                    body=(
                        "export const DEPLOY_CONFIG = "
                        "{apiMode:'real',apiBaseUrl:'https://api.example'};"
                    ),
                )
            elif (product / path).is_file():
                content_type = {
                    ".js": "application/javascript",
                    ".css": "text/css",
                    ".html": "text/html",
                }.get(Path(path).suffix, "image/svg+xml")
                route.fulfill(body=(product / path).read_bytes(), content_type=content_type)
            else:
                route.fulfill(status=404)

        page.route("https://**/*", serve)
        page.goto("https://pages.example/comic/")
        page.locator("#service-status").filter(has_text="已连接生成服务").wait_for()
        assert not page.locator(".demo-switch").is_visible()
        assert not page.locator(".showcase").is_visible()
        page.locator("#story-file").set_input_files(
            {
                "name": "story.txt",
                "mimeType": "text/plain",
                "buffer": "第一章 客厅\n\n客厅窗边的茶杯映着阳光。".encode(),
            }
        )
        page.locator("#prompt").fill("宁静的画面")
        page.locator("#start-button").click()
        page.locator(".current-message").filter(has_text="队列").wait_for()
        # Task records survive a reload and can resume polling through the library.
        page.reload()
        page.get_by_role("button", name="我的作品").click()
        page.locator(".work-card").click()
        page.locator(".current-message").filter(has_text="队列").wait_for()
        queue = QueueStore(tmp_path / "queue")
        item = queue.claim_next("browser-test")
        assert item is not None

        class FakeBackend:
            settings = item.job.generation

            def generate(self, shot, seed, *, continuity_path=None):
                return Image.new("RGB", (16, 16), (seed % 255, 64, 128))

        plan = build_plan(tmp_path, item.job, load_catalog(tmp_path))
        output = run_workflow(item.job, plan, tmp_path / "runs", backend=FakeBackend())
        queue.succeed(item, output)
        page.get_by_role("heading", name="你的漫画完成了").wait_for(timeout=15000)
        page.get_by_role("button", name="开始阅读").click()
        page.locator("[data-reader-image]").wait_for()
        page.wait_for_function("document.querySelector('[data-reader-image]').naturalWidth > 0")
        page.get_by_role("button", name="返回作品", exact=False).click()
        for label, suffix in [("下载 PDF", "pdf"), ("下载图片包 ZIP", "zip")]:
            with page.expect_download() as download_event:
                page.get_by_role("button", name=label, exact=True).click()
            assert download_event.value.suggested_filename == f"comic.{suffix}"
        page.get_by_role("button", name="重新生成", exact=True).click()
        page.get_by_role("button", name="保留设置返回创作").click()
        # A new run can fail and retry, without losing the saved source/preferences.
        page.locator("#story-file").set_input_files(
            {
                "name": "second.txt",
                "mimeType": "text/plain",
                "buffer": "第一章 客厅\n\n客厅窗边的茶杯映着阳光。".encode(),
            }
        )
        page.locator("#start-button").click()
        page.locator(".current-message").filter(has_text="队列").wait_for()
        failed = queue.claim_next("browser-failure")
        assert failed is not None
        queue.fail(failed, "test failure")
        page.get_by_role("button", name="重新尝试").wait_for(timeout=15000)
        page.get_by_role("button", name="重新尝试").click()
        page.locator(".current-message").filter(has_text="队列").wait_for()
        page.get_by_role("button", name="取消生成", exact=True).click()
        page.get_by_role("button", name="确认取消").click()
        page.get_by_role("heading", name="生成已取消").wait_for()
        assert not errors, errors
        browser.close()
