"""Inventario completo de `validate_production_security`, chequeo por chequeo.

2026-09-17 (audit B7-06). Sintoma: una sola funcion encadenaba 27 `if` en 94
lineas (regla 29: >80 lineas) mezclando tres alcances distintos — secretos
"fuera de desarrollo", endurecimientos "solo produccion" y limites operativos
"en cualquier entorno". Agregar un chequeo obligaba a leer las 94 lineas para
saber donde iba, y el test que la cubria ya habia tenido que partirse en tres
parametrizaciones para expresar esos alcances.

Este archivo fija las dos mitades del contrato ANTES de reorganizar nada:

1. el tamano: el validador reparte por alcance y cada parte (el orquestador
   y cada `_validate_*`) entra en una pantalla; y
2. que ningun chequeo se pierda al moverlo — cada fila de `INVENTARIO` apaga
   una sola proteccion y exige el mensaje exacto de ESA proteccion, asi que
   borrarla, moverla mal o cambiarle el alcance la deja en rojo.

Es la guarda de la regla 17 (config de produccion falla cerrada) escrita como
lista: mientras las 35 filas pasen, las 19 condiciones de las dos tablas de
datos y los 13 `if` sueltos (16 filas) siguen vivos.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path
from typing import Any

import pytest

from core.config import Settings

CONFIG_PY = Path(inspect.getsourcefile(Settings) or "")

# Configuracion de produccion valida: cada caso rompe UNA sola cosa sobre esta.
BASE: dict[str, Any] = {
    "ENV": "production",
    "SECRET_KEY": "una_clave_de_produccion_larga_y_unica_1234567890",
    "DATABASE_URL": "postgresql+asyncpg://u:p@db:5432/shifty",
    "REDIS_URL": "redis://redis:6379/0",
    "SMTP_HOST": "smtp.example.com",
    "SMTP_PORT": 587,
    "SMTP_USER": "user",
    "SMTP_PASS": "pass",
    "EMAILS_FROM_EMAIL": "no-reply@example.com",
    "CORS_ORIGINS": "https://app.example.com",
    "FRONTEND_URL": "https://app.example.com",
    "PUBLIC_API_URL": "https://api.example.com",
    "FIELD_ENCRYPTION_KEY": "clave_de_cifrado_de_campos_de_32_o_mas",
    "RATE_LIMIT_ENABLED": True,
    "RATE_LIMIT_FAIL_CLOSED": True,
    "COOKIE_SECURE": True,
    "OTP_PROVIDER": "twilio",
    "OTP_DEBUG_EXPOSE_CODE": False,
    "EXPOSE_API_DOCS": False,
    # El entorno de tests lo pone en "true" para los tests de /ops; produccion
    # lo exige apagado (AUD2-B7-12), igual que EXPOSE_API_DOCS.
    "OPS_ENABLE_PUBLIC_HEALTH": False,
}

# (ENV en el que el chequeo debe dispararse, override que lo rompe, mensaje).
# El ENV es el MINIMO exigido: "staging" prueba ademas que el chequeo no quedo
# encerrado en el bloque de produccion, y "development" que el limite operativo
# vale en cualquier entorno.
INVENTARIO: list[tuple[str, dict[str, Any], str]] = [
    # --- Secretos: todo entorno que no sea desarrollo (2 `if` sueltos, 4 filas) ---
    (
        "staging",
        {"SECRET_KEY": "generate_a_very_secret_key_here_for_production"},
        "SECRET_KEY debe ser fuerte y unico fuera de desarrollo",
    ),
    (
        "staging",
        {"SECRET_KEY": "corta"},
        "SECRET_KEY debe ser fuerte y unico fuera de desarrollo",
    ),
    (
        "staging",
        {"SECRET_KEY": "change_this_secret_key_but_long_enough_1234567890"},
        "SECRET_KEY debe ser fuerte y unico fuera de desarrollo",
    ),
    (
        "staging",
        {"FIELD_ENCRYPTION_KEY": "replace_this_field_encryption_key_1234567890"},
        "FIELD_ENCRYPTION_KEY parece un placeholder del repo",
    ),
    # --- Endurecimientos: solo produccion ---
    # (6 filas de _BOOLEANOS_DE_PRODUCCION + 9 `if` sueltos que ocupan 10, 16 filas)
    (
        "production",
        {"CORS_ORIGINS": "https://app.example.com,http://localhost:3000"},
        "CORS_ORIGINS no debe incluir localhost en produccion",
    ),
    (
        "production",
        {"CORS_ORIGINS": "https://app.example.com,http://127.0.0.1:3000"},
        "CORS_ORIGINS no debe incluir localhost en produccion",
    ),
    (
        "production",
        {"CORS_ORIGINS": "*"},
        "CORS_ORIGINS no puede ser * con credenciales habilitadas",
    ),
    (
        "production",
        {"RATE_LIMIT_FAIL_CLOSED": False},
        "RATE_LIMIT_FAIL_CLOSED debe ser true en produccion",
    ),
    (
        "production",
        {"ACCESS_TOKEN_EXPIRE_MINUTES": 120},
        "ACCESS_TOKEN_EXPIRE_MINUTES no debe superar 30 en produccion",
    ),
    (
        "production",
        {"EXPOSE_API_DOCS": True},
        "EXPOSE_API_DOCS debe ser false en produccion",
    ),
    (
        "production",
        {"RATE_LIMIT_ENABLED": False},
        "RATE_LIMIT_ENABLED debe estar activo en produccion",
    ),
    (
        "production",
        {"COOKIE_SECURE": False},
        "COOKIE_SECURE debe ser true en produccion",
    ),
    (
        "production",
        {"FIELD_ENCRYPTION_KEY": "corta"},
        "FIELD_ENCRYPTION_KEY debe tener al menos 32 caracteres en produccion",
    ),
    (
        "production",
        {"OTP_PROVIDER": "console"},
        "OTP_PROVIDER no puede ser console en produccion",
    ),
    (
        "production",
        {"OTP_DEBUG_EXPOSE_CODE": True},
        "OTP_DEBUG_EXPOSE_CODE debe ser false en produccion",
    ),
    (
        "production",
        {"COOKIE_SAMESITE": "invalido"},
        "COOKIE_SAMESITE debe ser lax, strict o none",
    ),
    (
        "production",
        {"FRONTEND_URL": "http://localhost:3000"},
        "FRONTEND_URL no puede apuntar a localhost en produccion",
    ),
    (
        "production",
        {"PUBLIC_API_URL": "http://127.0.0.1:8000"},
        "PUBLIC_API_URL no puede apuntar a localhost en produccion",
    ),
    (
        "production",
        {"FIELD_ENCRYPTION_KEY": None},
        "FIELD_ENCRYPTION_KEY es obligatorio en produccion",
    ),
    (
        "production",
        {"OPS_ENABLE_PUBLIC_HEALTH": True},
        "OPS_ENABLE_PUBLIC_HEALTH debe ser false en produccion",
    ),
    # --- Limites operativos: cualquier entorno, desarrollo incluido ---
    # (13 filas de _MINIMOS_OPERATIVOS + 2 `if` sueltos, 15 filas)
    (
        "development",
        {"PAYMENTS_CIRCUIT_BREAKER_FAILURE_THRESHOLD": 0},
        "PAYMENTS_CIRCUIT_BREAKER_FAILURE_THRESHOLD debe ser >= 1",
    ),
    (
        "development",
        {"PAYMENTS_CIRCUIT_BREAKER_RECOVERY_SECONDS": 0},
        "PAYMENTS_CIRCUIT_BREAKER_RECOVERY_SECONDS debe ser >= 1",
    ),
    (
        "development",
        {"MERCADOPAGO_OAUTH_STATE_TTL_SECONDS": 30},
        "MERCADOPAGO_OAUTH_STATE_TTL_SECONDS debe ser >= 60",
    ),
    (
        "development",
        {"MERCADOPAGO_WEBHOOK_MAX_AGE_SECONDS": 30},
        "MERCADOPAGO_WEBHOOK_MAX_AGE_SECONDS debe ser >= 60",
    ),
    (
        "development",
        {"PAYMENT_HOLD_MINUTES": 1},
        "PAYMENT_HOLD_MINUTES debe ser >= 5",
    ),
    (
        "development",
        {"REDIS_MAX_CONNECTIONS": 0},
        "REDIS_MAX_CONNECTIONS debe ser >= 1",
    ),
    (
        "development",
        {"CELERY_WORKER_PREFETCH_MULTIPLIER": 0},
        "CELERY_WORKER_PREFETCH_MULTIPLIER debe ser >= 1",
    ),
    (
        "development",
        {"CELERY_TASK_SOFT_TIME_LIMIT_SECONDS": 0},
        "CELERY_TASK_SOFT_TIME_LIMIT_SECONDS debe ser >= 1",
    ),
    (
        "development",
        {"CELERY_TASK_TIME_LIMIT_SECONDS": 10},
        "CELERY_TASK_TIME_LIMIT_SECONDS debe ser mayor al soft time limit",
    ),
    (
        "development",
        {"MAX_REQUEST_BODY_BYTES": 100},
        "MAX_REQUEST_BODY_BYTES no puede ser menor a 1024 bytes",
    ),
    (
        "development",
        {"MAX_REQUEST_BODY_BYTES": 5 * 1024 * 1024},
        "MAX_REQUEST_BODY_BYTES no debe superar 1MB sin revision de seguridad",
    ),
    # AUD2-B7-06 (2026-09-20) sumo estos cuatro a `_MINIMOS_OPERATIVOS` y no
    # llegaron aca: el inventario solo detectaba borrados, no altas.
    (
        "development",
        {"RATE_LIMIT_WINDOW_SECONDS": 0},
        "RATE_LIMIT_WINDOW_SECONDS debe ser >= 1",
    ),
    (
        "development",
        {"MAX_UPLOAD_BODY_BYTES": 100},
        "MAX_UPLOAD_BODY_BYTES no puede ser menor a 1024 bytes",
    ),
    (
        "development",
        {"REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS": 0},
        "REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS debe ser >= 0.1",
    ),
    (
        "development",
        {"REDIS_SOCKET_TIMEOUT_SECONDS": 0},
        "REDIS_SOCKET_TIMEOUT_SECONDS debe ser >= 0.1",
    ),
]

# Filas de los chequeos sueltos: los `if` escritos uno por uno, fuera de las
# dos tablas de datos de `config.py`. Son 13 `if` que ocupan 16 filas, porque
# SECRET_KEY tiene tres ramas en un mismo `or` (3 filas para 1 `if`) y
# CORS_ORIGINS/localhost dos.
N_SUELTOS = 16

# El total NO se escribe a mano suelto: se ata a las tablas de `config.py`
# (`test_el_inventario_cubre_las_dos_tablas`). Agregar una fila a
# `_MINIMOS_OPERATIVOS` o a `_BOOLEANOS_DE_PRODUCCION` sin inventariarla
# rompe la cuenta, que es lo que fallo con AUD2-B7-06: sus cuatro minimos
# nuevos no llegaron aca y el inventario, que solo detectaba borrados, no dijo
# nada. Bajar este numero es borrar una proteccion; subirlo sin agregar la
# fila correspondiente, olvidarse de probarla.
FILAS_ESPERADAS = 35
MAX_LINEAS_DEL_VALIDADOR = 30


def _build(**overrides: Any) -> Settings:
    return Settings(**{**BASE, **overrides})


def test_una_configuracion_de_produccion_valida_sigue_arrancando() -> None:
    assert _build().ENV.value == "production"


@pytest.mark.parametrize(
    ("env", "override", "mensaje"),
    INVENTARIO,
    ids=[
        f"{env}-{next(iter(override))}-{mensaje[:24]}"
        for env, override, mensaje in INVENTARIO
    ],
)
def test_cada_chequeo_sigue_aplicandose(
    env: str, override: dict[str, Any], mensaje: str
) -> None:
    with pytest.raises(ValueError, match=re.escape(mensaje)):
        _build(ENV=env, **override)


def test_el_inventario_cubre_las_dos_tablas() -> None:
    """Una fila nueva en una tabla de `config.py` obliga a inventariarla.

    El test viejo era unidireccional: detectaba un chequeo BORRADO (su mensaje
    desaparecia de `config.py`) pero no uno AGREGADO. AUD2-B7-06 sumo cuatro
    minimos operativos y el inventario siguio en verde sin ellos (2026-09-20).
    """
    from core.config import _BOOLEANOS_DE_PRODUCCION, _MINIMOS_OPERATIVOS

    campos_inventariados = {
        campo for _env, override, _msg in INVENTARIO for campo in override
    }
    sin_inventariar = [
        campo
        for campo, *_ in (*_MINIMOS_OPERATIVOS, *_BOOLEANOS_DE_PRODUCCION)
        if campo not in campos_inventariados
    ]
    assert sin_inventariar == [], sin_inventariar

    total = len(_MINIMOS_OPERATIVOS) + len(_BOOLEANOS_DE_PRODUCCION) + N_SUELTOS
    assert total == FILAS_ESPERADAS, (
        f"{len(_MINIMOS_OPERATIVOS)} minimos + "
        f"{len(_BOOLEANOS_DE_PRODUCCION)} booleanos + {N_SUELTOS} sueltos "
        f"!= {FILAS_ESPERADAS} filas inventariadas"
    )


def test_el_inventario_no_se_quedo_corto() -> None:
    """Un chequeo movido a una tabla de datos sigue teniendo que estar aca."""
    assert len(INVENTARIO) == FILAS_ESPERADAS
    # Los mensajes largos se escriben como literales concatenados en varias
    # lineas; se unen antes de buscarlos para comparar contra el texto real.
    fuente = re.sub(r'"\s*\n\s*"', "", CONFIG_PY.read_text(encoding="utf-8"))
    faltantes = [mensaje for _, _, mensaje in INVENTARIO if mensaje not in fuente]
    assert faltantes == [], faltantes


def _partes_del_validador() -> dict[str, list[str]]:
    """Cada parte del validador, leida del archivo: nombre -> lineas.

    Las partes son el orquestador `validate_production_security` y todo metodo
    `_validate_*` de `Settings`. No sirve `inspect.getsource` sobre el
    orquestador: `model_validator` lo deja tipado como
    `PydanticDescriptorProxy` y mypy rechaza la llamada.
    """
    fuente = CONFIG_PY.read_text(encoding="utf-8").splitlines()
    partes: dict[str, list[str]] = {}
    for i, linea in enumerate(fuente):
        firma = linea.strip()
        if not (
            firma.startswith("def validate_production_security")
            or firma.startswith("def _validate_")
        ):
            continue
        cuerpo = [linea]
        for siguiente in fuente[i + 1 :]:
            if siguiente.strip() and not siguiente.startswith(" " * 8):
                break
            cuerpo.append(siguiente)
        while not cuerpo[-1].strip():
            cuerpo.pop()
        partes[firma.split("(")[0].removeprefix("def ")] = cuerpo
    return partes


def test_cada_parte_del_validador_entra_en_una_pantalla() -> None:
    """Regla 29 y criterio 6 del audit: cada parte bajo 30 lineas.

    Mide el orquestador Y cada funcion por alcance: repartir 94 lineas en una
    sola funcion privada de 36 no resolvia nada (observacion V-diff,
    2026-09-18).
    """
    partes = _partes_del_validador()
    assert "validate_production_security" in partes
    assert len(partes) >= 4, sorted(partes)
    largas = {
        nombre: len(lineas)
        for nombre, lineas in partes.items()
        if len(lineas) > MAX_LINEAS_DEL_VALIDADOR
    }
    assert largas == {}, (
        f"partes de mas de {MAX_LINEAS_DEL_VALIDADOR} lineas: {largas}; "
        "partir por alcance, no apilar"
    )
