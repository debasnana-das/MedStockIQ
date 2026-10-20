from __future__ import annotations

from datetime import date


AS_OF = date(2026, 10, 20)


def _snapshot(
    run_id: str,
    product_id: str,
    snapshot_id: str,
    snapshot_date: str,
    quantity: float,
    *,
    organization_id: str = "ORG-1",
    source_product_code: str | None = "SKU-01",
    product_name: str | None = "Synthetic Medicine",
    manufacturer_name: str | None = "Synthetic Manufacturer",
    hsn_code: str | None = "300490",
    pack_description: str | None = "10'S",
    batch_record_id: str | None = "BATCH-1",
    batch_code: str | None = "B001",
    expiry_date: str | None = "2027-06-30",
    manufacturing_date: str | None = "2026-01-01",
    quantity_unit: str = "pack",
) -> dict:
    return {
        "run_id": run_id,
        "snapshot_id": snapshot_id,
        "organization_id": organization_id,
        "snapshot_date": snapshot_date,
        "product_id": product_id,
        "batch_record_id": batch_record_id,
        "quantity_on_hand": quantity,
        "quantity_unit": quantity_unit,
        "stock_basis": "physical",
        "source_product_code": source_product_code,
        "product_name": product_name,
        "manufacturer_name": manufacturer_name,
        "hsn_code": hsn_code,
        "pack_description": pack_description,
        "batch_code": batch_code,
        "expiry_date": expiry_date,
        "manufacturing_date": manufacturing_date,
        "source_file_name": f"{run_id}.csv",
    }


def _ledger(rows: list[dict], *, organization_id: str = "ORG-1"):
    from app.inventory.history import build_inventory_history_ledger

    return build_inventory_history_ledger(rows, organization_id=organization_id, as_of_date=AS_OF)


def test_strong_product_and_batch_identity_matches_across_uploads_and_reports_balance_change() -> None:
    report = _ledger([
        _snapshot("RUN-1", "P1", "S1", "2026-10-01", 10),
        _snapshot("RUN-2", "P-NEW-ID", "S2", "2026-10-02", 8),
    ])

    assert report["status"] == "ready"
    assert report["summary"]["cross_upload_matched_series_count"] == 1
    series = report["series"][0]
    assert series["product_matching_status"] == "matched_across_uploads"
    assert series["batch_matching_method"] == "batch_code_under_matched_product"
    assert series["distinct_run_count"] == 2
    assert series["latest_observation"]["quantity_on_hand"] == 8
    assert series["history"][1]["change_since_previous_snapshot"] == -2


def test_identical_same_date_observations_are_deduplicated_not_summed() -> None:
    report = _ledger([
        _snapshot("RUN-1", "P1", "S1", "2026-10-01", 10),
        _snapshot("RUN-2", "P2", "S2", "2026-10-01", 10),
    ])

    series = report["series"][0]
    assert report["summary"]["duplicate_observation_count"] == 1
    assert series["distinct_snapshot_dates"] == 1
    assert series["history"][0]["quantity_on_hand"] == 10
    assert series["history"][0]["observation_count"] == 2
    assert series["history"][0]["duplicate_observation_count"] == 1


def test_conflicting_same_date_balances_remain_unknown() -> None:
    report = _ledger([
        _snapshot("RUN-1", "P1", "S1", "2026-10-01", 10),
        _snapshot("RUN-2", "P2", "S2", "2026-10-01", 12),
    ])

    series = report["series"][0]
    point = series["history"][0]
    assert point["status"] == "conflict"
    assert point["quantity_on_hand"] is None
    assert point["candidate_quantities"] == [10, 12]
    assert series["latest_quantity_known"] is False
    assert report["summary"]["conflicting_snapshot_date_count"] == 1


def test_contradictory_attributes_block_source_code_match() -> None:
    report = _ledger([
        _snapshot("RUN-1", "P1", "S1", "2026-10-01", 10, product_name="Medicine A"),
        _snapshot("RUN-2", "P2", "S2", "2026-10-02", 12, product_name="Medicine B"),
    ])

    assert report["summary"]["series_count"] == 2
    assert report["summary"]["cross_upload_matched_series_count"] == 0
    assert all(row["product_matching_status"] == "ambiguous" for row in report["series"])
    assert report["summary"]["ambiguous_identity_series_count"] == 2


def test_incomplete_identity_stays_run_local() -> None:
    report = _ledger([
        _snapshot(
            "RUN-1", "P1", "S1", "2026-10-01", 10, source_product_code=None,
            manufacturer_name=None, hsn_code=None, pack_description=None,
        ),
        _snapshot(
            "RUN-2", "P2", "S2", "2026-10-02", 12, source_product_code=None,
            manufacturer_name=None, hsn_code=None, pack_description=None,
        ),
    ])

    assert report["summary"]["series_count"] == 2
    assert report["summary"]["cross_upload_matched_series_count"] == 0
    assert all(row["product_matching_status"] == "run_local_only" for row in report["series"])


def test_unit_conflict_prevents_latest_balance_and_delta_claims() -> None:
    report = _ledger([
        _snapshot("RUN-1", "P1", "S1", "2026-10-01", 10, quantity_unit="pack"),
        _snapshot("RUN-2", "P2", "S2", "2026-10-02", 12, quantity_unit="strip"),
    ])

    series = report["series"][0]
    assert series["unit_status"] == "conflict"
    assert series["latest_quantity_known"] is False
    assert all(point["change_since_previous_snapshot"] is None for point in series["history"])


def test_different_known_batch_expiries_do_not_merge_batch_code() -> None:
    report = _ledger([
        _snapshot("RUN-1", "P1", "S1", "2026-10-01", 10, expiry_date="2027-06-30"),
        _snapshot("RUN-2", "P2", "S2", "2026-10-02", 12, expiry_date="2027-07-31"),
    ])

    assert report["summary"]["series_count"] == 2
    assert report["summary"]["cross_upload_matched_series_count"] == 0
    assert all(row["batch_matching_method"] == "ambiguous_batch_code" for row in report["series"])


def test_batch_and_product_level_snapshots_remain_separate() -> None:
    report = _ledger([
        _snapshot("RUN-1", "P1", "S1", "2026-10-01", 10),
        _snapshot(
            "RUN-2", "P2", "S2", "2026-10-02", 18,
            batch_record_id=None, batch_code=None, expiry_date=None, manufacturing_date=None,
        ),
    ])

    assert report["summary"]["series_count"] == 2
    assert {row["inventory_level"] for row in report["series"]} == {"batch", "product"}


def test_future_and_invalid_rows_are_reported_and_excluded() -> None:
    rows = [
        _snapshot("RUN-1", "P1", "S1", "2026-10-01", 10),
        _snapshot("RUN-2", "P2", "S2", "2026-10-21", 12),
        _snapshot("RUN-3", "P3", "S3", "2026-10-02", -1),
    ]
    report = _ledger(rows)
    assert report["summary"]["eligible_snapshot_count"] == 1
    assert report["summary"]["future_snapshot_count"] == 1
    assert report["summary"]["invalid_snapshot_count"] == 1


def test_observations_from_another_organization_are_excluded() -> None:
    report = _ledger([
        _snapshot("RUN-1", "P1", "S1", "2026-10-01", 10, organization_id="ORG-OTHER"),
    ])
    assert report["status"] == "insufficient_data"
    assert report["series"] == []
    assert report["summary"]["invalid_snapshot_count"] == 1
