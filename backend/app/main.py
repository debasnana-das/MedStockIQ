"""FastAPI application entrypoint."""

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError

from app.api.auth import router as auth_router
from app.api.normalization import router as normalization_router
from app.api.profiling import router as profiling_router
from app.api.schema_confirmation import router as schema_confirmation_router
from app.db.session import DatabaseNotConfigured, check_database_connection

logger = logging.getLogger(__name__)

app = FastAPI(
    title="MedStockIQ API",
    description="API for schema-aware ingestion and inventory intelligence workflows.",
    version="0.2.0",
)

app.include_router(auth_router)
app.include_router(profiling_router)
app.include_router(schema_confirmation_router)
app.include_router(normalization_router)


@app.get("/health", tags=["system"])
def health_check() -> dict[str, str]:
    """Return process health only; use /health/database to verify database connectivity."""
    return {"status": "ok", "service": "medstockiq"}


@app.get("/health/database", tags=["system"])
def database_health_check() -> dict[str, str]:
    """Report database connectivity without leaking credentials."""
    try:
        check_database_connection()
    except DatabaseNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.exception("Database health check failed")
        raise HTTPException(status_code=503, detail="Database is not reachable.") from exc
    return {"status": "ok", "database": "reachable"}


# Serve the same-origin local workspace after API routes to avoid browser CORS setup.
_FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
if _FRONTEND_DIR.is_dir() and (_FRONTEND_DIR / "index.html").is_file():
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIR), html=True), name="frontend")
