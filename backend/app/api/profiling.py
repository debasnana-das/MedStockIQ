"""Upload and profile CSV/XLSX files without persisting the upload."""

from __future__ import annotations

from pathlib import Path

from app.ingestion.readers import read_tabular_content
from app.schema.profiler import profile_dataframe
from fastapi import APIRouter, File, HTTPException, UploadFile


router = APIRouter(prefix="/api/v1", tags=["data profiling"])
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


@router.post("/profile")
async def profile_uploaded_file(file: UploadFile = File(...)) -> dict:  # noqa: B008
    """Profile a CSV/XLSX upload and suggest column mappings.

    This MVP keeps upload bytes in memory for the request and does not store them.
    It does not normalize data, persist records, or run risk predictions yet.
    """
    filename = Path(file.filename or "").name
    suffix = Path(filename).suffix.casefold()
    if suffix not in {".csv", ".xlsx"}:
        raise HTTPException(status_code=415, detail="Unsupported file type. Upload CSV or XLSX.")

    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds the 10 MB profiling limit.")
    if not content:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")

    try:
        frame, truncated = read_tabular_content(filename, content)
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail="Could not parse the file. Check its format and whether it has a valid header row.",
        ) from exc

    report = profile_dataframe(frame, truncated=truncated)
    return {
        "filename": filename,
        "format": suffix.removeprefix("."),
        "storage": "in_memory_not_persisted",
        **report,
    }
