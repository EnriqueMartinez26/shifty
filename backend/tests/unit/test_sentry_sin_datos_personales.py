"""Sentry (proveedor externo) no recibe datos personales de los clientes.

PV-02 (auditoria de privacidad, 2026-09-24). ``sentry_sdk.init`` corria con
``include_local_variables`` en su default (True): cada frame de un traceback
viajaba con sus variables, por ejemplo ``data=PublicBookingCreate(
client_name=..., client_phone=..., client_email=...)``. ``_scrub_event``
limpiaba el body, cookies y headers, pero no las variables de los frames, ni
``request.url`` / ``query_string`` (el telefono viaja en la ruta de
``/public/client/{store}/{phone}/appointments`` y en
``/public/deposit/preview?client_phone=``), ni los argumentos de una tarea de
Celery que falla (``celery-job.args`` de ``send_otp_email`` = email, asunto y
cuerpo CON el codigo).
"""

from __future__ import annotations

from typing import Any

import pytest

import core.observability as observability
from core.config import settings


def _evento() -> dict[str, Any]:
    return {
        "transaction": "/public/client/{store_public_id}/{phone}/appointments",
        "request": {
            "url": "https://turnos.example.com/api/public/client/01J9ZX/"
            "%2B5491155550042/appointments",
            "query_string": "client_phone=%2B5491155550042&service_id=01J9",
            "headers": {"user-agent": "x"},
        },
        "extra": {
            "celery-job": {
                "task_name": "send_otp_email",
                "args": ["cliente@example.com", "Asunto", "Tu codigo es: 123456"],
                "kwargs": {"to": "cliente@example.com"},
            }
        },
        "exception": {
            "values": [
                {
                    "type": "ValueError",
                    "stacktrace": {
                        "frames": [
                            {
                                "function": "book",
                                "vars": {"client_phone": "'+5491155550042'"},
                            }
                        ]
                    },
                }
            ]
        },
    }


def test_el_evento_sale_sin_telefono_codigo_ni_argumentos_de_la_tarea() -> None:
    limpio: Any = observability._scrub_event(_evento(), {})  # type: ignore[arg-type]

    assert limpio is not None
    texto = str(limpio)
    assert "5491155550042" not in texto
    assert "cliente@example.com" not in texto
    assert "123456" not in texto
    assert limpio["request"]["url"].endswith(
        "/public/client/01J9ZX/[phone]/appointments"
    )
    assert "query_string" not in limpio["request"]
    job = limpio["extra"]["celery-job"]
    assert job["task_name"] == "send_otp_email", "el nombre de la tarea sirve y queda"
    assert job["args"] == "[redacted]"
    assert job["kwargs"] == "[redacted]"
    frame = limpio["exception"]["values"][0]["stacktrace"]["frames"][0]
    assert "vars" not in frame
    assert frame["function"] == "book"


def test_un_id_publico_no_se_confunde_con_un_telefono() -> None:
    evento: dict[str, Any] = {
        "request": {"url": "https://x/api/appointments/01J9ZXABCDEF0123456789ABCD"}
    }

    limpio: Any = observability._scrub_event(evento, {})  # type: ignore[arg-type]

    assert limpio is not None
    assert limpio["request"]["url"].endswith("/01J9ZXABCDEF0123456789ABCD")


def test_sentry_arranca_sin_variables_locales(monkeypatch: pytest.MonkeyPatch) -> None:
    import sentry_sdk

    capturado: dict[str, Any] = {}
    monkeypatch.setattr(sentry_sdk, "init", lambda **kw: capturado.update(kw))
    monkeypatch.setattr(sentry_sdk, "set_tag", lambda *_a, **_kw: None)
    monkeypatch.setattr(settings, "SENTRY_DSN", "https://clave@sentry.example/1")
    monkeypatch.setattr(observability, "_initialized", False)

    assert observability.init_observability("api") is True

    assert capturado["include_local_variables"] is False
    assert capturado["send_default_pii"] is False
    assert capturado["before_send"] is observability._scrub_event
    # ``before_send`` no corre sobre transacciones, y produccion muestrea el
    # 10 % con ``request.url`` y query (revision de PV-02, 2026-09-24).
    assert capturado["before_send_transaction"] is observability._scrub_event


def test_una_transaccion_muestreada_sale_sin_telefono_ni_query() -> None:
    transaccion: dict[str, Any] = {
        "type": "transaction",
        "transaction": "/public/deposit/preview",
        "request": {
            "url": "https://x/api/public/client/01J9ZX/5491155550042/appointments"
            "?client_phone=5491155550042",
            "query_string": "client_phone=5491155550042",
        },
        "breadcrumbs": {
            "values": [
                {
                    "category": "httplib",
                    "data": {
                        "url": "https://x/api/public/client/01J9ZX/"
                        "+5491155550042/appointments?client_phone=5491155550042",
                        "method": "GET",
                    },
                }
            ]
        },
    }

    limpio: Any = observability._scrub_event(transaccion, {})  # type: ignore[arg-type]

    assert limpio is not None
    assert "5491155550042" not in str(limpio)
    assert "query_string" not in limpio["request"]
    assert limpio["request"]["url"].endswith("/01J9ZX/[phone]/appointments")
    miga = limpio["breadcrumbs"]["values"][0]["data"]
    assert miga["url"].endswith("/01J9ZX/[phone]/appointments")
    assert miga["method"] == "GET"
