"""El consentimiento guarda QUE version se acepto, no solo cuando.

2026-09-25, PV-09 y L1 (O-3, O-4). ``terms_accepted_at`` sola no prueba que
texto rigio: la tienda y el cliente pueden discutir que terminos y que
politica de privacidad se mostraron. Ahora:

- ``GET /public/legal/versions`` expone las versiones vigentes (settings).
- La reserva publica manda ``terms_version`` y ``privacy_version``; si las
  manda, tienen que ser las vigentes (409 ``LEGAL_VERSION_MISMATCH``: el front
  vuelve a pedirlas y a mostrar la casilla) y quedan en el turno junto a
  ``terms_accepted_at``. Sin ellas la reserva sigue funcionando (el front
  actual todavia no las manda) y no se inventa una version.
- La lista de espera acepta ``accepts_terms`` y las versiones y las guarda.
  Solo las EXIGE con ``LEGAL_WAITLIST_CONSENT_REQUIRED`` (apagado hasta que el
  front tenga la casilla); un ``false`` explicito siempre es 422.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from modules.appointments.model import Appointment
from modules.waitlist.model import WaitlistEntry
from tests.integration.test_lista_de_espera import _alta, _tienda

VIGENTES = {"terms_version": "2026-09-25", "privacy_version": "2026-09-25"}


def _reserva(
    store: str, service: str, staff: str, slot: datetime, key: str, **extra: Any
) -> dict[str, Any]:
    cuerpo: dict[str, Any] = {
        "store_public_id": store,
        "service_id": service,
        "staff_id": staff,
        "starts_at": slot.isoformat(),
        "client_name": "Clara Consentimiento",
        "client_phone": "+5491155557001",
        "accepts_terms": True,
        "idempotency_key": key,
    }
    cuerpo.update(extra)
    return cuerpo


async def _turno(session: AsyncSession, public_id: str) -> Appointment:
    session.expire_all()
    return (
        await session.execute(select(Appointment).where(Appointment.id == public_id))
    ).scalar_one()


async def _entrada(session: AsyncSession, public_id: str) -> WaitlistEntry:
    session.expire_all()
    return (
        await session.execute(
            select(WaitlistEntry).where(WaitlistEntry.id == public_id)
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_las_versiones_vigentes_son_publicas_y_salen_de_settings(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    res = await client.get("/public/legal/versions")
    assert res.status_code == 200, res.text
    assert res.json() == VIGENTES

    monkeypatch.setattr(settings, "LEGAL_TERMS_VERSION", "2027-01-01")
    res = await client.get("/public/legal/versions")
    assert res.json() == {
        "terms_version": "2027-01-01",
        "privacy_version": "2026-09-25",
    }


@pytest.mark.asyncio
async def test_la_reserva_publica_guarda_las_versiones_aceptadas(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    store, _token, service, staff, slot = await _tienda(client, "consent-reserva")

    res = await client.post(
        "/public/appointments",
        json=_reserva(store, service, staff, slot, "consent-reserva-1", **VIGENTES),
    )

    assert res.status_code == 201, res.text
    turno = await _turno(test_session, res.json()["public_id"])
    assert turno.terms_accepted_at is not None
    assert turno.terms_version == "2026-09-25"
    assert turno.privacy_version == "2026-09-25"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "versiones",
    [
        {"terms_version": "2020-01-01", "privacy_version": "2026-09-25"},
        {"terms_version": "2026-09-25", "privacy_version": "2020-01-01"},
        {"terms_version": "2026-09-25"},
    ],
)
async def test_una_version_vieja_o_incompleta_se_rechaza(
    client: AsyncClient, test_session: AsyncSession, versiones: dict[str, str]
) -> None:
    store, _token, service, staff, slot = await _tienda(
        client, f"consent-vieja-{len(versiones)}-{sorted(versiones.values())[0]}"
    )

    res = await client.post(
        "/public/appointments",
        json=_reserva(store, service, staff, slot, "consent-vieja-001", **versiones),
    )

    assert res.status_code == 409, res.text
    assert res.json()["error_code"] == "LEGAL_VERSION_MISMATCH"
    assert (await test_session.execute(select(Appointment))).first() is None


@pytest.mark.asyncio
async def test_sin_versiones_la_reserva_sigue_y_no_inventa_una(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    store, _token, service, staff, slot = await _tienda(client, "consent-sin")

    res = await client.post(
        "/public/appointments",
        json=_reserva(store, service, staff, slot, "consent-sin-0001"),
    )

    assert res.status_code == 201, res.text
    turno = await _turno(test_session, res.json()["public_id"])
    assert turno.terms_accepted_at is not None
    assert turno.terms_version is None and turno.privacy_version is None


@pytest.mark.asyncio
async def test_la_lista_de_espera_sin_casilla_sigue_funcionando_con_el_flag_apagado(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    assert settings.LEGAL_WAITLIST_CONSENT_REQUIRED is False
    store, _token, service, _staff, slot = await _tienda(client, "consent-espera-sin")

    res = await client.post("/public/waitlist", json=_alta(store, service, slot))

    assert res.status_code == 201, res.text
    entrada = await _entrada(test_session, res.json()["public_id"])
    assert entrada.terms_accepted_at is None
    assert entrada.terms_version is None and entrada.privacy_version is None


@pytest.mark.asyncio
async def test_la_lista_de_espera_guarda_el_consentimiento(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    store, _token, service, _staff, slot = await _tienda(client, "consent-espera")

    res = await client.post(
        "/public/waitlist",
        json=_alta(store, service, slot, accepts_terms=True, **VIGENTES),
    )

    assert res.status_code == 201, res.text
    entrada = await _entrada(test_session, res.json()["public_id"])
    assert entrada.terms_accepted_at is not None
    assert entrada.terms_version == "2026-09-25"
    assert entrada.privacy_version == "2026-09-25"


@pytest.mark.asyncio
async def test_con_el_flag_la_lista_de_espera_exige_casilla_y_versiones(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "LEGAL_WAITLIST_CONSENT_REQUIRED", True)
    store, _token, service, _staff, slot = await _tienda(client, "consent-flag")

    sin_casilla = await client.post(
        "/public/waitlist", json=_alta(store, service, slot, **VIGENTES)
    )
    sin_versiones = await client.post(
        "/public/waitlist", json=_alta(store, service, slot, accepts_terms=True)
    )
    completo = await client.post(
        "/public/waitlist",
        json=_alta(store, service, slot, accepts_terms=True, **VIGENTES),
    )

    assert sin_casilla.status_code == 422, sin_casilla.text
    assert sin_versiones.status_code == 422, sin_versiones.text
    assert completo.status_code == 201, completo.text


@pytest.mark.asyncio
async def test_la_lista_de_espera_rechaza_un_no_explicito_y_una_version_vieja(
    client: AsyncClient,
) -> None:
    store, _token, service, _staff, slot = await _tienda(client, "consent-no")

    rechazo = await client.post(
        "/public/waitlist", json=_alta(store, service, slot, accepts_terms=False)
    )
    vieja = await client.post(
        "/public/waitlist",
        json=_alta(
            store,
            service,
            slot,
            accepts_terms=True,
            terms_version="2020-01-01",
            privacy_version="2026-09-25",
        ),
    )

    assert rechazo.status_code == 422, rechazo.text
    assert vieja.status_code == 409, vieja.text
    assert vieja.json()["error_code"] == "LEGAL_VERSION_MISMATCH"


def test_las_versiones_no_aceptan_cualquier_texto() -> None:
    from pydantic import ValidationError

    from modules.public_api.schemas import PublicBookingCreate

    base: dict[str, Any] = {
        "service_id": "svc",
        "starts_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        "client_name": "X",
        "client_phone": "5491155557001",
        "accepts_terms": True,
    }
    for malo in ("a" * 21, "2026 09 25", "v1\x00"):
        with pytest.raises(ValidationError):
            PublicBookingCreate.model_validate(
                {**base, "terms_version": malo, "privacy_version": "v1"}
            )
