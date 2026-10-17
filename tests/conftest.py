from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.security import AuthenticatedUser, get_current_principal


@pytest.fixture
def client():
    """Authenticated API client for endpoint behavior tests that do not test JWT itself."""
    original = app.dependency_overrides.get(get_current_principal)
    app.dependency_overrides[get_current_principal] = lambda: AuthenticatedUser(
        user_id="test-user-fixture",
        email="fixture@example.test",
    )
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        if original is None:
            app.dependency_overrides.pop(get_current_principal, None)
        else:
            app.dependency_overrides[get_current_principal] = original
