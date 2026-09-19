"""Una sola redaccion de URLs con credenciales en todo el repo (S-01).

2026-09-17. El lote 1A cerro dos veces el mismo agujero con dos mecanismos
distintos: B7-04 le dio a `run_migrations.py` el `redact_url` de
`core/config.py` (que tapa TODO lo que sigue al esquema) y C-01 resolvio
`alembic/env.py` a mano, armando el mensaje con `esquema=` y `host=` en vez de
redactar la URL. Sintoma: dos formas distintas de escribir el mismo error, una
de ellas sin helper, y la proxima vez que haga falta se escribe una tercera.

Ahora hay un solo helper con dos niveles:

* `redact_url(url, keep_target=True)` para los scripts y las migraciones: deja
  esquema, host, puerto y base — lo que hace falta para saber contra que
  deploy estaba apuntando — y nunca usuario ni contrasena.
* `redact_url(url)` para el error de settings, que sale en el 503 publico de
  `BootErrorMiddleware`: ahi tampoco debe verse el hostname interno.

Regla 20 (errores neutros hacia afuera): una URL con credenciales no cruza a
ningun mensaje, ni de log ni de respuesta.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.config import _sanitize_settings_error, redact_url

BACKEND = Path(__file__).resolve().parents[2]
USUARIO = "shifty_app"
CONTRASENA = "S3cr3t-no-debe-verse"
URL = f"postgresql+asyncpg://{USUARIO}:{CONTRASENA}@db:5432/shifty?sslmode=require"
CONSUMIDORES = (BACKEND / "run_migrations.py", BACKEND / "alembic" / "env.py")


def test_el_helper_conserva_el_destino_y_tapa_las_credenciales() -> None:
    redactada = redact_url(URL, keep_target=True)

    assert USUARIO not in redactada
    assert CONTRASENA not in redactada
    assert redactada == "postgresql+asyncpg://[redacted]@db:5432/shifty?sslmode=require"


def test_tapa_tambien_un_usuario_sin_contrasena() -> None:
    assert (
        redact_url("redis://solo_usuario@cache:6379/0", keep_target=True)
        == "redis://[redacted]@cache:6379/0"
    )


def test_una_contrasena_con_arroba_se_tapa_entera() -> None:
    """El `@` sin escapar no puede dejar la mitad de la contrasena afuera."""
    redactada = redact_url("postgres://u:p@ss@db:5432/shifty", keep_target=True)

    assert redactada == "postgres://[redacted]@db:5432/shifty"
    assert "ss" not in redactada.split("@")[0]


def test_una_url_sin_credenciales_queda_igual() -> None:
    """No hay nada que tapar: el mensaje no pierde el destino por las dudas."""
    assert (
        redact_url("postgresql://db:5432/shifty", keep_target=True)
        == "postgresql://db:5432/shifty"
    )


def test_el_error_de_settings_sigue_tapando_hasta_el_hostname() -> None:
    """Ese texto sale en el 503 publico: ahi no va ni el host interno."""
    assert (
        redact_url(f"no valida: {URL}") == "no valida: postgresql+asyncpg://[redacted]"
    )
    sanitizado = _sanitize_settings_error(f"DATABASE_URL invalida: {URL}")
    assert USUARIO not in sanitizado
    assert CONTRASENA not in sanitizado
    assert "db:5432" not in sanitizado


def test_los_dos_consumidores_usan_el_mismo_helper() -> None:
    """La proxima vez que haga falta se importa; no se reescribe el regex.

    Desde B7-11 los dos consumidores delegan el parseo (y con el la redaccion
    `keep_target=True` del error) en `core.config.parse_db_url`.
    """
    helper = (BACKEND / "core" / "config.py").read_text(encoding="utf-8")
    assert "redact_url(url, keep_target=True)" in helper
    for archivo in CONSUMIDORES:
        fuente = archivo.read_text(encoding="utf-8")
        assert "from core.config import parse_db_url" in fuente, archivo
        assert "re.sub" not in fuente, f"{archivo} reimplementa la redaccion"


# --- Rechazo V-diff de S-01 (2026-09-18) --------------------------------------
# La primera version cortaba las credenciales en el primer `/`: con
# `postgres://shifty:ab/cd+ef@db:5432/shifty` no habia match y la URL salia
# ENTERA, contrasena incluida. Una contrasena real (generada) puede traer `/`,
# `+`, `@` y hasta un espacio si alguien la pega sin escapar.


@pytest.mark.parametrize(
    "url",
    [
        "postgres://shifty:ab/cd+ef@db:5432/shifty",
        "postgres://shifty:ab+cd@db:5432/shifty",
        "postgres://shifty:a@b/c@db:5432/shifty",
        "postgres://shifty:a/b@c/d@db:5432/shifty",
    ],
    ids=["barra", "mas", "arroba-y-barra", "barras-y-arrobas"],
)
def test_contrasenas_con_caracteres_de_url_se_tapan_enteras(url: str) -> None:
    assert redact_url(url, keep_target=True) == "postgres://[redacted]@db:5432/shifty"
    assert redact_url(url) == "postgres://[redacted]"


@pytest.mark.parametrize(
    "url",
    [
        "postgres://shifty:ab cd@db:5432/shifty",
        "postgres://shifty:a@b cd@db:5432/shifty",
    ],
    ids=["espacio", "arroba-y-espacio"],
)
def test_con_un_espacio_en_la_contrasena_se_tapa_todo_lo_que_sigue(url: str) -> None:
    """Decision: con un espacio no se sabe donde terminan las credenciales.

    Se peca por tapar de mas: desde el esquema hasta el final del texto, en
    los dos niveles. Se pierde el destino en el mensaje, nunca un pedazo de la
    contrasena.
    """
    mensaje = f"No se pudo parsear DATABASE_URL: {url}"
    for redactada in (redact_url(mensaje, keep_target=True), redact_url(mensaje)):
        assert redactada == "No se pudo parsear DATABASE_URL: postgres://[redacted]"
