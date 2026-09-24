"""Top de consultas de ``pg_stat_statements`` (F5-03, R7-04, R11-14).

2026-09-24. La extension ya se precarga y se crea por migracion, pero nadie la
leia: los EXPLAIN de ``tests/postgres`` dicen que indice PUEDE usar una
consulta, no cuanto pesa con el trafico real. ``scripts/pg_top_queries.py``
imprime las 20 que mas tiempo total y mas tiempo medio consumen, con llamadas
y filas, y lo corre un cron semanal (``deploy/cron/shifty-pg-top``).

Se conecta con el rol DUENO (la vista necesita ``pg_read_all_stats`` o
superusuario; ``shifty_app`` solo veria sus propias sentencias y con el texto
tapado) y nunca imprime la URL con credenciales.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from tests.unit.host_falso import _lineas_de_cron

BACKEND_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = BACKEND_ROOT / "scripts" / "pg_top_queries.py"

URL_DUENO = (
    "postgresql+asyncpg://shifty_user:clave-del-dueno@db:5432/shifty_db?ssl=disable"
)
URL_RLS = (
    "postgresql+asyncpg://shifty_app:clave-de-la-app@db:5432/shifty_db?ssl=disable"
)


def _modulo() -> ModuleType:
    spec = importlib.util.spec_from_file_location("pg_top_queries", SCRIPT)
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modulo
    spec.loader.exec_module(modulo)
    return modulo


def _fila(n: int, *, total: float, media: float) -> tuple[Any, ...]:
    return (
        1000 + n,
        n * 10,
        total,
        media,
        n * 3,
        f"SELECT *\n  FROM   appointments WHERE store_id = $1 -- consulta {n}",
    )


class CursorFalso:
    """Cursor DB-API minimo: devuelve filas por orden de ejecucion."""

    def __init__(self, respuestas: list[list[tuple[Any, ...]]]) -> None:
        self.respuestas = respuestas
        self.ejecutadas: list[tuple[str, Any]] = []
        self._actual: list[tuple[Any, ...]] = []

    def execute(self, sql: str, params: Any = None) -> None:
        self.ejecutadas.append((sql, params))
        self._actual = self.respuestas.pop(0) if self.respuestas else []

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._actual

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._actual[0] if self._actual else None


@pytest.mark.parametrize(
    ("entorno", "esperada"),
    [
        ({"MIGRATION_DATABASE_URL": URL_DUENO, "DATABASE_URL": URL_RLS}, URL_DUENO),
        (
            {
                "BACKUP_DATABASE_URL": URL_DUENO,
                "MIGRATION_DATABASE_URL": "postgresql://otro:x@h:5432/b",
            },
            URL_DUENO,
        ),
        ({"DATABASE_URL": URL_RLS}, ""),
    ],
    ids=["migracion", "backup-gana", "solo-rls"],
)
def test_toma_la_url_del_dueno_y_nunca_database_url(
    entorno: dict[str, str], esperada: str
) -> None:
    assert _modulo()._owner_url(entorno) == esperada


def test_rechaza_el_rol_de_la_app_sin_imprimir_la_clave(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    modulo = _modulo()
    monkeypatch.setattr(
        modulo, "_connect", lambda _url: pytest.fail("no debe conectar")
    )
    monkeypatch.delenv("APP_DB_USER", raising=False)
    monkeypatch.setenv("DATABASE_URL", URL_RLS)

    with pytest.raises(SystemExit) as salida:
        modulo.main(["--database-url", URL_RLS])

    assert "clave-de-la-app" not in str(salida.value)
    assert "rol de la app" in str(salida.value)
    assert "clave-de-la-app" not in capsys.readouterr().out


def test_sin_url_del_dueno_falla_con_el_motivo(monkeypatch: pytest.MonkeyPatch) -> None:
    modulo = _modulo()
    for variable in ("BACKUP_DATABASE_URL", "MIGRATION_DATABASE_URL"):
        monkeypatch.delenv(variable, raising=False)

    with pytest.raises(SystemExit) as salida:
        modulo.main([])

    assert "MIGRATION_DATABASE_URL" in str(salida.value)


def test_el_reporte_ordena_por_total_y_por_media_con_llamadas_y_filas() -> None:
    modulo = _modulo()
    por_total = [_fila(1, total=9000.0, media=3.0), _fila(2, total=800.0, media=80.0)]
    por_media = [_fila(2, total=800.0, media=80.0), _fila(1, total=9000.0, media=3.0)]
    cursor = CursorFalso([[(10_000.0, 5000)], por_total, por_media])

    reporte = modulo.recolectar(cursor, limite=20)
    texto = modulo.formatear(reporte, destino="postgresql://***@db:5432/shifty_db")

    sql_total, params_total = cursor.ejecutadas[1]
    sql_media, params_media = cursor.ejecutadas[2]
    assert "order by s.total_exec_time desc" in " ".join(sql_total.lower().split())
    assert "order by s.mean_exec_time desc" in " ".join(sql_media.lower().split())
    assert params_total == params_media == (20,)
    assert "current_database()" in sql_total, "solo la base de la app, no otras"

    assert "total_exec_time" in texto and "mean_exec_time" in texto
    assert texto.index("consulta 1") < texto.index("consulta 2"), "por total: 1 antes"
    seccion_media = texto[texto.index("mean_exec_time") :]
    assert seccion_media.index("consulta 2") < seccion_media.index("consulta 1")
    # llamadas y filas de la consulta 2 (20 llamadas, 6 filas), y su peso.
    assert " 20 " in texto and " 6 " in texto
    assert "90.0%" in texto, "9000 de 10000 ms totales"
    # El texto sale en una linea, sin los saltos ni los espacios del ORM.
    assert "SELECT * FROM appointments WHERE store_id = $1" in texto
    assert "***@db:5432/shifty_db" in texto


def test_una_consulta_larga_se_recorta() -> None:
    modulo = _modulo()
    larga = (1, 1, 1.0, 1.0, 1, "SELECT " + "x, " * 400)
    cursor = CursorFalso([[(1.0, 1)], [larga], [larga]])

    texto = modulo.formatear(modulo.recolectar(cursor, limite=5), destino="d")

    assert max(len(linea) for linea in texto.splitlines()) < 260


def test_reset_limpia_las_estadisticas_despues_de_leerlas() -> None:
    modulo = _modulo()
    cursor = CursorFalso([[(1.0, 1)], [], [], []])

    modulo.recolectar(cursor, limite=20)
    modulo.reiniciar(cursor)

    assert "pg_stat_statements_reset()" in cursor.ejecutadas[-1][0]


def test_sin_la_extension_sale_con_un_mensaje_claro(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    modulo = _modulo()

    class SinVista(CursorFalso):
        def execute(self, sql: str, params: Any = None) -> None:
            raise modulo.ErrorDeBase('relation "pg_stat_statements" does not exist')

    class Conexion:
        autocommit = False

        def cursor(self) -> SinVista:
            return SinVista([])

        def close(self) -> None:
            pass

    monkeypatch.setattr(modulo, "_connect", lambda _url: Conexion())
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(SystemExit) as salida:
        modulo.main(["--database-url", URL_DUENO])

    assert "pg_stat_statements" in str(salida.value)
    assert "clave-del-dueno" not in str(salida.value)


def test_cron_semanal_dentro_del_contenedor_del_backend() -> None:
    lineas = _lineas_de_cron("shifty-pg-top")
    linea = next(ll for ll in lineas if "pg_top_queries.py" in ll)
    campos = linea.split()
    assert campos[2:5] == ["*", "*", "1"], "una vez por semana, el lunes"
    assert campos[5] == "root"
    assert "docker compose exec -T backend" in linea
    assert ".deploy/current" in linea, "compose de prod exige APP_VERSION"
    assert ">> /var/log/shifty/pg-top.log" in linea, "logrotate cubre *.log"
