from __future__ import annotations

from datetime import date, timedelta

from app.forecasting.baseline import evaluate_demand_baselines


START = date(2026, 8, 1)


def _result(*, days: int = 42, pattern: str = "weekly", mixed_units: bool = False) -> dict:
    transactions = []
    for index in range(days):
        day = START + timedelta(days=index)
        quantity = (index % 7) + 1 if pattern == "weekly" else 5
        transactions.append({
            "transaction_id": f"T{index}",
            "product_id": "P1",
            "transaction_date": day.isoformat(),
            "transaction_type": "retail_sale",
            "quantity": quantity,
            "effective_quantity": quantity,
            "free_quantity": None,
            "quantity_unit": "strip" if mixed_units and index % 2 else "pack",
        })
    return {
        "tables": {
            "products": [{"product_id": "P1", "product_name": "Synthetic Medicine"}],
            "transactions": transactions,
        }
    }


def _evaluate(result: dict, *, complete: bool = True, start: date = START, days: int = 42):
    end = start + timedelta(days=days - 1)
    return evaluate_demand_baselines(
        result,
        complete_daily_history=complete,
        history_start_date=start,
        history_end_date=end,
    )


def test_missing_explicit_coverage_prevents_zero_fill_and_forecasts() -> None:
    report = _evaluate(_result(), complete=False)
    assert report["status"] == "insufficient_data"
    assert report["forecasts"] == []
    assert any("every sale" in blocker for blocker in report["blockers"])


def test_short_history_reports_insufficient_data() -> None:
    report = _evaluate(_result(days=30), days=30)
    assert report["status"] == "insufficient_data"
    assert report["forecasts"] == []
    assert any("28 training days plus 7" in blocker for blocker in report["blockers"])


def test_weekly_pattern_selects_seasonal_naive_and_forecasts_next_week() -> None:
    report = _evaluate(_result(days=42), days=42)
    assert report["status"] == "ready"
    assert report["series_count"] == 1
    series = report["series"][0]
    assert series["train_days"] == 35
    assert series["holdout_days"] == 7
    assert series["selected_baseline"] == "seasonal_naive_7_day"
    assert series["backtest"]["seasonal_naive_7_day"]["metrics"]["mae"] == 0.0
    forecast = report["forecasts"][0]
    assert forecast["forecast_status"] == "baseline_only"
    assert len(forecast["daily_forecast"]) == 7
    assert forecast["daily_forecast"][0]["date"] == (START + timedelta(days=42)).isoformat()
    assert forecast["predicted_total_quantity"] == sum(range(1, 8))


def test_constant_demand_selects_naive_and_holdout_predictions_do_not_use_holdout_actuals() -> None:
    result = _result(days=42, pattern="constant")
    first = _evaluate(result, days=42)
    # Change holdout actuals dramatically without changing training history.
    for row in result["tables"]["transactions"][-7:]:
        row["quantity"] = 100
        row["effective_quantity"] = 100
    second = _evaluate(result, days=42)

    assert first["series"][0]["selected_baseline"] == "naive_last_value"
    first_predictions = [
        item["naive_last_value"] for item in first["series"][0]["backtest"]["daily_comparison"]
    ]
    second_predictions = [
        item["naive_last_value"] for item in second["series"][0]["backtest"]["daily_comparison"]
    ]
    assert first_predictions == second_predictions == [5.0] * 7
    assert second["series"][0]["backtest"]["naive_last_value"]["metrics"]["mae"] > 0


def test_mixed_units_exclude_product_without_guessing_conversion() -> None:
    report = _evaluate(_result(days=42, mixed_units=True), days=42)
    assert report["status"] == "insufficient_data"
    assert report["forecasts"] == []
    assert report["excluded_products"][0]["product_id"] == "P1"
    assert "Mixed quantity units" in report["excluded_products"][0]["reason"]


def test_sales_outside_declared_window_blocks_report() -> None:
    result = _result(days=42)
    result["tables"]["transactions"].append({
        "transaction_id": "OUTSIDE", "product_id": "P1",
        "transaction_date": (START - timedelta(days=1)).isoformat(),
        "transaction_type": "retail_sale", "quantity": 1, "quantity_unit": "pack",
    })
    report = _evaluate(result, days=42)
    assert report["status"] == "insufficient_data"
    assert any("outside the declared reporting window" in blocker for blocker in report["blockers"])
