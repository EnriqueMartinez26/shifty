"""Sentry muestrea por ruta, no con una tasa plana (F5-02, R11-13).

2026-09-24. ``traces_sample_rate=0.1`` en produccion mandaba una transaccion
de cada diez para TODO: los health checks del compose y del uptime externo
(``/ops/health/*`` cada pocos segundos, ~5760 por dia y replica) gastaban la
cuota, mientras que un cobro o un webhook de Mercado Pago, que es lo que hay
que poder investigar entero, tenia la misma chance que un GET de la vitrina.
Tampoco habia ``release`` confiable ni monitoreo de las tareas de beat.

Decisiones que se fijan aca:
- health y ``/ops/slo``: nunca (tampoco fuera de produccion);
- ``/payments/*`` (incluye el webhook): siempre;
- GET publico: 2 %; escrituras: 20 %; lecturas del panel: 10 %;
- el header ``sentry-trace`` de un cliente NO sube la tasa de un request
  (si no, cualquiera fuerza el 100 % y agota la cuota);
- una tarea de Celery hereda la decision del request que la encolo.
"""

from __future__ import annotations

from typing import Any

import pytest

import core.observability as observability
from core.config import Environment, settings


def _request(
    method: str, path: str, *, parent: bool | None = None, root_path: str = ""
) -> dict[str, Any]:
    return {
        "transaction_context": {"name": "generic ASGI request", "op": "http.server"},
        "parent_sampled": parent,
        "asgi_scope": {
            "type": "http",
            "method": method,
            "path": path,
            "root_path": root_path,
        },
    }


def _tarea(nombre: str, *, parent: bool | None = None) -> dict[str, Any]:
    return {
        "transaction_context": {"name": nombre, "op": "queue.task.celery"},
        "parent_sampled": parent,
        "celery_job": {"task": nombre, "args": [], "kwargs": {}},
    }


@pytest.fixture
def produccion(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ENV", Environment.PRODUCTION)


@pytest.mark.usefixtures("produccion")
@pytest.mark.parametrize(
    ("method", "path", "tasa"),
    [
        ("GET", "/ops/health/live", 0.0),
        ("GET", "/ops/health/ready", 0.0),
        ("GET", "/ops/slo", 0.0),
        ("GET", "/public/stores/barberia", 0.02),
        ("GET", "/public/availability", 0.02),
        ("HEAD", "/public/stores/barberia/logo", 0.02),
        ("POST", "/public/appointments", 0.2),
        ("PATCH", "/stores/me", 0.2),
        ("DELETE", "/appointment-blocks/01J9ZX", 0.2),
        ("PUT", "/staff/01J9ZX/schedule", 0.2),
        ("GET", "/appointments/", 0.1),
        ("GET", "/dashboard/summary", 0.1),
        ("GET", "/payments/", 1.0),
        ("POST", "/payments/webhooks/mercadopago", 1.0),
        ("POST", "/payments/01J9ZX/preference", 1.0),
    ],
)
def test_la_tasa_de_produccion_depende_de_la_ruta(
    method: str, path: str, tasa: float
) -> None:
    assert observability._traces_sampler(_request(method, path)) == tasa


@pytest.mark.parametrize("env", list(Environment))
@pytest.mark.parametrize(
    "path", ["/ops/health/live", "/ops/health/ready", "/ops/slo", "/api/ops/slo"]
)
def test_los_health_checks_nunca_se_muestrean(
    monkeypatch: pytest.MonkeyPatch, env: Environment, path: str
) -> None:
    """Ni en desarrollo ni aunque el cliente mande ``sentry-trace`` muestreado."""
    monkeypatch.setattr(settings, "ENV", env)

    assert observability._traces_sampler(_request("GET", path, parent=True)) == 0.0


@pytest.mark.usefixtures("produccion")
def test_un_header_de_traza_del_cliente_no_sube_la_tasa() -> None:
    contexto = _request("GET", "/public/services", parent=True)

    assert observability._traces_sampler(contexto) == 0.02


@pytest.mark.usefixtures("produccion")
def test_la_ruta_se_mide_sin_el_root_path_del_proxy() -> None:
    contexto = _request("GET", "/api/ops/health/ready", root_path="/api")

    assert observability._traces_sampler(contexto) == 0.0
    assert (
        observability._traces_sampler(
            _request("POST", "/api/payments/webhooks/mercadopago", root_path="/api")
        )
        == 1.0
    )


@pytest.mark.usefixtures("produccion")
def test_una_tarea_hereda_la_decision_del_request_que_la_encolo() -> None:
    assert observability._traces_sampler(_tarea("x", parent=True)) == 1.0
    assert observability._traces_sampler(_tarea("x", parent=False)) == 0.0


@pytest.mark.usefixtures("produccion")
def test_una_tarea_de_beat_sin_padre_se_muestrea_poco() -> None:
    """Beat corre varias tareas por minuto: su salud la cubre Sentry Crons."""
    tasa = observability._traces_sampler(_tarea("process_outbox_batch"))

    assert tasa == 0.02


def test_fuera_de_produccion_se_ve_todo_menos_el_health(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ENV", Environment.DEVELOPMENT)

    assert observability._traces_sampler(_request("GET", "/public/services")) == 1.0
    assert observability._traces_sampler(_tarea("x")) == 1.0


def test_init_usa_el_sampler_la_version_y_monitorea_beat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sentry_sdk
    import sentry_sdk.integrations.celery as integracion_celery

    class CeleryIntegrationFalsa:
        """Registra los argumentos: la real parchea Celery en todo el proceso."""

        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

    monkeypatch.setattr(integracion_celery, "CeleryIntegration", CeleryIntegrationFalsa)
    capturado: dict[str, Any] = {}
    monkeypatch.setattr(sentry_sdk, "init", lambda **kw: capturado.update(kw))
    monkeypatch.setattr(sentry_sdk, "set_tag", lambda *_a, **_kw: None)
    monkeypatch.setattr(settings, "SENTRY_DSN", "https://clave@sentry.example/1")
    monkeypatch.setattr(settings, "VERSION", "v2026.09.24-abc1234")
    monkeypatch.setattr(observability, "_initialized", False)

    assert observability.init_observability("worker") is True

    assert capturado["release"] == "v2026.09.24-abc1234"
    assert capturado["traces_sampler"] is observability._traces_sampler
    assert "traces_sample_rate" not in capturado, "el sampler es la unica fuente"
    celery = [
        i for i in capturado["integrations"] if isinstance(i, CeleryIntegrationFalsa)
    ]
    assert len(celery) == 1
    assert celery[0].kwargs == {
        "monitor_beat_tasks": True,
        "exclude_beat_tasks": observability.SENTRY_CRONS_EXCLUDED_BEAT_TASKS,
    }
    # El scrubbing de F1-A sigue enchufado a eventos y transacciones.
    assert capturado["before_send"] is observability._scrub_event
    assert capturado["before_send_transaction"] is observability._scrub_event


def test_sentry_crons_monitorea_solo_el_vencimiento_de_senas() -> None:
    """Plan gratuito de Sentry: UN monitor (decision del dueno, 2026-09-25).

    ``monitor_beat_tasks`` creaba un monitor por cada tarea de beat con
    crontab (8). Se monitorea solo el vencimiento de retenciones sin pagar:
    si deja de correr, los turnos con sena pendiente no se liberan y la agenda
    queda tomada. El resto lo cubren ``/ops/slo`` y el latido del worker. Se
    prueba con el matcher real del SDK (lista de regex, ``re.search`` con
    ``$`` agregado) contra los nombres reales del beat: una tarea nueva nace
    excluida y no consume cuota.
    """
    from sentry_sdk.utils import match_regex_list

    from core.celery_app import celery_app

    nombres = set(celery_app.conf.beat_schedule)
    assert observability.SENTRY_CRONS_MONITORED_BEAT_TASK in nombres
    monitoreadas = {
        nombre
        for nombre in nombres | {"una-tarea-nueva-cada-hora"}
        if not match_regex_list(nombre, observability.SENTRY_CRONS_EXCLUDED_BEAT_TASKS)
    }
    assert monitoreadas == {"expire-unpaid-appointment-holds-every-minute"}
