from pathlib import Path
from urllib.parse import urlsplit

import pytest


def test_pages_without_api_and_explicit_connection_switch():
    playwright = pytest.importorskip("playwright.sync_api")
    product = Path(__file__).resolve().parents[1] / "web_product"
    with playwright.sync_playwright() as driver:
        browser = driver.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page()
        errors = []
        api_calls = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def serve(route):
            url = urlsplit(route.request.url)
            if url.netloc != "pages.example":
                api_calls.append(url.path)
                route.fulfill(status=503, content_type="application/json", body='{"detail":"离线"}',
                              headers={"access-control-allow-origin": "https://pages.example"})
                return
            path = url.path.removeprefix("/comic/") or "index.html"
            source = product / path
            if source.is_file():
                content_type = {".js": "application/javascript", ".css": "text/css",
                                ".html": "text/html"}.get(source.suffix, "image/svg+xml")
                route.fulfill(body=source.read_bytes(), content_type=content_type)
            else:
                route.fulfill(status=404)

        page.route("**/*", serve)
        page.goto("https://pages.example/comic/")
        page.locator("#mode-notice").filter(has_text="演示模式").wait_for()
        page.locator("#story-file").set_input_files({
            "name": "story.txt", "mimeType": "text/plain", "buffer": "测试故事".encode(),
        })
        page.locator("#prompt").fill("电影感")
        page.locator("#start-button").click()
        page.get_by_role("heading", name="你的漫画完成了").wait_for(timeout=20000)
        page.get_by_role("button", name="开始阅读").click()
        page.wait_for_function("document.querySelector('[data-reader-image]')?.naturalWidth > 0")
        assert not api_calls
        page.get_by_role("button", name="返回作品", exact=False).click()
        page.get_by_role("button", name="连接设置").click()
        page.locator("#api-address").fill("https://offline.example")
        page.get_by_role("button", name="连接并使用").click()
        page.locator("#connection-error").filter(has_text="离线").wait_for()
        assert page.evaluate("window.__COMIC_APP__.API_MODE") == "mock"
        # User-initiated API connection persists only after a successful probe.
        page.route("https://online.example/**", lambda route: route.fulfill(
            content_type="application/json", body='{"referenceNames":["room"]}',
            headers={"access-control-allow-origin": "https://pages.example"},
        ))
        page.locator("#api-address").fill("https://online.example")
        page.get_by_role("button", name="连接并使用").click()
        page.locator("#mode-notice").filter(has_text="真实服务模式").wait_for()
        page.get_by_role("button", name="连接设置").click()
        page.get_by_role("button", name="使用演示模式").click()
        page.locator("#mode-notice").filter(has_text="演示模式").wait_for()
        assert not errors
        browser.close()
