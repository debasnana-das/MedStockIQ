"""Demand aggregation and chronological baseline forecasting.

This deliberately small baseline is used to establish a reproducible benchmark before
any machine-learning model is introduced. Missing days are zero-filled only when
the user explicitly confirms the full, continuous reporting window.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from math import isfinite, sqrt
from typing import Any

ENGINE_VERSION = "1.0.0"
MIN_TRAIN_DAYS = 28
HOLDOUT_DAYS = 7
FORECAST_HORIZON_DAYS = 7
MAX_PRODUCT_SERIES = 100


def _date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value is None or value == "":
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if isfinite(result) else None


def _round(value: float | None) -> float | None:
    return round(value, 6) if value is not None and isfinite(value) else None


def _metrics(actual: list[float], predicted: list[float]) -> dict[str, float | None]:
    if not actual or len(actual) != len(predicted):
        return {"mae": None, "rmse": None, "wape_percent": None}
    errors = [prediction - observed for observed, prediction in zip(actual, predicted)]
    mae = sum(abs(error) for error in errors) / len(errors)
    rmse = sqrt(sum(error * error for error in errors) / len(errors))
    total_actual = sum(abs(value) for value in actual)
    wape = sum(abs(error) for error in errors) / total_actual * 100 if total_actual else None
    return {
        "mae": _round(mae),
        "rmse": _round(rmse),
        "wape_percent": _round(wape),
    }


def _blocked_report(
    blockers: list[str],
    *,
    start: date | None,
    end: date | None,
    transaction_count: int,
    valid_transaction_count: int,
    excluded_row_count: int = 0,
) -> dict[str, Any]:
    return {
        "engine_version": ENGINE_VERSION,
        "status": "insufficient_data",
        "coverage": {
            "complete_daily_history_confirmed": False,
            "start_date": start.isoformat() if start else None,
            "end_date": end.isoformat() if end else None,
            "transaction_row_count": transaction_count,
            "valid_retail_sale_row_count": valid_transaction_count,
            "excluded_retail_sale_row_count": excluded_row_count,
        },
        "series_count": 0,
        "series": [],
        "model_comparison": [],
        "selected_models": [],
        "forecasts": [],
        "blockers": blockers,
        "warnings": [],
        "evaluation": {
            "method": "chronological_holdout",
            "holdout_days": HOLDOUT_DAYS,
            "minimum_training_days": MIN_TRAIN_DAYS,
            "note": "No metric or forecast is produced when data coverage is not explicitly confirmed.",
        },
        "scope_note": (
            "This is a baseline benchmark, not a validated production forecast. "
            "It uses only confirmed dated retail-sale transactions."
        ),
    }


def evaluate_demand_baselines(
    normalization_result: dict[str, Any],
    *,
    complete_daily_history: bool = False,
    history_start_date: date | str | None = None,
    history_end_date: date | str | None = None,
) -> dict[str, Any]:
    """Compare naïve-last-value and seasonal-naïve-7-day baselines on a time holdout.

    Dates outside the explicitly declared report window are not silently clipped.
    One product with mixed units or invalid rows is excluded rather than converted
    by guessing. A final 7-calendar-day forecast is emitted after backtesting, with
    each baseline re-fit on the full declared history.
    """
    tables = normalization_result.get("tables") or {}
    products = {
        str(row.get("product_id")): row
        for row in (tables.get("products") or [])
        if row.get("product_id")
    }
    transactions = list(tables.get("transactions") or [])
    retail_rows = [
        row for row in transactions
        if str(row.get("transaction_type") or "").casefold() == "retail_sale"
    ]
    start = _date(history_start_date)
    end = _date(history_end_date)
    valid_rows: list[dict[str, Any]] = []
    excluded_reasons: dict[str, int] = defaultdict(int)

    for row in retail_rows:
        row_date = _date(row.get("transaction_date"))
        quantity = _number(row.get("effective_quantity"))
        if quantity is None and row.get("free_quantity") is None:
            quantity = _number(row.get("quantity"))
        unit = str(row.get("quantity_unit") or "").strip()
        product_id = str(row.get("product_id") or "").strip()
        if not product_id:
            excluded_reasons["missing_product_id"] += 1
            continue
        if row_date is None:
            excluded_reasons["missing_transaction_date"] += 1
            continue
        if quantity is None:
            excluded_reasons["invalid_or_ambiguous_quantity"] += 1
            continue
        if quantity < 0:
            excluded_reasons["negative_sale_quantity"] += 1
            continue
        if not unit:
            excluded_reasons["missing_quantity_unit"] += 1
            continue
        valid_rows.append({
            "product_id": product_id,
            "transaction_date": row_date,
            "quantity": quantity,
            "unit": unit,
        })

    blockers = []
    warnings = []
    if not complete_daily_history:
        blockers.append(
            "Confirm that the uploaded retail-sales export contains every sale and every no-sale day for a continuous date range before forecasting."
        )
    if start is None or end is None:
        blockers.append("Set sales_history_start_date and sales_history_end_date to the covered reporting period.")
    elif start > end:
        blockers.append("sales_history_start_date must be on or before sales_history_end_date.")
    if excluded_reasons:
        warnings.append(
            "Some retail-sale rows were excluded for missing or invalid product, date, quantity, or unit data."
        )
    if start and end and start <= end:
        outside = [row for row in valid_rows if not (start <= row["transaction_date"] <= end)]
        if outside:
            blockers.append(
                f"{len(outside)} valid retail-sale row(s) fall outside the declared reporting window; correct the coverage dates or source data."
            )
    else:
        outside = []

    if blockers:
        report = _blocked_report(
            blockers,
            start=start,
            end=end,
            transaction_count=len(retail_rows),
            valid_transaction_count=len(valid_rows),
            excluded_row_count=sum(excluded_reasons.values()),
        )
        report["warnings"] = warnings
        report["excluded_row_reasons"] = dict(sorted(excluded_reasons.items()))
        return report

    assert start is not None and end is not None
    days_in_window = (end - start).days + 1
    if days_in_window < MIN_TRAIN_DAYS + HOLDOUT_DAYS:
        blockers.append(
            f"Need at least {MIN_TRAIN_DAYS} training days plus {HOLDOUT_DAYS} chronological holdout days; declared window has {days_in_window} days."
        )
    if not valid_rows:
        blockers.append("No valid dated retail-sale transactions were found in the declared window.")
    if blockers:
        report = _blocked_report(
            blockers,
            start=start,
            end=end,
            transaction_count=len(retail_rows),
            valid_transaction_count=len(valid_rows),
            excluded_row_count=sum(excluded_reasons.values()),
        )
        report["coverage"]["complete_daily_history_confirmed"] = bool(complete_daily_history)
        report["coverage"]["days_in_window"] = days_in_window
        report["warnings"] = warnings
        report["excluded_row_reasons"] = dict(sorted(excluded_reasons.items()))
        return report

    # Build explicit daily series only after complete coverage/window boundaries are confirmed.
    by_product: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in valid_rows:
        by_product[row["product_id"]].append(row)
    window_dates = [start + timedelta(days=index) for index in range(days_in_window)]
    train_days = days_in_window - HOLDOUT_DAYS
    holdout_dates = window_dates[train_days:]
    model_aggregate: dict[str, dict[str, float]] = {
        "naive_last_value": {"abs_error": 0.0, "squared_error": 0.0, "actual_abs": 0.0, "count": 0},
        "seasonal_naive_7_day": {"abs_error": 0.0, "squared_error": 0.0, "actual_abs": 0.0, "count": 0},
    }
    series_reports = []
    forecasts = []
    excluded_products: list[dict[str, Any]] = []
    series_data = []

    for product_id, rows in sorted(by_product.items()):
        units = {row["unit"].casefold() for row in rows}
        unit_spelling = {row["unit"] for row in rows}
        if len(units) != 1:
            excluded_products.append({
                "product_id": product_id,
                "product_name": products.get(product_id, {}).get("product_name"),
                "reason": "Mixed quantity units across retail-sales rows; conversion is not inferred.",
                "row_count": len(rows),
                "units": sorted(unit_spelling),
            })
            continue
        daily_totals: dict[date, float] = defaultdict(float)
        for row in rows:
            daily_totals[row["transaction_date"]] += row["quantity"]
        daily_series = [daily_totals[day] for day in window_dates]
        train = daily_series[:train_days]
        holdout = daily_series[train_days:]
        if len(train) < MIN_TRAIN_DAYS:
            excluded_products.append({
                "product_id": product_id,
                "product_name": products.get(product_id, {}).get("product_name"),
                "reason": f"Only {len(train)} training days; need at least {MIN_TRAIN_DAYS}.",
                "row_count": len(rows),
                "units": sorted(unit_spelling),
            })
            continue

        last_value = train[-1]
        naive_predictions = [last_value for _ in holdout]
        seasonal_predictions = [
            daily_series[index - 7] for index in range(train_days, days_in_window)
        ]
        actuals = holdout
        naive_metrics = _metrics(actuals, naive_predictions)
        seasonal_metrics = _metrics(actuals, seasonal_predictions)

        for name, metrics, predictions in (
            ("naive_last_value", naive_metrics, naive_predictions),
            ("seasonal_naive_7_day", seasonal_metrics, seasonal_predictions),
        ):
            agg = model_aggregate[name]
            for actual, predicted in zip(actuals, predictions):
                error = predicted - actual
                agg["abs_error"] += abs(error)
                agg["squared_error"] += error * error
                agg["actual_abs"] += abs(actual)
                agg["count"] += 1

        candidates = [
            ("naive_last_value", naive_metrics),
            ("seasonal_naive_7_day", seasonal_metrics),
        ]
        selected_name, selected_metrics = min(
            candidates,
            key=lambda item: (
                float("inf") if item[1]["mae"] is None else item[1]["mae"],
                float("inf") if item[1]["rmse"] is None else item[1]["rmse"],
                item[0],
            ),
        )
        series_reports.append({
            "product_id": product_id,
            "product_name": products.get(product_id, {}).get("product_name"),
            "quantity_unit": next(iter(unit_spelling)),
            "report_start_date": start.isoformat(),
            "report_end_date": end.isoformat(),
            "calendar_days": days_in_window,
            "observed_retail_sale_rows": len(rows),
            "days_with_sales": sum(value > 0 for value in daily_series),
            "days_with_zero_sales": sum(value == 0 for value in daily_series),
            "total_units_sold": _round(sum(daily_series)),
            "average_daily_demand": _round(sum(daily_series) / len(daily_series)),
            "train_days": train_days,
            "holdout_days": HOLDOUT_DAYS,
            "holdout_start_date": holdout_dates[0].isoformat(),
            "holdout_end_date": holdout_dates[-1].isoformat(),
            "backtest": {
                "naive_last_value": {"metrics": naive_metrics},
                "seasonal_naive_7_day": {"metrics": seasonal_metrics},
                "daily_comparison": [
                    {
                        "date": day.isoformat(),
                        "actual": _round(actual),
                        "naive_last_value": _round(naive),
                        "seasonal_naive_7_day": _round(seasonal),
                    }
                    for day, actual, naive, seasonal in zip(
                        holdout_dates, actuals, naive_predictions, seasonal_predictions
                    )
                ],
            },
            "selected_baseline": selected_name,
            "selected_holdout_mae": selected_metrics["mae"],
        })
        series_data.append((product_id, daily_series, selected_name, selected_metrics, next(iter(unit_spelling))))

        future_dates = [end + timedelta(days=index) for index in range(1, FORECAST_HORIZON_DAYS + 1)]
        if selected_name == "seasonal_naive_7_day":
            future_values = daily_series[-7:]
        else:
            future_values = [daily_series[-1]] * FORECAST_HORIZON_DAYS
        forecasts.append({
            "product_id": product_id,
            "product_name": products.get(product_id, {}).get("product_name"),
            "quantity_unit": next(iter(unit_spelling)),
            "selected_baseline": selected_name,
            "trained_through_date": end.isoformat(),
            "forecast_horizon_days": FORECAST_HORIZON_DAYS,
            "daily_forecast": [
                {"date": day.isoformat(), "predicted_quantity": _round(value)}
                for day, value in zip(future_dates, future_values)
            ],
            "predicted_total_quantity": _round(sum(future_values)),
            "evaluation_mae": selected_metrics["mae"],
            "evaluation_rmse": selected_metrics["rmse"],
            "evaluation_wape_percent": selected_metrics["wape_percent"],
            "forecast_status": "baseline_only",
        })

    if not series_reports:
        blockers = ["No product had sufficient dated retail sales and a consistent quantity unit for baseline evaluation."]
        report = _blocked_report(
            blockers, start=start, end=end,
            transaction_count=len(retail_rows), valid_transaction_count=len(valid_rows),
            excluded_row_count=sum(excluded_reasons.values()),
        )
        report["coverage"]["complete_daily_history_confirmed"] = bool(complete_daily_history)
        report["coverage"]["days_in_window"] = days_in_window
        report["warnings"] = warnings
        report["excluded_products"] = excluded_products
        report["excluded_row_reasons"] = dict(sorted(excluded_reasons.items()))
        return report

    comparison = []
    for name, agg in model_aggregate.items():
        count = int(agg["count"])
        mae = agg["abs_error"] / count if count else None
        rmse = sqrt(agg["squared_error"] / count) if count else None
        wape = agg["abs_error"] / agg["actual_abs"] * 100 if count and agg["actual_abs"] else None
        comparison.append({
            "model": name,
            "holdout_observation_count": count,
            "mae": _round(mae),
            "rmse": _round(rmse),
            "wape_percent": _round(wape),
        })
    comparison.sort(key=lambda item: (
        float("inf") if item["mae"] is None else item["mae"], item["model"]
    ))

    if excluded_products:
        warnings.append("Some products were excluded from forecasting because of unit conflicts or inadequate training data.")
    return {
        "engine_version": ENGINE_VERSION,
        "status": "ready_with_warnings" if warnings or excluded_products else "ready",
        "coverage": {
            "complete_daily_history_confirmed": True,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "days_in_window": days_in_window,
            "transaction_row_count": len(retail_rows),
            "valid_retail_sale_row_count": len(valid_rows),
            "excluded_retail_sale_row_count": sum(excluded_reasons.values()),
            "products_with_forecasts": len(forecasts),
            "products_excluded": len(excluded_products),
        },
        "series_count": len(series_reports),
        "series": series_reports[:MAX_PRODUCT_SERIES],
        "series_truncated": len(series_reports) > MAX_PRODUCT_SERIES,
        "model_comparison": comparison,
        "selected_models": [
            {
                "product_id": item["product_id"],
                "product_name": item["product_name"],
                "model": item["selected_baseline"],
                "holdout_mae": item["selected_holdout_mae"],
            }
            for item in series_reports
        ],
        "forecasts": forecasts[:MAX_PRODUCT_SERIES],
        "forecasts_truncated": len(forecasts) > MAX_PRODUCT_SERIES,
        "excluded_products": excluded_products[:MAX_PRODUCT_SERIES],
        "excluded_row_reasons": dict(sorted(excluded_reasons.items())),
        "blockers": [],
        "warnings": warnings,
        "evaluation": {
            "method": "single chronological holdout; final 7 calendar days held out",
            "minimum_training_days": MIN_TRAIN_DAYS,
            "holdout_days": HOLDOUT_DAYS,
            "forecast_horizon_days": FORECAST_HORIZON_DAYS,
            "metrics": ["MAE", "RMSE", "WAPE"],
            "candidate_baselines": ["naive_last_value", "seasonal_naive_7_day"],
            "selection_rule": "Choose the lowest per-product holdout MAE; break ties by RMSE and model name.",
            "refit_rule": "After holdout evaluation, generate the next 7 days using the selected baseline refit to the full confirmed history.",
            "note": "A single holdout is a benchmark, not robust model validation. Compare against more rolling-origin windows before operational use.",
        },
        "scope_note": (
            "Baseline forecasts are derived only from confirmed dated retail-sale history. "
            "The declared complete period is zero-filled at daily frequency; if the source "
            "does not contain every sale/no-sale day for this window, these metrics and forecasts are invalid."
        ),
    }
