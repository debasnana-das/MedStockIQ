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
        assert "MM/YYYY" in helper.text
        # Inventory-history fields follow the nested backend response contract.
        assert "const product = item.product || {}" in script.text
        assert "item.latest_quantity_known !== false" in script.text
        assert "Unknown (conflict / unit ambiguity)" in script.text
        # Analysis results make source dates, stock ages, and warnings visible.
        assert "Analysis data sources" in script.text
        assert "state.latestInventory?.previews?.inventory_snapshots?.[0]?.snapshot_date" in script.text
        assert "Analysis dates do not match" in script.text
        assert "Snapshot / age" in script.text
        assert "Distinct snapshot dates" in script.text
        assert "Single snapshot only" in script.text
        assert "provisional_reasons" in script.text
        assert "review_flags" in script.text
        assert "Review high percentage errors" in script.text
        assert "table-extra-wide" in script.text
        assert "Scroll horizontally to view all columns." in script.text
        assert "Age at report date (days)" in script.text
        assert "Historical snapshot" in script.text
        assert "Historical report — not current stock position" in script.text
        assert "Run-specific readiness" in script.text
        assert "Report date (as of)" in script.text
        assert "table-extra-wide" in stylesheet.text
