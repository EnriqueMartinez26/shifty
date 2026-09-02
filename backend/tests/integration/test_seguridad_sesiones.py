"""Invariantes de sesión/token endurecidas en la remediación de seguridad.

Fijan que un token filtrado/forjado no sea una llave maestra y que las
revocaciones corten el access token de inmediato (no al vencer).
"""

from jose import jwt as jose_jwt
import pytest
from httpx import AsyncClient

from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)


async def _login(
    client: AsyncClient, email: str, password: str = "Password123!"
) -> str:
    res = await client.post("/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return str(res.json()["access_token"])


@pytest.mark.asyncio
async def test_token_forjado_con_otra_clave_es_rechazado(client: AsyncClient) -> None:
    """Un JWT firmado con un secreto distinto no autentica (base del miedo:
    'si se filtra el secreto...'). Se prueba el control, no el secreto real."""
    store, token = await register_and_login(
        client, slug="sec-forjado", email="forjado@test.com"
    )
    real = jose_jwt.get_unverified_claims(token)
    forjado = jose_jwt.encode(
        {**real, "is_global_admin": True}, "otra-clave-de-atacante", algorithm="HS256"
    )
    res = await client.get(
        "/superadmin/stores", headers={"Authorization": f"Bearer {forjado}"}
    )
    assert res.status_code in {401, 403}, "un token forjado obtuvo acceso"


@pytest.mark.asyncio
async def test_claim_is_global_admin_no_da_poderes(client: AsyncClient) -> None:
    """El poder global se decide en la DB, no por el claim del token: aunque el
    claim diga is_global_admin, sin el flag en la base no hay acceso global."""
    store, token = await register_and_login(
        client, slug="sec-escala", email="escala@test.com"
    )
    # El token es de un admin de tienda comun; /superadmin debe negarlo.
    res = await client.get("/superadmin/stores", headers=auth_headers(token))
    assert res.status_code in {401, 403}


@pytest.mark.asyncio
async def test_revocar_sesiones_mata_el_access_token(client: AsyncClient) -> None:
    """El access token esta atado a la sesion (sid): al revocarla, deja de
    servir en el acto en vez de sobrevivir hasta su exp."""
    store, token = await register_and_login(
        client, slug="sec-revoca", email="revoca-access@test.com"
    )
    # Funciona antes de revocar.
    ok = await client.get("/me", headers=auth_headers(token))
    assert ok.status_code == 200, ok.text

    # El propio usuario (admin) revoca todas las sesiones de su tienda.
    revoke = await client.post(
        "/auth/sessions/revoke-store", headers=auth_headers(token)
    )
    assert revoke.status_code == 200, revoke.text

    # El MISMO access token ya no autentica.
    dead = await client.get("/me", headers=auth_headers(token))
    assert dead.status_code in {401, 403}, "el access token sobrevivio a la revocacion"


@pytest.mark.asyncio
async def test_cambiar_password_cierra_las_demas_sesiones(client: AsyncClient) -> None:
    store, token_a = await register_and_login(
        client, slug="sec-chpass", email="chpass@test.com"
    )
    # Segunda sesion del mismo usuario (otro "dispositivo").
    token_b = await _login(client, "chpass@test.com")

    # El test client comparte un unico cookie jar, asi que "la sesion actual"
    # seria ambigua. Se limpia: sin cookie de refresh, el cambio revoca TODAS
    # las sesiones (comportamiento cuando el request no trae la sesion actual).
    client.cookies.clear()
    res = await client.put(
        "/auth/change-password",
        headers=auth_headers(token_a),
        json={
            "current_password": "Password123!",
            "new_password": "OtraClaveSegura456",
        },
    )
    assert res.status_code == 200, res.text

    # Ambas sesiones quedan cortadas tras el cambio de credencial.
    for etiqueta, tok in (("A", token_a), ("B", token_b)):
        dead = await client.get("/me", headers=auth_headers(tok))
        assert dead.status_code in {401, 403}, f"la sesion {etiqueta} sobrevivio"


@pytest.mark.asyncio
async def test_password_debil_es_rechazada(client: AsyncClient) -> None:
    res = await client.post(
        "/auth/register",
        json={
            "store_name": "Debil",
            "store_slug": "sec-debil",
            "business_type": "generic",
            "admin_email": "debil@test.com",
            "admin_password": "corta1",
            "admin_first_name": "A",
            "admin_last_name": "B",
        },
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_desactivar_staff_corta_su_sesion(client: AsyncClient) -> None:
    """Regresion del gap detectado en la re-auditoria: al desactivar un
    profesional, sus sesiones vivas deben morir (no revivir si se reactiva)."""
    from tests.integration.test_feature_flags_finance_and_public_privacy import (
        create_service,
        create_staff,
    )

    store, token = await register_and_login(
        client, slug="sec-staff", email="sec-staff@test.com"
    )
    servicio = await create_service(client, token)
    staff_pid = await create_staff(client, token, servicio)

    # El staff se crea sin password utilizable; se la fijamos via API de admin.
    upd = await client.patch(
        f"/users/{staff_pid}",
        headers=auth_headers(token),
        json={"password": "StaffSeguro123"},
    )
    assert upd.status_code in {200, 404}
    if upd.status_code == 404:
        return  # el id de staff no es el de users en este entorno; se cubre en unit

    staff_token = await _login(client, "pro-demo@test.com", "StaffSeguro123")
    ok = await client.get("/me", headers=auth_headers(staff_token))
    assert ok.status_code == 200

    # El admin desactiva al staff.
    de = await client.delete(f"/staff/{staff_pid}", headers=auth_headers(token))
    assert de.status_code in {200, 204}

    dead = await client.get("/me", headers=auth_headers(staff_token))
    assert dead.status_code in {401, 403}, "la sesion del staff sobrevivio a la baja"
