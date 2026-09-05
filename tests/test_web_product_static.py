from pathlib import Path

from fastapi.testclient import TestClient

from comic_agent.main import create_app


def test_product_shell_and_module_assets_are_served(tmp_path: Path) -> None:
    app = create_app(f"sqlite+pysqlite:///{tmp_path / 'product.sqlite'}")
    with TestClient(app) as client:
        page = client.get("/")
        css = client.get("/product/css/app.css")
        javascript = client.get("/product/js/app.js")
        mock_api = client.get("/product/js/api/mock-comic-generation-api.js")

    assert page.status_code == css.status_code == javascript.status_code == 200
    assert "绘卷" in page.text
    assert 'type="module"' in page.text
    assert "GenerationStore" in javascript.text
    assert "MockComicGenerationAPI" in mock_api.text


def test_frontend_contract_covers_customer_actions() -> None:
    root = Path(__file__).resolve().parents[1] / "web_product" / "js"
    contract = (root / "api" / "comic-generation-api.js").read_text(encoding="utf-8")
    mock = (root / "api" / "mock-comic-generation-api.js").read_text(encoding="utf-8")
    ui = (root / "components" / "ui.js").read_text(encoding="utf-8")

    for method in (
        "createGeneration",
        "getGeneration",
        "getGenerationResult",
        "listGenerations",
        "cancelGeneration",
        "retryGeneration",
        "downloadComic",
    ):
        assert method in contract
        assert method in mock
    for state in ("RUNNING", "COMPLETED", "FAILED", "CANCELLED"):
        assert state in mock or state in ui
    assert "data-action=\"fullscreen\"" in ui
    assert "data-action=\"previous\"" in ui
    assert "data-action=\"next\"" in ui


def test_mock_timer_is_isolated_from_ui_and_state_modules() -> None:
    root = Path(__file__).resolve().parents[1] / "web_product" / "js"
    assert "setTimeout" in (root / "api" / "mock-comic-generation-api.js").read_text(
        encoding="utf-8"
    )
    assert "setTimeout" not in (root / "components" / "ui.js").read_text(encoding="utf-8")


def test_pages_bundle_is_relative_and_contains_local_comic_assets() -> None:
    product = Path(__file__).resolve().parents[1] / "web_product"
    index = (product / "index.html").read_text(encoding="utf-8")
    mock = (product / "js" / "api" / "mock-comic-generation-api.js").read_text(
        encoding="utf-8"
    )
    config = (product / "js" / "config.js").read_text(encoding="utf-8")

    assert 'href="./css/app.css"' in index
    assert 'src="./js/app.js"' in index
    assert "DEPLOY_CONFIG.apiMode" in config
    assert "data:image/svg+xml" not in mock
    assert "mock://" not in mock
    assert "localhost" not in mock
    assert "./assets/mock-comic/page-" in mock
    assets = sorted((product / "assets" / "mock-comic").glob("page-*.svg"))
    assert len(assets) == 12
    assert all(asset.read_text(encoding="utf-8").startswith("<svg") for asset in assets)


def test_pages_workflow_deploys_only_the_static_product() -> None:
    workflow = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" / "deploy-pages.yml"
    ).read_text(encoding="utf-8")
    assert "actions/upload-pages-artifact@v3" in workflow
    assert "actions/deploy-pages@v4" in workflow
    assert "path: ./web_product" in workflow
    assert "pages: write" in workflow
    assert "id-token: write" in workflow
    assert "uvicorn" not in workflow
