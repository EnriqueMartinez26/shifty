"""Los validadores publicos de fecha comparan instantes en UTC (regla 24).

B1-11 (2026-09-18): ``PublicBookingCreate.starts_at`` y
``ClientRescheduleRequest.new_starts_at`` hacian
``datetime.now(value.tzinfo) if value.tzinfo else datetime.now()``: con un
payload sin offset, "no agendar en el pasado" se comparaba contra la hora
LOCAL del proceso. En un host con zona argentina (UTC-3) un instante de hace
una hora en UTC pasaba como futuro, y despues el router lo reinterpretaba
como UTC. Hoy los contenedores corren en UTC y por eso no se veia; la regla
existe para que la correccion no dependa de eso.

El reloj del sistema se fija en hora argentina con un doble de ``datetime``
para que el test sea determinista en cualquier host.
"""

from datetime import datetime, timedelta, timezone, tzinfo

import pytest
from pydantic import ValidationError

import modules.public_api.schemas as public_schemas
from core.utils import ARGENTINA_TZ
from modules.public_api.schemas import ClientRescheduleRequest, PublicBookingCreate


class _RelojDeHostEnArgentina(datetime):
    """``datetime.now()`` sin zona devuelve la hora de un host en UTC-3."""

    @classmethod
    def now(cls, tz: tzinfo | None = None) -> "_RelojDeHostEnArgentina":
        real = datetime.now(timezone.utc)
        local = (
            real.astimezone(ARGENTINA_TZ).replace(tzinfo=None)
            if tz is None
            else real.astimezone(tz)
        )
        return cls.fromisoformat(local.isoformat())


@pytest.fixture
def host_en_argentina(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(public_schemas, "datetime", _RelojDeHostEnArgentina)


def _hace_una_hora_utc_sin_offset() -> datetime:
    return (datetime.now(timezone.utc) - timedelta(hours=1)).replace(tzinfo=None)


def _en_una_hora_utc_sin_offset() -> datetime:
    return (datetime.now(timezone.utc) + timedelta(hours=1)).replace(tzinfo=None)


def _reserva(starts_at: datetime) -> PublicBookingCreate:
    return PublicBookingCreate.model_validate(
        {
            "service_id": "svc-demo-0001",
            "starts_at": starts_at,
            "client_name": "Cliente",
            "client_phone": "5491155550000",
            "accepts_terms": True,
        }
    )


def _reprogramacion(new_starts_at: datetime) -> ClientRescheduleRequest:
    return ClientRescheduleRequest(
        phone="5491155550000",
        new_starts_at=new_starts_at,
        idempotency_key="reprogramar-utc-0001",
    )


@pytest.mark.usefixtures("host_en_argentina")
def test_reserva_sin_offset_en_el_pasado_utc_se_rechaza() -> None:
    with pytest.raises(ValidationError, match="pasado"):
        _reserva(_hace_una_hora_utc_sin_offset())


@pytest.mark.usefixtures("host_en_argentina")
def test_reprogramacion_sin_offset_en_el_pasado_utc_se_rechaza() -> None:
    with pytest.raises(ValidationError, match="futuro"):
        _reprogramacion(_hace_una_hora_utc_sin_offset())


@pytest.mark.usefixtures("host_en_argentina")
def test_sin_offset_se_asume_utc_una_sola_vez_en_el_borde() -> None:
    """El instante sale del schema ya con zona UTC: el resto del camino no
    vuelve a adivinar (antes el repositorio hacia ``astimezone`` sobre un
    naive y Python asumia la zona del sistema)."""
    futuro = _en_una_hora_utc_sin_offset()

    reserva = _reserva(futuro)
    assert reserva.starts_at == futuro.replace(tzinfo=timezone.utc)
    assert reserva.starts_at.utcoffset() == timedelta(0)

    reprogramacion = _reprogramacion(futuro)
    assert reprogramacion.new_starts_at == futuro.replace(tzinfo=timezone.utc)
    assert reprogramacion.new_starts_at.utcoffset() == timedelta(0)


def test_con_offset_el_instante_no_cambia() -> None:
    en_argentina = (datetime.now(timezone.utc) + timedelta(hours=1)).astimezone(
        ARGENTINA_TZ
    )
    assert _reserva(en_argentina).starts_at == en_argentina
    assert _reprogramacion(en_argentina).new_starts_at == en_argentina
    with pytest.raises(ValidationError):
        _reserva(en_argentina - timedelta(hours=2))
