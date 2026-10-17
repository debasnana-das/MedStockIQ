from __future__ import annotations

from datetime import date, timedelta

from app.quality.readiness import evaluate_data_quality_and_readiness


def _result(*, sales: int = 0, days: int = 0, same_units: bool = True) -> dict:
    products = [{"product_id": "PRODUCT-000001", "product_name": "Synthetic Medicine",
                 "source_product_code": "SYN-001", "product_match_status": "source_code"}]
    batches = [{"batch_record_id": "BATCH-000001", "product_id": "PRODUCT-000001",
                "batch_code": "B001", "expiry_date": "2027-06-30"}]
    snapshots = [{"snapshot_id": "SNAPSHOT-000001", "product_id": "PRODUCT-000001",
                  "batch_record_id": "BATCH-000001", "snapshot_date": "2026-10-15",
                  "quantity_on_hand": 20, "quantity_unit": "pack", "stock_basis": "unknown"}]
    transactions = []
    if sales:
        start = date(2026, 9, 1)
        for index in range(sales):
            offset = int(index * (max(days, 1) - 1) / max(sales - 1, 1))
            sale_date = start + timedelta(days=offset)
            transactions.append({
                "transaction_id": f"TRANSACTION-{index:08d}", "document_id": f"DOCUMENT-{index:06d}",
                "product_id": "PRODUCT-000001", "batch_record_id": "BATCH-000001",
                "transaction_date": sale_date.isoformat(), "transaction_type": "retail_sale",
                "quantity": 1, "quantity_unit": "pack" if same_units or index % 2 else "strip",
                "unit_rate": 10, "line_amount": 10, "line_total_amount": 10,
            })
    return {"input_row_count": sales, "tables": {
        "products": products, "batches": batches, "source_documents": [],
        "transactions": transactions, "inventory_snapshots": snapshots,
    }, "issues": [], "summary": {}}


def test_readiness_distinguishes_expiry_from_demand_evidence() -> None:
    report = evaluate_data_quality_and_readiness(_result(), document_type="purchase_invoice")
    modules = report["analysis_readiness"]
    assert modules["expiry_monitoring"]["status"] == "ready_with_warnings"
    assert modules["expiry_monitoring"]["available_inputs"]["expiry_and_stock_matched_batches"] == 1
    assert modules["demand_forecasting"]["status"] == "insufficient_data"
    assert modules["overstock_review"]["status"] == "insufficient_data"
    assert modules["stockout_review"]["status"] == "insufficient_data"
    assert report["overall_status"] == "ready_with_warnings"
    assert any(item["code"] == "unknown_stock_basis" for item in report["quality_findings"])


def test_sales_guardrails_and_matching_stock_make_demand_and_overstock_ready() -> None:
    report = evaluate_data_quality_and_readiness(_result(sales=14, days=35))
    modules = report["analysis_readiness"]
    assert modules["demand_forecasting"]["status"] == "ready"
    assert modules["overstock_review"]["status"] == "ready_with_warnings"
    assert modules["overstock_review"]["available_inputs"]["products_with_compatible_units"] == 1
    assert modules["stockout_review"]["status"] == "insufficient_data"
    assert any("replenishment" in text.lower() for text in modules["stockout_review"]["blockers"])


def test_mixed_quantity_units_block_demand_and_overstock() -> None:
    report = evaluate_data_quality_and_readiness(_result(sales=14, days=35, same_units=False))
    modules = report["analysis_readiness"]
    assert modules["demand_forecasting"]["status"] == "insufficient_data"
    assert any("multiple units" in text for text in modules["demand_forecasting"]["blockers"])
    assert modules["overstock_review"]["status"] == "insufficient_data"


def test_empty_input_is_insufficient_and_reports_errors() -> None:
    report = evaluate_data_quality_and_readiness({
        "input_row_count": 0, "tables": {}, "summary": {},
        "issues": [{"code": "missing_product_identity", "severity": "error", "row_index": 0,
                    "canonical_field": None, "message": "No product identity was supplied."}],
    })
    assert report["overall_status"] == "insufficient_data"
    assert report["quality_summary"]["error_finding_count"] == 1
    assert report["quality_findings"][0]["code"] == "missing_product_identity"


def test_duplicate_signature_warns_without_deduplicating() -> None:
    result = _result()
    row = {"document_id": "DOC-1", "product_id": "PRODUCT-000001",
           "batch_record_id": "BATCH-000001", "transaction_date": "2026-10-01",
           "transaction_type": "purchase_receipt", "quantity": 2, "quantity_unit": "pack",
           "unit_rate": 10, "line_amount": 20, "line_total_amount": 22}
    result["tables"]["transactions"] = [dict(row), dict(row)]
    report = evaluate_data_quality_and_readiness(result)
    finding = next(item for item in report["quality_findings"]
                   if item["code"] == "possible_duplicate_transaction_lines")
    assert finding["affected_count"] == 1
    assert finding["severity"] == "warning"
    assert len(result["tables"]["transactions"]) == 2


def test_ignored_columns_are_reported_as_information() -> None:
    report = evaluate_data_quality_and_readiness(
        _result(), confirmed_schema={"mappings": [{"source_column": "REMARKS", "action": "ignore"}]}
    )
    finding = next(item for item in report["quality_findings"]
                   if item["code"] == "source_columns_ignored")
    assert finding["severity"] == "info"
    assert finding["columns"] == ["REMARKS"]
