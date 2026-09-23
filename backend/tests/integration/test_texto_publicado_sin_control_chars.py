"""El texto de tienda y de personal que se publica en el portal no lleva invisibles.

Auditoria B3-15, 2026-09-16 (decision del 2026-09-18). Sintoma:
``reject_control_chars`` solo se aplicaba a la entrada anonima (turnos, reserva
publica, lista de espera). Un admin podia guardar en el nombre o la descripcion
de la tienda, en el nombre visible del personal o en las etiquetas de los campos
del formulario de reserva un U+202E o un zero-width que despues se servian tal
cual en el portal: spoofing visual tipo Trojan Source.

Decision: la regla 19 se lee como "texto que se publica", sin importar quien lo
tipeo. Se valida al ESCRIBIR (422, sin persistir), como B6-01 con los
servicios: los validadores van en los schemas de entrada y no en bases que
heredan las respuestas, asi una fila legada con un invisible se sigue leyendo
(sin 500) y un PATCH que no toca ese campo sigue funcionando.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, cast

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.staff.model import StaffBlock
from modules.stores.model import Store
from modules.users.model import User
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)

JsonDict = dict[str, Any]

VENENOS = [
    pytest.param("Nombre " + chr(0x202E) + "otracosa", id="bidi-override"),
    pytest.param("Nom" + chr(0x200B) + "bre", id="zero-width"),
]


def _campo_formulario(**sobre: Any) -> JsonDict:
    campo: JsonDict = {"key": "obra_social", "label": "Obra social", "type": "text"}
    campo.update(sobre)
    return campo


TIENDA = [
    pytest.param(lambda v: {"name": v}, id="name"),
    pytest.param(lambda v: {"description": v}, id="description"),
    pytest.param(lambda v: {"whatsapp_number": v}, id="whatsapp_number"),
    pytest.param(lambda v: {"deposit_policy": v}, id="deposit_policy"),
    pytest.param(
        lambda v: {"custom_client_fields": [_campo_formulario(label=v)]},
        id="custom-label",
    ),
    pytest.param(
        lambda v: {"custom_client_fields": [_campo_formulario(help_text=v)]},
        id="custom-help",
    ),
    pytest.param(
        lambda v: {
            "custom_client_fields": [
                _campo_formulario(
                    type="select", options=[{"label": v, "value": "osde"}]
                )
            ]
        },
        id="custom-option",
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("veneno", VENENOS)
@pytest.mark.parametrize("cuerpo", TIENDA)
async def test_patch_de_la_tienda_rechaza_invisibles(
    client: AsyncClient, test_session: AsyncSession, veneno: str, cuerpo: Any
) -> None:
    _, token = await register_and_login(
        client, slug="texto-tienda", email="texto-tienda@test.com"
    )
    res = await client.patch(
        "/stores/me", headers=auth_headers(token), json=cuerpo(veneno)
    )
    assert res.status_code == 422, res.text

    test_session.expire_all()
    tienda = (
        await test_session.execute(select(Store).where(Store.slug == "texto-tienda"))
    ).scalar_one()
    guardado = " ".join(
        str(valor or "")
        for valor in (
            tienda.name,
            tienda.description,
            tienda.whatsapp_number,
            tienda.deposit_policy,
            tienda.custom_client_fields,
        )
    )
    assert veneno not in guardado


@pytest.mark.asyncio
@pytest.mark.parametrize("veneno", VENENOS)
@pytest.mark.parametrize("campo", ["display_name", "first_name", "last_name"])
async def test_alta_y_edicion_de_personal_rechazan_invisibles(
    client: AsyncClient, veneno: str, campo: str
) -> None:
    _, token = await register_and_login(
        client, slug="texto-staff", email="texto-staff@test.com"
    )
    servicio = await create_service(client, token)
    alta: JsonDict = {
        "display_name": "Pro Uno",
        "first_name": "Pro",
        "last_name": "Uno",
        "email": "pro-uno@test.com",
        "service_ids": [servicio],
        campo: veneno,
    }
    res = await client.post("/staff/", headers=auth_headers(token), json=alta)
    assert res.status_code == 422, res.text

    profesional = await create_staff(client, token, servicio)
    edicion = await client.put(
        f"/staff/{profesional}", headers=auth_headers(token), json={campo: veneno}
    )
    assert edicion.status_code == 422, edicion.text


@pytest.mark.asyncio
@pytest.mark.parametrize("veneno", VENENOS)
async def test_el_superadmin_tampoco_publica_invisibles_en_el_nombre(
    client: AsyncClient, test_session: AsyncSession, veneno: str
) -> None:
    tienda_pid, token = await register_and_login(
        client, slug="texto-sa", email="texto-sa@test.com"
    )
    superadmin = (
        await test_session.execute(
            select(User).where(User.email == "texto-sa@test.com")
        )
    ).scalar_one()
    superadmin.is_global_admin = True
    await test_session.commit()
    headers = auth_headers(token)

    alta = await client.post(
        "/superadmin/stores",
        headers=headers,
        json={"name": veneno, "slug": "tienda-envenenada"},
    )
    assert alta.status_code == 422, alta.text

    edicion = await client.patch(
        f"/superadmin/stores/{tienda_pid}", headers=headers, json={"name": veneno}
    )
    assert edicion.status_code == 422, edicion.text


@pytest.mark.asyncio
async def test_el_texto_normal_con_acentos_y_saltos_sigue_entrando(
    client: AsyncClient,
) -> None:
    _, token = await register_and_login(
        client, slug="texto-normal", email="texto-normal@test.com"
    )
    res = await client.patch(
        "/stores/me",
        headers=auth_headers(token),
        json={
            "name": "Peluquería Ñandú",
            "description": "Cortes y color.\nAtendemos con turno.",
            "custom_client_fields": [
                _campo_formulario(label="¿Tenés obra social?", help_text="Opcional")
            ],
        },
    )
    assert res.status_code == 200, res.text
    assert res.json()["name"] == "Peluquería Ñandú"


@pytest.mark.asyncio
async def test_una_tienda_legada_con_invisibles_se_sigue_leyendo_y_editando(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """Validar al escribir, no al leer: nada de 500 para datos viejos."""
    _, token = await register_and_login(
        client, slug="texto-legado", email="texto-legado@test.com"
    )
    tienda = (
        await test_session.execute(select(Store).where(Store.slug == "texto-legado"))
    ).scalar_one()
    # description y los campos del formulario viven en theme_config (JSON):
    # se escriben ahi, como quedaria una fila guardada antes de la guarda.
    tienda.theme_config = {
        **(tienda.theme_config or {}),
        "description": "Legado" + chr(0x200B) + "invisible",
        "custom_client_fields": [
            _campo_formulario(label="Obra" + chr(0x202E) + "social")
        ],
    }
    await test_session.commit()

    panel = await client.get("/stores/me", headers=auth_headers(token))
    assert panel.status_code == 200, panel.text
    portal = await client.get("/public/stores/texto-legado")
    assert portal.status_code == 200, portal.text

    # Un PATCH que no toca esos campos no se bloquea por el dato viejo.
    otro = await client.patch(
        "/stores/me", headers=auth_headers(token), json={"cancellation_hours": 12}
    )
    assert otro.status_code == 200, otro.text
    assert cast(JsonDict, otro.json())["cancellation_hours"] == 12


# ---------------------------------------------------------------------------
# Bloqueos de agenda (AUD2-B1-11, 2026-09-20)
# ---------------------------------------------------------------------------
#
# El ``reason`` de un bloqueo lo tipea un admin y se publica en tres lados: la
# respuesta de disponibilidad (``availability`` lo devuelve como motivo del
# slot), el listado del panel y el cuerpo del mail de cancelacion en bloque.
# Ninguno de los tres schemas pasaba por ``reject_payload_control_chars``, asi
# que un U+202E o un zero-width llegaba al portal y al mail del cliente. Mismo
# criterio que la tienda y el personal: se valida al ESCRIBIR, con 422 y sin
# persistir.


async def _tienda_con_profesional(
    client: AsyncClient, slug: str
) -> tuple[str, str, str]:
    _, token = await register_and_login(client, slug=slug, email=f"{slug}@test.com")
    servicio = await create_service(client, token)
    profesional = await create_staff(client, token, servicio)
    return token, servicio, profesional


def _rango() -> tuple[str, str]:
    inicio = datetime.now(timezone.utc) + timedelta(days=5)
    return inicio.isoformat(), (inicio + timedelta(hours=1)).isoformat()


@pytest.mark.asyncio
@pytest.mark.parametrize("veneno", VENENOS)
async def test_el_motivo_de_un_bloqueo_rechaza_invisibles(
    client: AsyncClient, test_session: AsyncSession, veneno: str
) -> None:
    token, _servicio, profesional = await _tienda_con_profesional(
        client, "texto-bloqueo"
    )
    headers = auth_headers(token)
    starts_at, ends_at = _rango()
    base: JsonDict = {
        "staff_id": profesional,
        "starts_at": starts_at,
        "ends_at": ends_at,
    }

    alta = await client.post(
        "/appointment-blocks/", headers=headers, json={**base, "reason": veneno}
    )
    assert alta.status_code == 422, alta.text

    cierre = await client.post(
        "/appointment-blocks/store-wide",
        headers=headers,
        json={"starts_at": starts_at, "ends_at": ends_at, "reason": veneno},
    )
    assert cierre.status_code == 422, cierre.text

    lote = await client.post(
        "/appointment-blocks/batch",
        headers=headers,
        json={**base, "reason": veneno, "recurrence": "none"},
    )
    assert lote.status_code == 422, lote.text

    limpio = await client.post(
        "/appointment-blocks/", headers=headers, json={**base, "reason": "Tramite"}
    )
    assert limpio.status_code == 201, limpio.text
    edicion = await client.patch(
        f"/appointment-blocks/{limpio.json()['public_id']}",
        headers=headers,
        json={"reason": veneno},
    )
    assert edicion.status_code == 422, edicion.text

    test_session.expire_all()
    motivos = (await test_session.execute(select(StaffBlock.reason))).scalars().all()
    assert all(veneno not in (m or "") for m in motivos), motivos


@pytest.mark.asyncio
async def test_el_motivo_normal_de_un_bloqueo_sigue_entrando(
    client: AsyncClient,
) -> None:
    token, _servicio, profesional = await _tienda_con_profesional(
        client, "texto-bloqueo-ok"
    )
    starts_at, ends_at = _rango()
    res = await client.post(
        "/appointment-blocks/",
        headers=auth_headers(token),
        json={
            "staff_id": profesional,
            "starts_at": starts_at,
            "ends_at": ends_at,
            "reason": "Turno médico\nde la mañana",
        },
    )
    assert res.status_code == 201, res.text
    assert res.json()["reason"] == "Turno médico\nde la mañana"
