"""Los CHECK de la terna de sena frenan aunque el codigo se equivoque (AUD2-B6-03).

2026-09-20. La terna ``deposit_mode``/``deposit_type``/``deposit_amount`` se
validaba SOLO en la entrada (Pydantic). Lo que toca dinero se garantiza en
Postgres:

- ``ck_services_deposit_percent_max``: un porcentaje mayor a 100 cobraba
  5 veces el precio por adelantado (fila vieja con ``percent`` = 500).
- ``ck_services_deposit_amount_presente``: ``required`` sin monto reservaba
  sin cobrar, y ``optional`` sin monto ofrecia una sena de 0.

El tercer camino es concurrente y por eso vive aca y no en SQLite: dos PATCH
sobre el mismo servicio leen la fila SIN lock, cada uno valida contra el
snapshot que vio y el ultimo escribe encima. Ej.: fila
``('none','percent',null)``; A manda ``{mode:'required', amount:30}`` (valido)
y B manda ``{amount:null}`` (valido contra la fila vieja); el resultado seria
``('required','percent',null)``, una sena obligatoria que no cobra. El modulo
de servicios no tiene capa de service donde tomar el lock, asi que la guarda
correcta es el CHECK: la escritura perdedora falla con IntegrityError y sale
como 409 neutro, nunca como una fila invalida.

Se escribe SQL crudo con el rol dueno (superusuario: salta RLS pero no los
constraints) para simular un bug o una carga directa a la base.
"""

import asyncio
import os
from pathlib import Path

import pytest
import ulid
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.postgres.conftest import auth_headers, register_and_login

pytestmark = pytest.mark.postgres

RAFAGA = int(os.getenv("TEST_POSTGRES_RAFAGA", "25"))

_INSERT = text(
    "INSERT INTO services ("
    "  id, public_id, store_id, name, duration_minutes, price,"
    "  deposit_mode, deposit_type, deposit_amount, is_active,"
    "  created_at, updated_at"
    ") VALUES ("
    "  :sid, :sid, :store, 'Corte', 30, 10000,"
    "  :mode, :tipo, :monto, true, now(), now()"
    ")"
)


async def _insertar(
    owner_engine: AsyncEngine, store_id: str, mode: str, tipo: str, monto: float | None
) -> None:
    async with owner_engine.begin() as conn:
        await conn.execute(
            _INSERT,
            {
                "sid": str(ulid.ULID()),
                "store": store_id,
                "mode": mode,
                "tipo": tipo,
                "monto": monto,
            },
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "tipo", "monto", "constraint"),
    [
        ("required", "percent", 500, "ck_services_deposit_percent_max"),
        ("optional", "percent", 101, "ck_services_deposit_percent_max"),
        ("required", "percent", None, "ck_services_deposit_amount_presente"),
        ("required", "fixed", 0, "ck_services_deposit_amount_presente"),
        ("optional", "fixed", None, "ck_services_deposit_amount_presente"),
    ],
)
async def test_la_base_rechaza_una_terna_de_sena_imposible(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
    mode: str,
    tipo: str,
    monto: float | None,
    constraint: str,
) -> None:
    store, _ = await register_and_login(
        client, app_sessions, slug=f"pg-sena-{mode}-{tipo}", email=f"pg-{mode}@demo.com"
    )
    with pytest.raises(IntegrityError, match=constraint):
        await _insertar(owner_engine, store, mode, tipo, monto)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "tipo", "monto"),
    [
        ("none", "percent", None),
        ("required", "full", None),
        ("required", "percent", 100),
        ("optional", "fixed", 0.01),
    ],
)
async def test_las_ternas_validas_siguen_entrando(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
    mode: str,
    tipo: str,
    monto: float | None,
) -> None:
    """El CHECK no puede rechazar nada que el schema de entrada acepta."""
    store, _ = await register_and_login(
        client,
        app_sessions,
        slug=f"pg-sena-ok-{mode}-{tipo}",
        email=f"pg-ok-{mode}-{tipo}@demo.com",
    )
    await _insertar(owner_engine, store, mode, tipo, monto)
    async with owner_engine.begin() as conn:
        total = await conn.execute(
            text("SELECT count(*) FROM services WHERE store_id = :s"), {"s": store}
        )
    assert total.scalar_one() == 1


@pytest.mark.asyncio
async def test_rafaga_de_patch_sobre_la_sena_no_deja_ninguna_fila_invalida(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    """Dos PATCH concurrentes no pueden componer una terna imposible."""
    _store, token = await register_and_login(
        client, app_sessions, slug="pg-sena-rafaga", email="pg-sena-rafaga@demo.com"
    )
    alta = await client.post(
        "/services/",
        headers=auth_headers(token),
        json={"name": "Corte", "duration_minutes": 30, "price": 10000},
    )
    assert alta.status_code == 201, alta.text
    servicio = str(alta.json()["public_id"])

    # La mitad activa la sena con monto; la otra mitad borra el monto. Cada
    # uno es valido contra la fila que leyo; combinados son una sena
    # obligatoria sin monto.
    cuerpos = [
        {"deposit_mode": "required", "deposit_type": "percent", "deposit_amount": 30}
        if i % 2 == 0
        else {"deposit_amount": None}
        for i in range(RAFAGA)
    ]
    respuestas = await asyncio.gather(
        *(
            client.patch(
                f"/services/{servicio}", headers=auth_headers(token), json=cuerpo
            )
            for cuerpo in cuerpos
        )
    )
    codigos = [r.status_code for r in respuestas]
    assert all(c < 500 for c in codigos), codigos

    async with owner_engine.begin() as conn:
        invalidas = await conn.execute(
            text(
                "SELECT count(*) FROM services WHERE NOT ("
                "  deposit_mode = 'none' OR deposit_type = 'full'"
                "  OR (deposit_amount IS NOT NULL AND deposit_amount > 0)"
                ") OR NOT ("
                "  deposit_type <> 'percent' OR deposit_amount IS NULL"
                "  OR deposit_amount <= 100"
                ")"
            )
        )
    assert invalidas.scalar_one() == 0


def test_la_migracion_se_detiene_si_ya_hay_filas_invalidas() -> None:
    """La migracion cuenta e informa; no corrige ni borra por nadie.

    Es la misma decision que ``c9e1f3a5b7d9`` con los telefonos repetidos:
    cuanto cobra cada servicio no lo decide una migracion. Se lee el archivo
    por ruta, como ``test_trigger_matches_python_graph``.
    """
    ruta = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "d1f3b5a7c9e2_check_terna_sena_servicios.py"
    )
    fuente = ruta.read_text(encoding="utf-8")
    assert 'down_revision: Union[str, Sequence[str], None] = "c5e7a9b1d3f4"' in fuente
    assert "raise RuntimeError(" in fuente
    assert "deposit_amount > 0" in fuente
    assert "deposit_amount <= 100" in fuente
    # Ni borra ni corrige filas.
    for prohibido in ("DELETE FROM services", "UPDATE services", "op.execute("):
        assert prohibido not in fuente
