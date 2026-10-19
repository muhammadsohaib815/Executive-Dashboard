"""Static contract tests for independent dashboard frontend assets."""
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_executive_frontend_has_its_own_template_and_assets():
    executive = PROJECT_ROOT / "executive_website"
    assert (executive / "templates" / "index.html").is_file()
    assert (executive / "static" / "css" / "styles.css").is_file()
    for name in ("config.js", "components.js", "api.js", "app.js", "ai-insights.js"):
        assert (executive / "static" / "js" / name).is_file()

    # The legacy shared asset locations must not be used after migration.
    assert not (PROJECT_ROOT / "css").exists()
    assert not (PROJECT_ROOT / "js").exists()


def test_fastapi_keeps_public_executive_asset_urls_stable():
    server = (PROJECT_ROOT / "server.py").read_text(encoding="utf-8")
    assert 'EXECUTIVE_DIR = ROOT / "executive_website"' in server
    assert 'StaticFiles(directory=EXECUTIVE_DIR / "static" / folder)' in server

