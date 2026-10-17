# Development setup

## Requirements

- Python 3.11 or newer
- Git
- Docker Desktop / Docker Engine for local PostgreSQL (optional until database persistence is implemented)

## Create a local environment (Windows PowerShell)

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
uvicorn app.main:app --reload --app-dir backend
```

Open `http://127.0.0.1:8000/health` to check the API process and `http://127.0.0.1:8000/docs` for the interactive OpenAPI page.

## Try the file profiling endpoint

The first upload endpoint accepts CSV or XLSX up to 10 MB and profiles no more than 20,000 rows. It suggests mappings but does not normalize records, run inventory-risk calculations, store the file, or call an LLM.

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/v1/profile" -F "file=@sample.csv"
```

You can also upload a file from the `/docs` page. Use synthetic or sanitized data only during development; the current prototype has no authentication or tenant access controls and is not ready for public deployment with business-confidential files.

See [Profiling API](profiling_api.md) for response fields and current limitations.

## Generate synthetic data

From the repository root:

```powershell
python -m synthetic_data.generate_dataset --output-dir data/synthetic --seed 42
```

The output directory is git-ignored. Keep generated files local unless there is a specific reason to commit a small, reviewed, fully synthetic fixture. Never commit real business data.

## Tests

```powershell
pytest
ruff check .
```

## Database

```powershell
docker compose up -d postgres
```

The PostgreSQL service is provided for local development. The current API health route checks process health only; database connectivity and persistence will be added in a later phase.
