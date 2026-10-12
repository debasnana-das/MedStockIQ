# Development setup

## Requirements

- Python 3.11 or newer
- Git
- Docker Desktop / Docker Engine for local PostgreSQL (optional until DB code is added)

## Create a local environment (Windows PowerShell)

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
uvicorn app.main:app --reload --app-dir backend
```

Open `http://127.0.0.1:8000/health` to check the API scaffold and `http://127.0.0.1:8000/docs` for the OpenAPI UI.

## Tests

```powershell
pytest
```

## Database

```powershell
docker compose up -d postgres
```

The PostgreSQL service is provided for local development. Do not put real business data or production credentials in this repository. The API health route currently checks process health only; database connectivity checks will be added when persistence is implemented.
