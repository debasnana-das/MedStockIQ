"""Demand aggregation with rolling-origin baseline evaluation.

Missing days are zero-filled only when the caller confirms complete daily coverage
for a continuous reporting window. Baseline selection uses expanding-window folds
that end before a separate, untouched final holdout.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from math import isfinite, sqrt
from typing import Any

ENGINE_VERSION = "1.1.0"
MIN_TRAIN_DAYS = 28
HOLDOUT_DAYS = 7
MIN_ROLLING_ORIGIN_WINDOWS = 2
MAX_ROLLING_ORIGIN_WINDOWS = 4
FORECAST_HORIZON_DAYS = 7
MAX_PRODUCT_SERIES = 100
MODEL_NAMES = ("naive_last_value", "seasonal_naive_7_day")


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
    complete_daily_history: bool = False,
    excluded_row_count: int = 0,
) -> dict[str, Any]:
    return {
        "engine_version": ENGINE_VERSION,
        "status": "insufficient_data",
        "coverage": {
            "complete_daily_history_confirmed": complete_daily_history,
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
            "method": "expanding_window_rolling_origin_with_untouched_final_holdout",
            "minimum_training_days": MIN_TRAIN_DAYS,
            "minimum_rolling_origin_windows": MIN_ROLLING_ORIGIN_WINDOWS,
            "rolling_origin_validation_days_per_window": HOLDOUT_DAYS,
            "final_holdout_days": HOLDOUT_DAYS,
            "note": "No metric or forecast is produced when coverage or history is insufficient.",
        },
        "scope_note": (
            "This is a baseline benchmark, not a validated production forecast. "
            "It uses only confirmed dated retail-sale transactions."
        ),
    }


def _macro_average(values: list[float | None]) -> float | None:
    defined = [value for value in values if value is not None]
    return _round(sum(defined) / len(defined)) if defined else None


def evaluate_demand_baselines(
    normalization_result: dict[str, Any],
    *,
    complete_daily_history: bool = False,
    history_start_date: date | str | None = None,
    history_end_date: date | str | None = None,
) -> dict[str, Any]:
    """Compare naive baselines on rolling-origin windows and an untouched final holdout.

    Rolling-origin windows use expanding training history and each predict the next
    seven days. Model selection is based only on aggregate rolling-origin MAE/RMSE;
    the final seven days are held out separately and do not drive baseline selection.
    The final seven-day forecast is then generated using the selected baseline refit
    to the full declared history.
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

    blockers: list[str] = []
    warnings: list[str] = []
    if not complete_daily_history:
        blockers.append(
            "Confirm that the uploaded retail-sales export contains every sale and every no-sale day for a continuous date range before forecasting."
        )
    if start is None or end is None:
        blockers.append("Set sales_history_start_date and sales_history_end_date to the covered reporting period.")
    elif start > end:
        blockers.append("sales_history_start_date must be on or before sales_history_end_date.")
    if excluded_reasons:
        excluded_total = sum(excluded_reasons.values())
        blockers.append(
            f"{excluded_total} retail-sale row(s) have missing or invalid product, date, quantity, or unit data; resolve these rows before forecasting."
        )

    outside = []
    if start and end and start <= end:
        outside = [row for row in valid_rows if not (start <= row["transaction_date"] <= end)]
        if outside:
            blockers.append(
                f"{len(outside)} valid retail-sale row(s) fall outside the declared reporting window; correct the coverage dates or source data."
            )

    if blockers:
        report = _blocked_report(
            blockers,
            start=start,
            end=end,
            transaction_count=len(retail_rows),
            valid_transaction_count=len(valid_rows),
            complete_daily_history=complete_daily_history,
            excluded_row_count=sum(excluded_reasons.values()),
        )
        report["warnings"] = warnings
        report["excluded_row_reasons"] = dict(sorted(excluded_reasons.items()))
        return report

    assert start is not None and end is not None
    days_in_window = (end - start).days + 1
    available_rolling_days = days_in_window - MIN_TRAIN_DAYS - HOLDOUT_DAYS
    rolling_window_count = min(
        MAX_ROLLING_ORIGIN_WINDOWS,
        available_rolling_days // HOLDOUT_DAYS,
    )
    minimum_days = (
        MIN_TRAIN_DAYS
        + MIN_ROLLING_ORIGIN_WINDOWS * HOLDOUT_DAYS
        + HOLDOUT_DAYS
    )
    if days_in_window < minimum_days or rolling_window_count < MIN_ROLLING_ORIGIN_WINDOWS:
        blockers.append(
            f"Need at least {minimum_days} calendar days: {MIN_TRAIN_DAYS} initial training days, "
            f"{MIN_ROLLING_ORIGIN_WINDOWS} rolling-origin windows of {HOLDOUT_DAYS} days, "
            f"and a separate {HOLDOUT_DAYS}-day final holdout; declared window has {days_in_window} days."
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
            complete_daily_history=complete_daily_history,
            excluded_row_count=sum(excluded_reasons.values()),
        )
        report["coverage"]["days_in_window"] = days_in_window
        report["coverage"]["rolling_origin_window_count"] = rolling_window_count
        report["warnings"] = warnings
        report["excluded_row_reasons"] = dict(sorted(excluded_reasons.items()))
        return report

    # Daily zero-filling is safe only after explicit complete-history confirmation.
    by_product: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in valid_rows:
        by_product[row["product_id"]].append(row)
    window_dates = [start + timedelta(days=index) for index in range(days_in_window)]
    final_train_days = days_in_window - HOLDOUT_DAYS
    final_holdout_dates = window_dates[final_train_days:]
    first_origin = days_in_window - HOLDOUT_DAYS - rolling_window_count * HOLDOUT_DAYS

    series_reports: list[dict[str, Any]] = []
    forecasts: list[dict[str, Any]] = []
    excluded_products: list[dict[str, Any]] = []
    eligible_metrics: dict[str, list[dict[str, float | None]]] = {
        name: [] for name in MODEL_NAMES
    }
    total_rolling_folds = 0

    for product_id, rows in sorted(by_product.items()):
        units = {row["unit"].casefold() for row in rows}
        unit_spellings = {row["unit"] for row in rows}
        if len(units) != 1:
            excluded_products.append({
                "product_id": product_id,
                "product_name": products.get(product_id, {}).get("product_name"),
                "reason": "Mixed quantity units across retail-sales rows; conversion is not inferred.",
                "row_count": len(rows),
                "units": sorted(unit_spellings),
            })
            continue

        daily_totals: dict[date, float] = defaultdict(float)
        for row in rows:
            daily_totals[row["transaction_date"]] += row["quantity"]
        daily_series = [daily_totals[day] for day in window_dates]
        rolling_actuals: dict[str, list[float]] = {name: [] for name in MODEL_NAMES}
        rolling_predictions: dict[str, list[float]] = {name: [] for name in MODEL_NAMES}
        rolling_windows = []

        for window_index in range(rolling_window_count):
            origin = first_origin + window_index * HOLDOUT_DAYS
            validation_end = origin + HOLDOUT_DAYS
            train = daily_series[:origin]
            actual = daily_series[origin:validation_end]
            naive_predictions = [train[-1]] * HOLDOUT_DAYS
            seasonal_predictions = [
                daily_series[index - 7] for index in range(origin, validation_end)
            ]
            naive_metrics = _metrics(actual, naive_predictions)
            seasonal_metrics = _metrics(actual, seasonal_predictions)
            rolling_actuals["naive_last_value"].extend(actual)
            rolling_actuals["seasonal_naive_7_day"].extend(actual)
            rolling_predictions["naive_last_value"].extend(naive_predictions)
            rolling_predictions["seasonal_naive_7_day"].extend(seasonal_predictions)
            rolling_windows.append({
                "window": window_index + 1,
                "train_start_date": start.isoformat(),
                "train_end_date": window_dates[origin - 1].isoformat(),
                "training_days": origin,
                "validation_start_date": window_dates[origin].isoformat(),
                "validation_end_date": window_dates[validation_end - 1].isoformat(),
                "validation_days": HOLDOUT_DAYS,
                "naive_last_value": {"metrics": naive_metrics},
                "seasonal_naive_7_day": {"metrics": seasonal_metrics},
            })

        rolling_metrics = {
            name: _metrics(rolling_actuals[name], rolling_predictions[name])
            for name in MODEL_NAMES
        }
        for name in MODEL_NAMES:
            eligible_metrics[name].append(rolling_metrics[name])
        total_rolling_folds += rolling_window_count

        selected_name = min(
            MODEL_NAMES,
            key=lambda name: (
                float("inf") if rolling_metrics[name]["mae"] is None else rolling_metrics[name]["mae"],
                float("inf") if rolling_metrics[name]["rmse"] is None else rolling_metrics[name]["rmse"],
                name,
            ),
        )

        # Final holdout is intentionally not included in rolling-origin model selection.
        final_train = daily_series[:final_train_days]
        final_actual = daily_series[final_train_days:]
        final_naive = [final_train[-1]] * HOLDOUT_DAYS
        final_seasonal = [
            daily_series[index - 7] for index in range(final_train_days, days_in_window)
        ]
        final_metrics = {
            "naive_last_value": _metrics(final_actual, final_naive),
            "seasonal_naive_7_day": _metrics(final_actual, final_seasonal),
        }
        selected_holdout_metrics = final_metrics[selected_name]
        series_reports.append({
            "product_id": product_id,
            "product_name": products.get(product_id, {}).get("product_name"),
            "quantity_unit": next(iter(unit_spellings)),
            "report_start_date": start.isoformat(),
            "report_end_date": end.isoformat(),
            "calendar_days": days_in_window,
            "observed_retail_sale_rows": len(rows),
            "days_with_sales": sum(value > 0 for value in daily_series),
            "days_with_zero_sales": sum(value == 0 for value in daily_series),
            "total_units_sold": _round(sum(daily_series)),
            "average_daily_demand": _round(sum(daily_series) / len(daily_series)),
            "backtest": {
                "train_days": final_train_days,
                "holdout_days": HOLDOUT_DAYS,
                "holdout_start_date": final_holdout_dates[0].isoformat(),
                "holdout_end_date": final_holdout_dates[-1].isoformat(),
                "selected_baseline": selected_name,
                "selected_baseline_metrics": selected_holdout_metrics,
                "naive_last_value": {"metrics": final_metrics["naive_last_value"]},
                "seasonal_naive_7_day": {"metrics": final_metrics["seasonal_naive_7_day"]},
                "daily_comparison": [
                    {
                        "date": day.isoformat(),
                        "actual": _round(actual),
                        "naive_last_value": _round(naive),
                        "seasonal_naive_7_day": _round(seasonal),
                    }
                    for day, actual, naive, seasonal in zip(
                        final_holdout_dates, final_actual, final_naive, final_seasonal
                    )
                ],
            },
            "rolling_origin_evaluation": {
                "window_count": rolling_window_count,
                "window_length_days": HOLDOUT_DAYS,
                "selection_metrics": rolling_metrics,
                "windows": rolling_windows,
                "selected_baseline": selected_name,
            },
            # Retain this field, but make explicit that selection is based on the rolling-origin
            # folds rather than the final holdout score.
            "selected_baseline": selected_name,
            "selected_holdout_mae": selected_holdout_metrics["mae"],
        })

        future_dates = [
            end + timedelta(days=index) for index in range(1, FORECAST_HORIZON_DAYS + 1)
        ]
        future_values = (
            daily_series[-7:]
            if selected_name == "seasonal_naive_7_day"
            else [daily_series[-1]] * FORECAST_HORIZON_DAYS
        )
        selected_rolling_metrics = rolling_metrics[selected_name]
        forecasts.append({
            "product_id": product_id,
            "product_name": products.get(product_id, {}).get("product_name"),
            "quantity_unit": next(iter(unit_spellings)),
            "selected_baseline": selected_name,
            "trained_through_date": end.isoformat(),
            "forecast_horizon_days": FORECAST_HORIZON_DAYS,
            "daily_forecast": [
                {"date": day.isoformat(), "predicted_quantity": _round(value)}
                for day, value in zip(future_dates, future_values)
            ],
            "predicted_total_quantity": _round(sum(future_values)),
            "rolling_origin_mae": selected_rolling_metrics["mae"],
            "rolling_origin_rmse": selected_rolling_metrics["rmse"],
            "rolling_origin_wape_percent": selected_rolling_metrics["wape_percent"],
            "final_holdout_mae": selected_holdout_metrics["mae"],
            "final_holdout_rmse": selected_holdout_metrics["rmse"],
            "final_holdout_wape_percent": selected_holdout_metrics["wape_percent"],
            "forecast_status": "baseline_only",
        })

    if not series_reports:
        blockers = ["No product had sufficient dated retail sales and a consistent quantity unit for baseline evaluation."]
        report = _blocked_report(
            blockers, start=start, end=end,
            transaction_count=len(retail_rows), valid_transaction_count=len(valid_rows),
            complete_daily_history=complete_daily_history,
            excluded_row_count=sum(excluded_reasons.values()),
        )
        report["coverage"]["days_in_window"] = days_in_window
        report["coverage"]["rolling_origin_window_count"] = rolling_window_count
        report["warnings"] = warnings
        report["excluded_products"] = excluded_products
        report["excluded_row_reasons"] = dict(sorted(excluded_reasons.items()))
        return report

    model_comparison = []
    for name in MODEL_NAMES:
        series_model_metrics = eligible_metrics[name]
        model_comparison.append({
            "model": name,
            "evaluated_series_count": len(series_model_metrics),
            "rolling_origin_window_count": total_rolling_folds,
            "metric_aggregation": "macro-average of per-product rolling-origin metrics; products with different units/scales are not pooled",
            "mae": _macro_average([metric["mae"] for metric in series_model_metrics]),
            "rmse": _macro_average([metric["rmse"] for metric in series_model_metrics]),
            "wape_percent": _macro_average([metric["wape_percent"] for metric in series_model_metrics]),
        })
    model_comparison.sort(key=lambda item: (
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
        "model_comparison": model_comparison,
        "selected_models": [
            {
                "product_id": item["product_id"],
                "product_name": item["product_name"],
                "model": item["selected_baseline"],
                "rolling_origin_mae": item["rolling_origin_evaluation"]["selection_metrics"][item["selected_baseline"]]["mae"],
                "final_holdout_mae": item["selected_holdout_mae"],
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
            "method": "expanding-window rolling-origin backtests followed by an untouched final 7-day holdout",
            "minimum_training_days": MIN_TRAIN_DAYS,
            "minimum_rolling_origin_windows": MIN_ROLLING_ORIGIN_WINDOWS,
            "rolling_origin_validation_days_per_window": HOLDOUT_DAYS,
            "rolling_origin_window_count": rolling_window_count,
            "final_holdout_days": HOLDOUT_DAYS,
            "forecast_horizon_days": FORECAST_HORIZON_DAYS,
            "metrics": ["MAE", "RMSE", "WAPE"],
            "candidate_baselines": list(MODEL_NAMES),
            "selection_rule": "Select each product's baseline using aggregate rolling-origin MAE; break ties by RMSE and model name. The final holdout does not affect selection.",
            "final_holdout_rule": "The final seven history days are evaluated separately after baseline selection.",
            "refit_rule": "After evaluation, generate the next seven days using the selected baseline refit to the full confirmed history.",
            "aggregate_metric_rule": "Top-level model metrics are macro-averages of per-product rolling-origin metrics, not pooled quantities across unlike units.",
            "note": "Rolling-origin testing is stronger than a single split but does not establish operational accuracy. Use verified authorized sales data and continue monitoring forecast errors.",
        },
        "scope_note": (
            "Baseline forecasts are derived only from confirmed dated retail-sale history. "
            "The declared complete period is zero-filled at daily frequency; if the source "
            "does not contain every sale/no-sale day for this window, metrics and forecasts are invalid."
        ),
    }
