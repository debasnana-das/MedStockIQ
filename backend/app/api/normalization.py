"""Stateless API endpoint for canonical normalization."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import ValidationError

from app.ingestion.readers import read_tabular_content
from app.normalization.normalizer import NormalizationOptions, normalize_dataframe
from app.schema.confirmation import SchemaConfirmationRequest

router = APIRouter(prefix="/api/v1", tags=["canonical normalization"])
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_PREVIEW_ROWS = 10
MAX_ISSUE_PREVIEW = 50


@router.post("/normalize")
async def normalize_uploaded_file(
    file: UploadFile = File(...),
    confirmed_schema_json: str = Form(...),
    options_json: str = Form(default="{}"),
) -> dict[str, Any]:
    """Normalize a CSV/XLSX upload using an explicitly confirmed schema.

    The file and normalized output are not persisted. The response contains full
    entity counts plus limited previews and data-quality issues.
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
    result["note"] = (
        "The core normalizer returns full canonical tables for programmatic use. "
        "This upload endpoint returns limited previews only; nothing is persisted."
    )
    return result
