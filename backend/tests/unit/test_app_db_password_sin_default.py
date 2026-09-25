"""C-02 (2026-09-19): la contrasena del rol `shifty_app` no tiene default.

Sintoma: `c3d4e5f6a7b8_rls_efectivo.py` hacia
`os.getenv("APP_DB_PASSWORD", "shifty_app_password")` y docker-compose.yml
repetia `${APP_DB_PASSWORD:-shifty_app_password}` dos veces. Un despliegue que
no exportaba la variable creaba el rol de la aplicacion con una contrasena
publicada en el repo; con ella, `SET app.is_global_admin='true'` lee todas
las tiendas. Regla 17/21: la config falla cerrada, no usa un valor conocido.

Tests sin base: la migracion se ejecuta con `op` simulado; compose se lee
como texto (no se corre docker compose).
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

import pytest
import sqlalchemy as sa

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_ROOT.parent
MIGRACION = BACKEND_ROOT / "alembic" / "versions" / "c3d4e5f6a7b8_rls_efectivo.py"
DEFAULT_PUBLICADO = "shifty_app_password"

# AUD2-C-02 (2026-09-19): C-02 cerro solo la del rol shifty_app, que es el
# MENOS privilegiado. El rol dueno de la base (tiene DDL y RLS no lo alcanza) y
# el broker seguian con su default publicado en el repo.
CREDENCIALES = ("APP_DB_PASSWORD", "POSTGRES_PASSWORD", "RABBITMQ_DEFAULT_PASS")
DEFAULTS_PUBLICADOS = ("shifty_app_password", "shifty_password")


def _migracion_con_op_simulado(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[ModuleType, MagicMock]:
    spec = importlib.util.spec_from_file_location("migracion_c3d4e5f6a7b8", MIGRACION)
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    op = MagicMock()
    op.get_bind.return_value.dialect.name = "postgresql"
    monkeypatch.setattr(modulo, "op", op)
    return modulo, op


@pytest.mark.parametrize("valor", [None, "", "   "])
def test_la_migracion_sin_la_variable_falla_antes_de_tocar_la_base(
    monkeypatch: pytest.MonkeyPatch, valor: str | None
) -> None:
    if valor is None:
        monkeypatch.delenv("APP_DB_PASSWORD", raising=False)
    else:
        monkeypatch.setenv("APP_DB_PASSWORD", valor)
    migracion, op = _migracion_con_op_simulado(monkeypatch)

    with pytest.raises(RuntimeError, match="APP_DB_PASSWORD"):
        migracion.upgrade()

    assert op.execute.call_count == 0, "emitio DDL antes de fallar"


def test_la_migracion_usa_la_contrasena_de_la_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_DB_PASSWORD", "valor-explicito-de-prueba")
    migracion, op = _migracion_con_op_simulado(monkeypatch)

    migracion.upgrade()

    sql = " ".join(str(llamada.args[0]) for llamada in op.execute.call_args_list)
    assert "PASSWORD 'valor-explicito-de-prueba'" in sql
    assert DEFAULT_PUBLICADO not in sql


def test_compose_no_resuelve_sin_la_variable() -> None:
    for compose in sorted(REPO_ROOT.glob("docker-compose*.yml")):
        texto = compose.read_text(encoding="utf-8")
        usos = re.findall(r"\$\{APP_DB_PASSWORD(?P<resto>[^}]*)\}", texto)
        for resto in usos:
            assert resto.startswith(":?"), (
                f"{compose.name}: ${{APP_DB_PASSWORD{resto}}} resuelve sin la "
                "variable; tiene que ser ${APP_DB_PASSWORD:?mensaje}"
            )
    texto = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "${APP_DB_PASSWORD:?" in texto


def test_el_default_publicado_no_vive_en_la_app_ni_en_la_config() -> None:
    candidatos = [
        *REPO_ROOT.glob("docker-compose*.yml"),
        REPO_ROOT / ".env.example",
        BACKEND_ROOT / ".env.production.example",
        *REPO_ROOT.glob(".github/workflows/*.yml"),
        *(
            p
            for p in BACKEND_ROOT.rglob("*.py")
            if "tests" not in p.relative_to(BACKEND_ROOT).parts
            and ".venv" not in p.relative_to(BACKEND_ROOT).parts
        ),
    ]
    con_default = [
        str(p.relative_to(REPO_ROOT))
        for p in candidatos
        if p.is_file() and DEFAULT_PUBLICADO in p.read_text(encoding="utf-8")
    ]
    assert not con_default, (
        f"la contrasena publicada del rol shifty_app sigue en: {con_default}"
    )


def _create_role(op: MagicMock) -> str:
    """El DDL tal como lo recibe Postgres.

    `op.execute(str)` envuelve el string en `sqlalchemy.text()` (que trata
    `:palabra` como parametro ligado y desescapa la barra-dos-puntos) y el driver de las
    migraciones es psycopg2 (pyformat: `%` se duplica al compilar y se vuelve
    a formatear al ejecutar). Se reproduce ese camino sin base.
    """
    bloques = [str(llamada.args[0]) for llamada in op.execute.call_args_list]
    ddl = next(b for b in bloques if "CREATE ROLE" in b)
    compilado = sa.text(ddl).compile(
        dialect=sa.create_engine("postgresql+psycopg2://").dialect
    )
    assert compilado.params == {}, (
        f"el DDL tiene parametros ligados: {compilado.params}"
    )
    return str(compilado.string) % {}


def _literal_del_password(ddl: str) -> str:
    """Decodifica el literal SQL que sigue a PASSWORD, respetando '' y E''."""
    resto = ddl.split("PASSWORD ", 1)[1]
    prefijo_e = resto.startswith("E'")
    i = 2 if prefijo_e else 1
    assert resto[i - 1] == "'", resto[:20]
    valor = []
    while True:
        c = resto[i]
        if prefijo_e and c == "\\":
            valor.append(resto[i + 1])
            i += 2
            continue
        if c == "'":
            if resto[i + 1 : i + 2] == "'":
                valor.append("'")
                i += 2
                continue
            break
        valor.append(c)
        i += 1
    # Despues del literal cerrado sigue el resto del CREATE ROLE, sin nada
    # que se haya colado desde la contrasena.
    assert resto[i + 1 :].lstrip().startswith("NOSUPERUSER"), resto[i + 1 : i + 40]
    return "".join(valor)


@pytest.mark.parametrize(
    "password",
    [
        "con'comilla",
        "x'; DROP ROLE x; --",
        r"barra\invertida",
        r"mezcla\'; DROP ROLE x; --",
        ":empieza_con_dos_puntos",
        r"barra\:dos_puntos",
        "50%off:x",
    ],
)
def test_la_contrasena_viaja_como_un_unico_literal_bien_cerrado(
    monkeypatch: pytest.MonkeyPatch, password: str
) -> None:
    """C-02 (2026-09-19): la contrasena iba al CREATE ROLE por f-string.

    Sintoma: con una comilla simple el DDL se rompia o inyectaba SQL. Ahora
    va como literal escapado (semantica de quote_literal: '' para la comilla
    y E'' con la barra duplicada si hay barras).
    """
    monkeypatch.setenv("APP_DB_PASSWORD", password)
    migracion, op = _migracion_con_op_simulado(monkeypatch)

    migracion.upgrade()

    assert _literal_del_password(_create_role(op)) == password


@pytest.mark.parametrize(
    "password", ["con\x00nul", "salto\nde linea", "tab\tx", "del\x7f"]
)
def test_la_contrasena_con_caracteres_de_control_se_rechaza(
    monkeypatch: pytest.MonkeyPatch, password: str
) -> None:
    migracion, op = _migracion_con_op_simulado(monkeypatch)
    # El sistema operativo no admite NUL en una variable de entorno: se le da
    # a la migracion un `os` cuyo environ es un dict comun.
    monkeypatch.setattr(
        migracion, "os", SimpleNamespace(environ={"APP_DB_PASSWORD": password})
    )

    with pytest.raises(RuntimeError, match="APP_DB_PASSWORD"):
        migracion.upgrade()

    assert op.execute.call_count == 0


def test_la_contrasena_no_puede_cerrar_el_bloque_do(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # El CREATE ROLE vive dentro de DO $$ ... $$: un "$$" en la contrasena
    # cerraria el bloque antes de tiempo.
    monkeypatch.setenv("APP_DB_PASSWORD", "abc$$; DROP ROLE x; --")
    migracion, op = _migracion_con_op_simulado(monkeypatch)

    with pytest.raises(RuntimeError, match="APP_DB_PASSWORD"):
        migracion.upgrade()

    assert op.execute.call_count == 0


@pytest.mark.parametrize("variable", CREDENCIALES)
def test_ninguna_credencial_tiene_default_en_compose(variable: str) -> None:
    for compose in sorted(REPO_ROOT.glob("docker-compose*.yml")):
        texto = compose.read_text(encoding="utf-8")
        usos = re.findall(r"\$\{" + variable + r"(?P<resto>[^}]*)\}", texto)
        for resto in usos:
            assert resto.startswith(":?"), (
                f"{compose.name}: {variable} con {resto!r} resuelve sin la "
                "variable; tiene que ser la forma :? con mensaje"
            )


@pytest.mark.parametrize("variable", CREDENCIALES)
def test_cada_credencial_esta_documentada_en_el_env_de_ejemplo(variable: str) -> None:
    ejemplo = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    assert f"\n{variable}=" in ejemplo, (
        f"{variable} no esta en .env.example: quien copie el ejemplo no sabe "
        "que tiene que definirla"
    )


def test_ningun_default_publicado_vive_en_la_app_ni_en_la_config() -> None:
    candidatos = [
        *REPO_ROOT.glob("docker-compose*.yml"),
        REPO_ROOT / ".env.example",
        BACKEND_ROOT / ".env.production.example",
        *(
            ruta
            for ruta in BACKEND_ROOT.rglob("*.py")
            if "tests" not in ruta.relative_to(BACKEND_ROOT).parts
            and ".venv" not in ruta.relative_to(BACKEND_ROOT).parts
        ),
    ]
    con_default = [
        f"{ruta.relative_to(REPO_ROOT)}: {publicado}"
        for ruta in candidatos
        if ruta.is_file()
        for publicado in DEFAULTS_PUBLICADOS
        if publicado in ruta.read_text(encoding="utf-8")
    ]
    assert not con_default, f"credenciales publicadas todavia en el repo: {con_default}"
