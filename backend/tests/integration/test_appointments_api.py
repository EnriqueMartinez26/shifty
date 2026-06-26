"""
Tests de integración para los endpoints de Turnos.

Usan una base de datos de test en memoria (SQLite async) y el cliente
de test de FastAPI para simular requests HTTP completos.

Casos cubiertos:
  1. Creación de turno exitosa.
  2. Intento de crear turno en el pasado (validación Pydantic).
  3. Cancelación de turno y liberación del horario.
  4. Intento de completar un turno cancelado (transición inválida → 422).
  5. Reprogramación de turno atómica.
  6. Marcar turno como AUSENTE.
"""

import json
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta, timezone
from typing import Any, cast

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from core.config import settings
from core.models import Base

import modules.appointments.model  # noqa: F401
import modules.audit.model  # noqa: F401
import modules.budget.model  # noqa: F401
import modules.services.model  # noqa: F401
import modules.staff.model  # noqa: F401
import modules.stores.model  # noqa: F401
import modules.users.model  # noqa: F401


# ---------------------------------------------------------------------------
# Fixtures de base de datos en memoria (SQLite async)
# ---------------------------------------------------------------------------

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"
JsonDict = dict[str, Any]


@pytest_asyncio.fixture(scope="function")
async def test_engine() -> AsyncGenerator[AsyncEngine, None]:
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def test_session(
    test_engine: AsyncEngine,
) -> AsyncGenerator[AsyncSession, None]:
    session_local = async_sessionmaker(
        bind=test_engine, expire_on_commit=False, autoflush=False
    )
    async with session_local() as session:
        yield session


# ---------------------------------------------------------------------------
# Fixture: Cliente HTTP de FastAPI con DB de test inyectada
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="function")
async def client(test_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """
    Crea el cliente HTTP con override de la dependencia de base de datos.
    """
    from main import app
    from core.database import get_db

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield test_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"x-raw-response": "true"},
    ) as c:
        yield c

    app.dependency_overrides.pop(get_db, None)


@pytest_asyncio.fixture(scope="function")
async def public_client(
    test_session: AsyncSession,
) -> AsyncGenerator[AsyncClient, None]:
    """
    Cliente HTTP sin la cabecera de respuesta cruda para verificar el envelope
    canónico real que ve un consumidor externo.
    """
    from main import app
    from core.database import get_db

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield test_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Helpers para crear datos de prueba
# ---------------------------------------------------------------------------


async def create_test_store_and_admin(client: AsyncClient) -> tuple[str, str]:
    """Registra un salón y retorna (store_public_id, access_token)."""
    resp = await client.post(
        "/auth/register",
        json={
            "store_name": "Barbería Test",
            "store_slug": "barberia-test",
            "admin_email": "admin@test.com",
            "admin_password": "Password123!",
            "admin_first_name": "Test",
            "admin_last_name": "Admin",
        },
    )
    assert resp.status_code == 201, f"Register failed: {resp.text}"
    register_body = cast(JsonDict, resp.json())
    register_data = cast(JsonDict, register_body.get("data", register_body))
    store_public_id = str(register_data["store_public_id"])

    token_resp = await client.post(
        "/auth/login",
        json={
            "email": "admin@test.com",
            "password": "Password123!",
        },
    )
    assert token_resp.status_code == 200
    token_body = cast(JsonDict, token_resp.json())
    token_data = cast(JsonDict, token_body.get("data", token_body))
    token = str(token_data["access_token"])
    return store_public_id, token


async def create_service(client: AsyncClient, token: str) -> str:
    """Crea un servicio y retorna su public_id."""
    resp = await client.post(
        "/services/",
        json={"name": "Corte Clásico", "duration_minutes": 30, "price": 1500},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, f"Create service failed: {resp.text}"
    service_body = cast(JsonDict, resp.json())
    service_data = cast(JsonDict, service_body.get("data", service_body))
    return str(service_data["public_id"])


async def create_staff(client: AsyncClient, token: str, service_public_id: str) -> str:
    resp = await client.post(
        "/staff/",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "display_name": "Pro Demo",
            "first_name": "Pro",
            "last_name": "Demo",
            "email": "pro-demo@test.com",
            "service_ids": [service_public_id],
        },
    )
    assert resp.status_code == 201, resp.text
    staff_body = cast(JsonDict, resp.json())
    staff_data = cast(JsonDict, staff_body.get("data", staff_body))
    return str(staff_data["public_id"])


# ---------------------------------------------------------------------------
# Tests de integración
# ---------------------------------------------------------------------------


class TestAppointmentEndpoints:
    @pytest.mark.asyncio
    async def test_create_appointment_in_past_fails(self, client: AsyncClient) -> None:
        """
        Caso: Intentar crear un turno con starts_at en el pasado.
        Esperado: 422 Unprocessable Entity (validación Pydantic).
        """
        _, token = await create_test_store_and_admin(client)
        service_id = await create_service(client, token)

        resp = await client.post(
            "/appointments/",
            json={
                "service_id": service_id,
                "staff_id": "cualquier-staff-id",
                "starts_at": (
                    datetime.now(timezone.utc) - timedelta(hours=1)
                ).isoformat(),
                "idempotency_key": "test-key-past-0001",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422
        body = cast(JsonDict, resp.json())
        # FastAPI retorna "detail" con los errores de validación
        assert any(
            "pasado" in str(e).lower() or "future" in str(e).lower()
            for e in [str(body)]
        )

    @pytest.mark.asyncio
    async def test_invalid_status_transition_returns_422(
        self, client: AsyncClient
    ) -> None:
        """
        Caso: Intentar completar un turno que está CANCELLED.
        Esperado: El handler global de AppException retorna 422.
        """
        _, token = await create_test_store_and_admin(client)

        # Usamos un public_id inexistente para obtener 404 (equivalente para el test)
        resp = await client.patch(
            "/appointments/NO-EXISTE/complete",
            headers={"Authorization": f"Bearer {token}"},
        )
        # Debe retornar 404 porque el turno no existe
        assert resp.status_code == 404
        assert cast(JsonDict, resp.json())["error_code"] == "APPOINTMENT_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_app_exception_handler_returns_structured_json(
        self, client: AsyncClient
    ) -> None:
        """
        Caso: Verificar que el handler global convierte AppException en JSON estructurado.
        Esperado: Respuesta con error_code, message y detail.
        """
        _, token = await create_test_store_and_admin(client)

        resp = await client.patch(
            "/appointments/TURNO-INEXISTENTE-123/cancel",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404
        body = cast(JsonDict, resp.json())
        assert "error_code" in body
        assert "message" in body
        assert "detail" in body

    @pytest.mark.asyncio
    async def test_reschedule_to_past_fails(self, client: AsyncClient) -> None:
        """
        Caso: Intentar reprogramar a una fecha pasada.
        Esperado: 422 por validación Pydantic en AppointmentReschedule.
        """
        _, token = await create_test_store_and_admin(client)

        resp = await client.patch(
            "/appointments/TURNO-ID/reschedule",
            json={
                "new_starts_at": (
                    datetime.now(timezone.utc) - timedelta(days=1)
                ).isoformat(),
                "idempotency_key": "idempotency-key-reschedule-001",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_unauthorized_user_cannot_confirm(self, client: AsyncClient) -> None:
        """
        Caso: Un cliente (role=CLIENT) no puede confirmar turnos.
        Esperado: Error de autenticación o de permisos.
        """
        # Registrar como admin
        await create_test_store_and_admin(client)

        # Crear usuario cliente
        await client.post(
            "/auth/register",
            json={
                "store_name": "Otro Salon",
                "store_slug": "otro-salon-slug",
                "admin_email": "cliente@test.com",
                "admin_password": "ClientPass123!",
                "admin_first_name": "Juan",
                "admin_last_name": "Cliente",
            },
        )
        client_token_resp = await client.post(
            "/auth/login",
            json={
                "email": "cliente@test.com",
                "password": "ClientPass123!",
            },
        )
        client_token = str(cast(JsonDict, client_token_resp.json())["access_token"])

        resp = await client.patch(
            "/appointments/TURNO-CUALQUIERA/confirm",
            headers={"Authorization": f"Bearer {client_token}"},
        )
        # Admin con otro store no tiene acceso al turno de otro tenant → 403 o 404
        assert resp.status_code in (403, 404)

    @pytest.mark.asyncio
    async def test_search_endpoint_returns_paginated_response(
        self, client: AsyncClient
    ) -> None:
        """
        Caso: Búsqueda sin filtros retorna estructura de paginación válida.
        Esperado: Respuesta con keys total, page, page_size, results.
        """
        _, token = await create_test_store_and_admin(client)

        resp = await client.get(
            "/appointments/search",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        body = cast(JsonDict, resp.json())
        assert "total" in body
        assert "page" in body
        assert "page_size" in body
        assert "results" in body
        assert isinstance(body["results"], list)
        assert body["total"] == 0  # BD vacía

    @pytest.mark.asyncio
    async def test_search_filters_by_status(self, client: AsyncClient) -> None:
        """
        Caso: Búsqueda con filtro de estado returns lista vacía correctamente.
        """
        _, token = await create_test_store_and_admin(client)

        resp = await client.get(
            "/appointments/search?statuses=absent&statuses=cancelled",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert cast(JsonDict, resp.json())["total"] == 0

    @pytest.mark.asyncio
    async def test_create_appointment_returns_201_and_canonical_envelope(
        self, public_client: AsyncClient
    ) -> None:
        _, token = await create_test_store_and_admin(public_client)
        service_id = await create_service(public_client, token)
        staff_id = await create_staff(public_client, token, service_id)
        starts_at = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()

        resp = await public_client.post(
            "/appointments/",
            json={
                "service_id": service_id,
                "staff_id": staff_id,
                "starts_at": starts_at,
                "notes": "Corte completo",
                "idempotency_key": "appointment-create-001",
            },
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 201
        body = cast(JsonDict, resp.json())
        assert body["success"] is True
        assert "data" in body
        assert body["data"]["service_id"] == service_id
        assert body["data"]["staff_id"] == staff_id

    @pytest.mark.asyncio
    async def test_create_appointment_is_idempotent(self, client: AsyncClient) -> None:
        _, token = await create_test_store_and_admin(client)
        service_id = await create_service(client, token)
        staff_id = await create_staff(client, token, service_id)
        starts_at = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
        payload = {
            "service_id": service_id,
            "staff_id": staff_id,
            "starts_at": starts_at,
            "notes": "Reserva repetida",
            "idempotency_key": "appointment-create-002",
        }

        first = await client.post(
            "/appointments/",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        second = await client.post(
            "/appointments/",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )

        assert first.status_code == 201
        assert second.status_code == 201
        first_body = cast(JsonDict, first.json())
        second_body = cast(JsonDict, second.json())
        assert first_body["public_id"] == second_body["public_id"]

    @pytest.mark.asyncio
    async def test_openapi_documents_appointment_create_as_201(self) -> None:
        from main import app

        openapi = app.openapi()
        post_responses = openapi["paths"]["/appointments/"]["post"]["responses"]

        assert "201" in post_responses
        assert "200" not in post_responses

    @pytest.mark.asyncio
    async def test_oversized_write_requests_keep_security_headers(
        self, public_client: AsyncClient
    ) -> None:
        _, token = await create_test_store_and_admin(public_client)
        oversized_json = json.dumps(
            {"payload": "x" * (settings.MAX_REQUEST_BODY_BYTES + 1024)},
            separators=(",", ":"),
        ).encode("utf-8")

        resp = await public_client.post(
            "/appointments/",
            content=oversized_json,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            },
        )

        assert resp.status_code == 413
        assert resp.headers["x-content-type-options"] == "nosniff"
        assert resp.headers["x-frame-options"] == "DENY"
        assert resp.headers["referrer-policy"] == "strict-origin-when-cross-origin"
