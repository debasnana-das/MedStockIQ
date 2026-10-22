from fastapi.testclient import TestClient

from app.main import app


def test_root_serves_local_dashboard_and_assets() -> None:
    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "MedStockIQ" in page.text
        assert "Inventory intelligence" in page.text
        script = client.get("/app.js")
        stylesheet = client.get("/styles.css")
        helper = client.get("/meta_controls.js")
        assert script.status_code == 200
        assert "confirmMappingButton" in script.text
        assert stylesheet.status_code == 200
        assert "--forest" in stylesheet.text
        assert helper.status_code == 200
        assert "month_end" in helper.text
