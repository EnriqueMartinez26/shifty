"""El presupuesto por hora del OTP cuenta verificaciones, no solo fallos.

B4-09 (2026-09-18): ``verify_code`` consume el presupuesto ANTES de leer el
registro y comparar el codigo, asi que tambien lo gastan las verificaciones
exitosas. El comportamiento es el correcto (frena la fuerza bruta aun con
verificaciones en paralelo), pero el setting se llamaba
``OTP_MAX_FAILURES_PER_HOUR`` y el contador ``otp:fail:``: el nombre prometia
"10 fallos" y el limite real es "10 verificaciones por hora". Se renombra a
``OTP_MAX_VERIFY_ATTEMPTS_PER_HOUR`` / ``otp:verify:`` sin cambiar el
comportamiento, y el nombre viejo sigue aceptado como alias de entrada para
que un ``.env`` de produccion con el nombre viejo no se ignore en silencio.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import modules.notifications.tasks as tasks
import modules.otp.service as otp_service
from core.config import Settings, settings
from core.exceptions import OTPException, OTPRateLimitedException
from modules.otp.service import OtpService
from tests.unit.test_config_production_guards import BASE

TELEFONO = "+5491155550909"
TIENDA = "tienda-presupuesto-otp"


class _RedisContador:
    def __init__(self) -> None:
        self.valores: dict[str, int] = {}

    def pipeline(self) -> "_Pipeline":
        return _Pipeline(self)


class _Pipeline:
    def __init__(self, redis: _RedisContador) -> None:
        self.redis = redis
        self.ops: list[tuple[str, str]] = []

    def incr(self, key: str) -> None:
        self.ops.append(("incr", key))

    def expire(self, key: str, seconds: int) -> None:
        self.ops.append(("expire", key))

    async def execute(self) -> list[Any]:
        resultados: list[Any] = []
        for op, key in self.ops:
            if op == "incr":
                self.redis.valores[key] = self.redis.valores.get(key, 0) + 1
                resultados.append(self.redis.valores[key])
            else:
                resultados.append(True)
        return resultados


def test_el_nombre_viejo_del_setting_sigue_funcionando_como_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nuevo = Settings(**{**BASE, "OTP_MAX_VERIFY_ATTEMPTS_PER_HOUR": 4})
    assert nuevo.OTP_MAX_VERIFY_ATTEMPTS_PER_HOUR == 4

    viejo = Settings(**{**BASE, "OTP_MAX_FAILURES_PER_HOUR": 7})
    assert viejo.OTP_MAX_VERIFY_ATTEMPTS_PER_HOUR == 7

    # Un .env / entorno de produccion con el nombre viejo no se ignora.
    monkeypatch.setenv("OTP_MAX_FAILURES_PER_HOUR", "8")
    desde_entorno = Settings(**BASE)
    assert desde_entorno.OTP_MAX_VERIFY_ATTEMPTS_PER_HOUR == 8

    assert Settings.model_fields["OTP_MAX_VERIFY_ATTEMPTS_PER_HOUR"].default == 10


@pytest.mark.asyncio
async def test_verificaciones_exitosas_o_no_consumen_el_presupuesto_y_frenan(
    test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Guarda anti fuerza bruta: pasado el tope, ni el codigo correcto entra."""
    redis = _RedisContador()

    async def fake_get_redis() -> _RedisContador:
        return redis

    async def buzon(to: str, subject: str, body: str) -> bool:
        return True

    monkeypatch.setattr(otp_service, "get_redis", fake_get_redis)
    monkeypatch.setattr(tasks, "_send_email", buzon)
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "OTP_DEBUG_EXPOSE_CODE", True)
    monkeypatch.setattr(settings, "OTP_MAX_VERIFY_ATTEMPTS_PER_HOUR", 3)
    servicio = OtpService(test_session)

    async def pedir() -> str:
        respuesta = await servicio.request_code(
            store_id=TIENDA,
            phone=TELEFONO,
            channel="email",
            email="c@example.com",
            # El envio (post-respuesta desde B4-01) no importa aca.
            schedule_dispatch=lambda *args: None,
        )
        return str(respuesta["debug_code"])

    codigo = await pedir()
    incorrecto = "000000" if codigo != "000000" else "111111"
    for _ in range(2):
        with pytest.raises(OTPException):
            await servicio.verify_code(store_id=TIENDA, phone=TELEFONO, code=incorrecto)

    # Pedir un codigo nuevo no resetea el presupuesto; el exito tambien cuenta.
    codigo = await pedir()
    ok = await servicio.verify_code(store_id=TIENDA, phone=TELEFONO, code=codigo)
    assert ok["ok"] is True

    codigo = await pedir()
    with pytest.raises(OTPRateLimitedException):
        await servicio.verify_code(store_id=TIENDA, phone=TELEFONO, code=codigo)

    claves = set(redis.valores)
    assert any(k.startswith("otp:verify:") for k in claves), claves
    assert not any(k.startswith("otp:fail:") for k in claves), claves
    verify = next(v for k, v in redis.valores.items() if k.startswith("otp:verify:"))
    assert verify == 4
