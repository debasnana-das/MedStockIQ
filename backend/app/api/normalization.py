"""Upload, normalize, optionally persist, and review normalization runs."""

from __future__ import annotations

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
from app.db.persistence import get_persisted_normalization_preview, persist_normalization_result
from app.db.session import get_db_session
from app.ingestion.readers import read_tabular_content
from app.normalization.normalizer import NormalizationOptions, normalize_dataframe
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

    if persist:
        try:
            run_id = persist_normalization_result(
                session=session,
                result=result,
                confirmed_schema=confirmed_schema,
                options=options,
                source_file_name=filename,
                source_format=suffix.removeprefix("."),
                source_file_bytes=len(content),
            )
            session.commit()
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
            "Normalized entities, confirmed mapping, summary, issues and transformation traces "
            "were saved transactionally. The original uploaded file bytes were not stored."
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
