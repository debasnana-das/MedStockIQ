"""Upload, normalize, optionally persist, and review normalization runs."""

from __future__ import annotations

from datetime import date
import json
import logging
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.models import Organization, OrganizationMembership
from app.db.persistence import (
    get_persisted_inventory_history_observations,
    get_persisted_normalization_preview,
    get_persisted_overstock_sales_run,
    persist_normalization_result,
)
from app.db.session import get_db_session
from app.ingestion.readers import read_tabular_content
from app.forecasting.baseline import evaluate_demand_baselines
from app.inventory.arithmetic import calculate_inventory_arithmetic
from app.inventory.history import build_inventory_history_ledger
from app.inventory.overstock import evaluate_overstock_review
from app.normalization.normalizer import NormalizationOptions, normalize_dataframe
from app.quality.readiness import evaluate_data_quality_and_readiness
from app.schema.confirmation import SchemaConfirmationRequest
from app.security import AuthenticatedUser, get_current_principal

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["canonical normalization"])
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_PREVIEW_ROWS = 10
MAX_ISSUE_PREVIEW = 50
WRITER_ROLES = {"owner", "admin", "member"}


def _require_organization_access(
    session: Session,
    principal: AuthenticatedUser,
    organization_id: str,
    *,
    write: bool = False,
) -> OrganizationMembership:
    """Enforce tenant membership on the server; never trust a supplied ID alone."""
    organization = session.get(Organization, organization_id)
    membership = session.get(OrganizationMembership, (organization_id, principal.user_id))
    if organization is None or not organization.is_active or membership is None:
        # Hide whether an unrelated tenant exists.
        raise HTTPException(status_code=404, detail="Organization was not found.")
    if write and membership.role not in WRITER_ROLES:
        raise HTTPException(status_code=403, detail="Your organization role cannot save normalization runs.")
    return membership


@router.post("/normalize")
async def normalize_uploaded_file(
    file: UploadFile = File(...),
    confirmed_schema_json: str = Form(...),
    options_json: str = Form(default="{}"),
    persist: bool = Form(default=False),
    principal: AuthenticatedUser = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """Normalize confirmed mappings and save records only after tenant authorization.

    Upload bytes are held in memory for this request and are never stored as a file.
    Persisted records are assigned to an organization only after membership is verified.
    """
    filename = Path(file.filename or "").name
    suffix = Path(filename).suffix.casefold()
    if suffix not in {".csv", ".xlsx"}:
        raise HTTPException(status_code=415, detail="Unsupported file type. Upload CSV or XLSX.")

    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds the 10 MB normalization limit.")
    if not content:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")

    try:
        frame, truncated = read_tabular_content(filename, content)
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to parse uploaded tabular file")
        raise HTTPException(status_code=400, detail="Could not parse the uploaded file.") from exc

    if truncated:
        raise HTTPException(
            status_code=413,
            detail=(
                "The current normalizer refuses to process files at the 20,000-row profiling cap. "
                "Use a smaller file until full-file validation and pagination are implemented."
            ),
        )

    try:
        confirmed_schema = SchemaConfirmationRequest.model_validate_json(confirmed_schema_json)
        options = NormalizationOptions.model_validate_json(options_json)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=json.loads(exc.json())) from exc
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid JSON form field: {exc}") from exc

    organization_id = options.organization_id
    membership = None
    if organization_id != "ORG-UNSPECIFIED":
        membership = _require_organization_access(
            session, principal, organization_id, write=persist
        )
    if persist and organization_id == "ORG-UNSPECIFIED":
        raise HTTPException(
            status_code=422,
            detail="Set options_json.organization_id to an organization you belong to before persisting.",
        )
    if persist and (membership is None or membership.role not in WRITER_ROLES):
        raise HTTPException(status_code=403, detail="Your organization role cannot save normalization runs.")

    try:
        result = normalize_dataframe(
            frame=frame,
            confirmation=confirmed_schema,
            options=options,
            source_file_name=filename,
            source_format=suffix.removeprefix("."),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    result["quality_report"] = evaluate_data_quality_and_readiness(
        result,
        document_type=options.document_type,
        confirmed_schema=confirmed_schema,
    )
    result["quality_report"]["inventory_analysis"] = calculate_inventory_arithmetic(
        result,
        currency_code=options.currency_code,
    )
    result["quality_report"]["forecasting_baseline"] = evaluate_demand_baselines(
        result,
        complete_daily_history=options.sales_history_complete,
        history_start_date=options.sales_history_start_date,
        history_end_date=options.sales_history_end_date,
    )

    if persist:
        try:
            # Tenant authorization used this request session for SELECTs; close that
            # read transaction so the persistence service can own its atomic write.
            session.commit()
            run_id = persist_normalization_result(
                session=session,
                result=result,
                confirmed_schema=confirmed_schema,
                options=options,
                source_file_name=filename,
                source_format=suffix.removeprefix("."),
                source_file_bytes=len(content),
            )
        except SQLAlchemyError as exc:
            session.rollback()
            logger.exception("Could not persist normalization run")
            raise HTTPException(
                status_code=503,
                detail="Database persistence failed; no partial normalization run was saved.",
            ) from exc
        result["normalization_run_id"] = run_id
        result["persistence"] = "saved_to_postgresql"
        result["note"] = (
            "Normalized entities, confirmed mapping, quality/readiness findings, inventory arithmetic, "
            "expiry alerts and transformation traces were saved transactionally. Original upload bytes "
            "were not stored."
        )
    else:
        result["note"] = (
            "Preview only: nothing was saved. Set persist=true and select an organization role "
            "permitted to save this normalization run to persist the result."
        )

    preview_tables = {
        table_name: records[:MAX_PREVIEW_ROWS]
        for table_name, records in result.pop("tables").items()
    }
    all_issues = result.pop("issues")
    all_transformations = result.pop("transformations")
    result["previews"] = preview_tables
    result["issues_preview"] = all_issues[:MAX_ISSUE_PREVIEW]
    result["transformations_preview"] = all_transformations[:MAX_ISSUE_PREVIEW]
    result["issue_preview_truncated"] = len(all_issues) > MAX_ISSUE_PREVIEW
    result["transformation_preview_truncated"] = len(all_transformations) > MAX_ISSUE_PREVIEW
    return result


@router.get("/normalization-runs/{run_id}")
def get_normalization_run(
    run_id: UUID,
    organization_id: str = Query(..., min_length=1, max_length=100),
    principal: AuthenticatedUser = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """Return bounded previews only after verifying membership of the requested tenant."""
    _require_organization_access(session, principal, organization_id)

    try:
        result = get_persisted_normalization_preview(
            session=session,
            run_id=str(run_id),
            organization_id=organization_id,
            preview_limit=MAX_PREVIEW_ROWS,
            issue_limit=MAX_ISSUE_PREVIEW,
        )
    except SQLAlchemyError as exc:
        logger.exception("Could not retrieve normalization run")
        raise HTTPException(status_code=503, detail="Database query failed.") from exc

    if result is None:
        raise HTTPException(status_code=404, detail="Normalization run was not found.")
    return result



@router.get("/inventory-history")
def get_inventory_history(
    organization_id: str = Query(..., min_length=1, max_length=100),
    as_of_date: date | None = Query(default=None),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    principal: AuthenticatedUser = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """Build a read-only cross-upload snapshot timeline after tenant access checks."""
    _require_organization_access(session, principal, organization_id)
    effective_as_of = as_of_date or date.today()
    if end_date is not None and end_date > effective_as_of:
        raise HTTPException(status_code=422, detail="end_date must be on or before as_of_date.")
    if start_date is not None and start_date > effective_as_of:
        raise HTTPException(status_code=422, detail="start_date must be on or before as_of_date.")
    if start_date is not None and end_date is not None and start_date > end_date:
        raise HTTPException(status_code=422, detail="start_date must be on or before end_date.")

    try:
        observations, truncated = get_persisted_inventory_history_observations(
            session=session,
            organization_id=organization_id,
            as_of_date=effective_as_of,
            start_date=start_date,
            end_date=end_date,
            row_limit=20_000,
        )
    except SQLAlchemyError as exc:
        logger.exception("Could not query inventory history")
        raise HTTPException(status_code=503, detail="Inventory history query failed.") from exc

    if truncated:
        raise HTTPException(
            status_code=413,
            detail=(
                "More than 20,000 inventory snapshots match this query. Add a narrower "
                "start_date and/or end_date so the ledger can analyze a complete bounded window."
            ),
        )

    report = build_inventory_history_ledger(
        observations,
        organization_id=organization_id,
        as_of_date=effective_as_of,
    )
    report["coverage_window"] = {
        "start_date": start_date.isoformat() if start_date else None,
        "end_date": end_date.isoformat() if end_date else effective_as_of.isoformat(),
        "as_of_date": effective_as_of.isoformat(),
        "window_is_date_bounded": start_date is not None or end_date is not None,
    }
    return report



@router.get("/overstock-review")
def get_overstock_review(
    organization_id: str = Query(..., min_length=1, max_length=100),
    sales_run_id: UUID = Query(...),
    as_of_date: date | None = Query(default=None),
    target_days_of_supply: float | None = Query(default=None, ge=1, le=365),
    principal: AuthenticatedUser = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """Review stock against one confirmed saved retail-sales window."""
    _require_organization_access(session, principal, organization_id)
    effective_as_of = as_of_date or date.today()
    try:
        sales_run, sales_rows = get_persisted_overstock_sales_run(
            session=session,
            organization_id=organization_id,
            run_id=str(sales_run_id),
        )
        if sales_run is None:
            raise HTTPException(status_code=404, detail="Saved sales run was not found.")
        if sales_run["document_type"] != "retail_sales":
            raise HTTPException(
                status_code=422,
                detail="sales_run_id must identify a saved normalization run with document_type retail_sales.",
            )
        sales_options = sales_run["options"]
        inventory_rows, truncated = get_persisted_inventory_history_observations(
            session=session,
            organization_id=organization_id,
            as_of_date=effective_as_of,
            row_limit=20_000,
            document_type="inventory_report",
        )
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        logger.exception("Could not query saved data for overstock review")
        raise HTTPException(status_code=503, detail="Overstock review query failed.") from exc

    if truncated:
        raise HTTPException(
            status_code=413,
            detail="More than 20,000 saved inventory snapshots match this organization. Reduce the saved history before running overstock analysis.",
        )
    return evaluate_overstock_review(
        inventory_rows,
        sales_rows,
        sales_run_id=str(sales_run_id),
        organization_id=organization_id,
        as_of_date=effective_as_of,
        sales_history_complete=bool(sales_options.get("sales_history_complete", False)),
        sales_history_start_date=sales_options.get("sales_history_start_date"),
        sales_history_end_date=sales_options.get("sales_history_end_date"),
        target_days_of_supply=target_days_of_supply,
    )
