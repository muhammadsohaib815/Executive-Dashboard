"""Static contract tests for independent dashboard frontend assets."""
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_frontend_has_dedicated_template_and_assets():
    frontend = PROJECT_ROOT / "frontend"
    assert (frontend / "html" / "index.html").is_file()
    assert (frontend / "css" / "styles.css").is_file()
    for name in ("config.js", "components.js", "api.js", "app.js", "ai-insights.js"):
        assert (frontend / "js" / name).is_file()

    # The legacy shared asset locations must not be used after migration.
    assert not (PROJECT_ROOT / "css").exists()
    assert not (PROJECT_ROOT / "js").exists()


def test_fastapi_uses_dedicated_frontend_asset_urls():
    server = (PROJECT_ROOT / "scripts" / "server.py").read_text(encoding="utf-8")
    assert 'FRONTEND_DIR = ROOT / "frontend"' in server
    assert 'StaticFiles(directory=FRONTEND_DIR / folder)' in server

