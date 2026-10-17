from app.api.profiling import router as profiling_router
from app.api.schema_confirmation import router as schema_confirmation_router
from fastapi import FastAPI

app = FastAPI(
    title="MedStockIQ API",
    description="API scaffold for inventory intelligence workflows.",
    version="0.1.0",
)

app.include_router(profiling_router)
app.include_router(schema_confirmation_router)


@app.get("/health", tags=["system"])
def health_check() -> dict[str, str]:
    """Return lightweight process health; does not check database connectivity."""
    return {"status": "ok", "service": "medstockiq"}
