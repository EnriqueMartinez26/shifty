"""Lo que se guarda de Mercado Pago: una lista blanca, nunca el recurso entero.

2026-09-25, L3-01 y PV-14. ``payments.raw_payload`` guardaba el recurso
completo del pago (conciliacion) y de la preferencia: email, nombre,
identificacion (DNI/CUIT) y telefono del pagador, titular y digitos de la
tarjeta, IP, titulo del servicio. Ningun lector de ``raw_payload`` usa esos
datos y la Politica de Privacidad dice que Shifty no los almacena.

La lista del pago es la misma que arma el webhook
(``processing.enrich_mercadopago_webhook_payload``); la de ``metadata``, las
claves que Shifty manda en la preferencia (``service.prepare_mercadopago_preference``).
La validacion (collector, importe, referencia) sigue leyendo el recurso
completo en memoria: esto recorta solo lo que se persiste.

``alembic/versions/b5d7f9a1c3e6_minimizar_raw_payload_de_pagos.py`` recorta
las filas historicas con una copia congelada de estas listas.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from modules.payments.model import JsonValue

# Claves de primer nivel de la notificacion de MP y del payload que arma la
# conciliacion (``{"data": remoto, "status": ...}``).
NOTIFICATION_FIELDS = (
    "id",
    "type",
    "action",
    "topic",
    "resource",
    "api_version",
    "live_mode",
    "date_created",
    "user_id",
    "status",
    "external_reference",
    "payment_id",
    "appointment_id",
)
# Recurso del pago: lo que lee el webhook.
PAYMENT_DATA_FIELDS = (
    "id",
    "status",
    "external_reference",
    "metadata",
    "date_approved",
    "transaction_amount",
    "currency_id",
    "collector_id",
    "live_mode",
    "preference_id",
)
# ``metadata`` que Shifty manda en la preferencia (ids internos).
METADATA_FIELDS = ("appointment_id", "store_id", "store_public_id", "payment_id")
# Respuesta de la preferencia: el id y los links de checkout.
PREFERENCE_FIELDS = ("id", "init_point", "sandbox_init_point", "external_reference")

_SCALARS = (str, int, float, bool, type(None))


def _scalars(source: Mapping[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    """Las claves permitidas con valor escalar: un dict o una lista no pasa
    aunque la clave este en la lista (no se sabe que trae adentro)."""
    return {
        k: source[k] for k in fields if k in source and isinstance(source[k], _SCALARS)
    }


def minimize_payment_payload(payload: Mapping[str, Any]) -> dict[str, JsonValue]:
    """Payload de webhook o de conciliacion reducido a la lista blanca."""
    result: dict[str, Any] = _scalars(payload, NOTIFICATION_FIELDS)
    data = payload.get("data")
    if isinstance(data, Mapping):
        minimal = _scalars(data, PAYMENT_DATA_FIELDS)
        metadata = data.get("metadata")
        if isinstance(metadata, Mapping):
            minimal["metadata"] = _scalars(metadata, METADATA_FIELDS)
        result["data"] = minimal
    return result


def minimize_preference_payload(payload: Mapping[str, Any]) -> dict[str, JsonValue]:
    """Respuesta de ``/checkout/preferences`` sin ``payer`` ni ``items``."""
    return _scalars(payload, PREFERENCE_FIELDS)


__all__ = [
    "METADATA_FIELDS",
    "NOTIFICATION_FIELDS",
    "PAYMENT_DATA_FIELDS",
    "PREFERENCE_FIELDS",
    "minimize_payment_payload",
    "minimize_preference_payload",
]
