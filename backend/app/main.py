from fastapi import FastAPI

app = FastAPI(
    title="MedStockIQ API",
    description="API scaffold for inventory intelligence workflows.",
    version="0.1.0",
)


@app.get("/health", tags=["system"])
def health_check() -> dict[str, str]:
    """Return lightweight process health; does not check database connectivity."""
    return {"status": "ok", "service": "medstockiq"}
