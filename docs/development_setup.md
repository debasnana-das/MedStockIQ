# Development setup

## Requirements

- Python 3.11 or newer
- Git
- Docker Desktop / Docker Engine for local PostgreSQL

## Create a local environment (Windows PowerShell)

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
Copy-Item .env.example .env
```

Start PostgreSQL and create tables before launching the API:

```powershell
docker compose up -d postgres
alembic upgrade head
uvicorn app.main:app --reload --app-dir backend
```

Open `http://127.0.0.1:8000/health`, `http://127.0.0.1:8000/health/database`, and `http://127.0.0.1:8000/docs`.

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

PostgreSQL persistence is opt-in on `POST /api/v1/normalize` via multipart form field `persist=true`. Preview is still the default. Include an explicit `organization_id` in `options_json`. Successful saves return `normalization_run_id`; retrieve a bounded preview at `GET /api/v1/normalization-runs/{run_id}?organization_id=...`. Each save is transactional; mappings, normalized records, quality issues, and transformation logs are stored, but original upload bytes are not.

The supplied organization ID is only a query filter, not an authenticated identity. Keep this prototype local and use synthetic/sanitized data until authentication and real tenant authorization exist.
