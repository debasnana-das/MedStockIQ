# Database persistence

- `models.py` defines run-scoped canonical entities, run metadata, issues, and transformation traces.
- `session.py` lazily configures SQLAlchemy from `DATABASE_URL`.
- `persistence.py` writes a complete normalization result in one transaction and returns bounded saved-run previews.
- `alembic/` contains versioned schema migrations; API startup does not create tables automatically.

Uploaded bytes are not stored. The organization filter is not authentication, so this integration is not ready for untrusted multi-tenant use.
