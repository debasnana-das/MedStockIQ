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
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Copy the generated random value into `AUTH_TOKEN_SECRET` in `.env`, replacing the example placeholder. Keep `.env` private and never commit it. Authentication fails closed when this secret is missing, too short, or still contains the example placeholder.

Start PostgreSQL and create all database tables:

```powershell
docker compose up -d postgres
alembic upgrade head
uvicorn app.main:app --reload --app-dir backend
```

Open `http://127.0.0.1:8000/health`, `http://127.0.0.1:8000/health/database`, and `http://127.0.0.1:8000/docs`.

## Register, create an organization, and upload a file

Registration and login are public. All other `/api/v1` endpoints require a bearer access token. Passwords must be 12–128 characters; successful login/register responses contain an access token valid for 30 minutes.

```powershell
$account = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/v1/auth/register" -ContentType "application/json" -Body (@{email="you@example.com"; password="use-a-long-unique-password"} | ConvertTo-Json)
$headers = @{ Authorization = "Bearer $($account.access_token)" }
$org = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/v1/organizations" -Headers $headers -ContentType "application/json" -Body (@{display_name="Local Test Pharmacy"} | ConvertTo-Json)
$org.organization_id
curl.exe -H "Authorization: Bearer $($account.access_token)" -X POST "http://127.0.0.1:8000/api/v1/profile" -F "file=@sample.csv"
```

The account that creates an organization becomes its owner. To grant access, the invitee must register first; an owner or admin then calls `POST /api/v1/organizations/{organization_id}/members` with the invitee's email and a role (`admin`, `member`, or `viewer`). Admins can grant only `member` and `viewer`. Owners/admins can manage memberships; owners/admins/members can save normalization runs. Viewers cannot write. An account has no organization data access merely because it registered or knows an organization ID.

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

## Persistence and remaining security limits

Start PostgreSQL using `docker compose up -d postgres`; apply migrations with `alembic upgrade head`. Normalization remains preview-only unless the caller sets `persist=true` and selects an organization where they have a writer role. The server validates that membership. Saved previews are returned only after membership is verified; the organization query parameter alone grants no access. Original upload bytes are not stored by the normalization workflow.

This is a security baseline for controlled development, not a production-ready identity service. Rate limiting, MFA, account recovery, refresh tokens, dedicated secret management, detailed audit logging, HTTPS/proxy hardening, retention/deletion workflows, and a full security review remain outstanding. Use synthetic or sanitized data only and do not expose the prototype publicly.
