"""Contrato de `.env.example`: es el perfil de DESARROLLO y no se contradice.

Defecto real (2026-09-17, C-09 de la auditoria): `.env.example`
declaraba `FIELD_ENCRYPTION_KEY` dos veces (linea 10 vacia, linea 49 con el
placeholder `change_this_to_a_32_char_minimum_secret`) y fijaba
`ENV=production`. Sintoma: `cp .env.example .env && make dev` levantaba el
stack en modo produccion y `core/config.py` abortaba por el placeholder de
la linea 49 -- no por la linea 10 que el comentario de la 8 anuncia. Gana
la ultima asignacion, asi que el comentario describia una clave que ya no
era la efectiva.

El perfil de produccion vive en `backend/.env.production.example`.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
ENV_EXAMPLE = REPO_ROOT / ".env.example"


def _assignments() -> list[tuple[str, str]]:
    pares: list[tuple[str, str]] = []
    for linea in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        limpia = linea.strip()
        if not limpia or limpia.startswith("#") or "=" not in limpia:
            continue
        clave, valor = limpia.split("=", 1)
        pares.append((clave.strip(), valor.strip()))
    return pares


def test_ninguna_clave_se_declara_dos_veces() -> None:
    vistas: dict[str, str] = {}
    duplicadas: dict[str, tuple[str, str]] = {}
    for clave, valor in _assignments():
        if clave in vistas:
            duplicadas[clave] = (vistas[clave], valor)
        vistas[clave] = valor
    assert not duplicadas, (
        "`.env.example` declara claves dos veces (gana la ultima y el "
        f"comentario de la primera miente): {sorted(duplicadas)}"
    )


def test_el_ejemplo_es_el_perfil_de_desarrollo() -> None:
    valores = dict(_assignments())
    assert valores.get("ENV") == "development", (
        "`.env.example` es el perfil de desarrollo; el de produccion es "
        f"backend/.env.production.example. ENV={valores.get('ENV')!r}"
    )


# --- Las dos URLs de base (AUD2-C-03, 2026-09-19) ----------------------------
#
# alembic/env.py migra con `MIGRATION_DATABASE_URL or DATABASE_URL`, y la
# segunda tiene default None. El ejemplo de produccion documentaba solo
# DATABASE_URL, y ahi el USER es el rol shifty_app: siguiendo ese archivo,
# `alembic upgrade head` corre sin DDL y falla en CREATE EXTENSION / CREATE
# ROLE. Y si el operador pone el rol dueno en DATABASE_URL para que las
# migraciones pasen, la API se niega a arrancar (_assert_rls_capable_role). O
# sea: con lo documentado, o no migras o no arranca.

PRODUCCION = REPO_ROOT / "backend" / ".env.production.example"


def _claves(ruta: Path) -> set[str]:
    claves = set()
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        limpia = linea.strip()
        if limpia and not limpia.startswith("#") and "=" in limpia:
            claves.add(limpia.split("=", 1)[0].strip())
    return claves


def test_el_ejemplo_de_produccion_documenta_las_dos_urls_de_base() -> None:
    claves = _claves(PRODUCCION)
    for variable in ("DATABASE_URL", "MIGRATION_DATABASE_URL"):
        assert variable in claves, (
            f"{variable} no esta en backend/.env.production.example: un despliegue "
            "que copie ese archivo no puede migrar y arrancar a la vez"
        )


def test_el_ejemplo_de_produccion_explica_por_que_son_dos_roles() -> None:
    texto = PRODUCCION.read_text(encoding="utf-8")
    assert "DDL" in texto, "no dice por que las migraciones necesitan otro rol"
    assert "shifty_app" in texto
