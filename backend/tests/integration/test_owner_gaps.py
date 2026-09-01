"""Huecos de la operatoria del dueno de tienda.

Cubre lo que un negocio real necesita y no estaba: corregir horarios mal
cargados, cerrar la tienda un feriado y avisarle al cliente por un canal que
efectivamente lea.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, cast

import pytest
from httpx import AsyncClient

from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)


async def _staff(client: AsyncClient, token: str) -> str:
    servicio = await create_service(client, token)
    return await create_staff(client, token, servicio)


# ---------------------------------------------------------------------------
# Horarios del personal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_un_horario_mal_cargado_se_puede_corregir(client: AsyncClient) -> None:
    """Antes solo existia el alta: un error era permanente."""
    _, token = await register_and_login(
        client, slug="horario-editar", email="hor-editar@test.com"
    )
    staff = await _staff(client, token)

    alta = await client.post(
        f"/staff/{staff}/schedules",
        headers=auth_headers(token),
        json={"day_of_week": 1, "start_time": "09:00:00", "end_time": "18:00:00"},
    )
    assert alta.status_code == 200, alta.text
    horario = cast(str, alta.json()["public_id"])

    correccion = await client.patch(
        f"/staff/{staff}/schedules/{horario}",
        headers=auth_headers(token),
        json={"end_time": "13:00:00"},
    )
    assert correccion.status_code == 200, correccion.text
    assert correccion.json()["end_time"] == "13:00:00"


@pytest.mark.asyncio
async def test_un_horario_se_puede_eliminar(client: AsyncClient) -> None:
    _, token = await register_and_login(
        client, slug="horario-borrar", email="hor-borrar@test.com"
    )
    staff = await _staff(client, token)

    alta = await client.post(
        f"/staff/{staff}/schedules",
        headers=auth_headers(token),
        json={"day_of_week": 2, "start_time": "10:00:00", "end_time": "14:00:00"},
    )
    horario = cast(str, alta.json()["public_id"])

    baja = await client.delete(
        f"/staff/{staff}/schedules/{horario}", headers=auth_headers(token)
    )
    assert baja.status_code == 204, baja.text

    detalle = await client.get(f"/staff/{staff}", headers=auth_headers(token))
    assert all(h["public_id"] != horario for h in detalle.json().get("schedules", []))


@pytest.mark.asyncio
async def test_no_se_pueden_cargar_franjas_superpuestas(client: AsyncClient) -> None:
    """Los duplicados mostraban cada horario repetido en el booking publico."""
    _, token = await register_and_login(
        client, slug="horario-solapa", email="hor-solapa@test.com"
    )
    staff = await _staff(client, token)

    base = await client.post(
        f"/staff/{staff}/schedules",
        headers=auth_headers(token),
        json={"day_of_week": 3, "start_time": "09:00:00", "end_time": "13:00:00"},
    )
    assert base.status_code == 200, base.text

    for inicio, fin, caso in [
        ("09:00:00", "13:00:00", "duplicado exacto"),
        ("12:00:00", "15:00:00", "solapa el final"),
        ("08:00:00", "10:00:00", "solapa el inicio"),
        ("10:00:00", "11:00:00", "contenido dentro"),
    ]:
        res = await client.post(
            f"/staff/{staff}/schedules",
            headers=auth_headers(token),
            json={"day_of_week": 3, "start_time": inicio, "end_time": fin},
        )
        assert res.status_code == 422, f"{caso} fue aceptado ({res.status_code})"


@pytest.mark.asyncio
async def test_la_siesta_sigue_siendo_valida(client: AsyncClient) -> None:
    """Dos franjas separadas el mismo dia son lo normal en Argentina."""
    _, token = await register_and_login(
        client, slug="horario-siesta", email="hor-siesta@test.com"
    )
    staff = await _staff(client, token)

    for inicio, fin in [("09:00:00", "13:00:00"), ("16:00:00", "20:00:00")]:
        res = await client.post(
            f"/staff/{staff}/schedules",
            headers=auth_headers(token),
            json={"day_of_week": 4, "start_time": inicio, "end_time": fin},
        )
        assert res.status_code == 200, f"{inicio}-{fin}: {res.text}"


@pytest.mark.asyncio
async def test_editar_un_horario_no_puede_generar_solapamiento(
    client: AsyncClient,
) -> None:
    _, token = await register_and_login(
        client, slug="horario-edita-solapa", email="hor-edsol@test.com"
    )
    staff = await _staff(client, token)

    manana = await client.post(
        f"/staff/{staff}/schedules",
        headers=auth_headers(token),
        json={"day_of_week": 5, "start_time": "09:00:00", "end_time": "13:00:00"},
    )
    tarde = await client.post(
        f"/staff/{staff}/schedules",
        headers=auth_headers(token),
        json={"day_of_week": 5, "start_time": "16:00:00", "end_time": "20:00:00"},
    )
    assert tarde.status_code == 200

    # Estirar la manana hasta pisar la tarde debe rebotar.
    res = await client.patch(
        f"/staff/{staff}/schedules/{manana.json()['public_id']}",
        headers=auth_headers(token),
        json={"end_time": "17:00:00"},
    )
    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_no_se_puede_tocar_el_horario_de_otra_tienda(
    client: AsyncClient,
) -> None:
    _, token_a = await register_and_login(
        client, slug="horario-tienda-a", email="hor-a@test.com"
    )
    staff_a = await _staff(client, token_a)
    alta = await client.post(
        f"/staff/{staff_a}/schedules",
        headers=auth_headers(token_a),
        json={"day_of_week": 1, "start_time": "09:00:00", "end_time": "12:00:00"},
    )
    horario = cast(str, alta.json()["public_id"])

    _, token_b = await register_and_login(
        client, slug="horario-tienda-b", email="hor-b@test.com"
    )
    res = await client.delete(
        f"/staff/{staff_a}/schedules/{horario}", headers=auth_headers(token_b)
    )
    assert res.status_code == 404, "la tienda B borro un horario de la tienda A"


# ---------------------------------------------------------------------------
# Cierre de toda la tienda
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cerrar_la_tienda_bloquea_a_todo_el_personal(
    client: AsyncClient,
) -> None:
    """Un feriado no puede exigir bloquear empleado por empleado."""
    _, token = await register_and_login(
        client, slug="cierre-feriado", email="feriado@test.com"
    )
    servicio = await create_service(client, token)
    for i in range(2):
        res = await client.post(
            "/staff/",
            headers=auth_headers(token),
            json={
                "display_name": f"Pro {i}",
                "first_name": "Pro",
                "last_name": str(i),
                "email": f"pro{i}-feriado@test.com",
                "service_ids": [servicio],
            },
        )
        assert res.status_code == 201, res.text

    feriado = (datetime.now(timezone.utc) + timedelta(days=10)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    cierre = await client.post(
        "/appointment-blocks/store-wide",
        headers=auth_headers(token),
        json={
            "starts_at": feriado.isoformat(),
            "ends_at": (feriado + timedelta(days=1)).isoformat(),
            "reason": "Feriado nacional",
        },
    )
    assert cierre.status_code == 201, cierre.text
    assert cierre.json()["blocked_staff"] == 2

    listado = await client.get("/appointment-blocks/", headers=auth_headers(token))
    motivos = [b["reason"] for b in listado.json()]
    assert motivos.count("Feriado nacional") == 2


@pytest.mark.asyncio
async def test_un_cierre_con_rango_invertido_se_rechaza(client: AsyncClient) -> None:
    _, token = await register_and_login(
        client, slug="cierre-invertido", email="cierre-inv@test.com"
    )
    ahora = datetime.now(timezone.utc) + timedelta(days=5)
    res = await client.post(
        "/appointment-blocks/store-wide",
        headers=auth_headers(token),
        json={
            "starts_at": ahora.isoformat(),
            "ends_at": (ahora - timedelta(hours=2)).isoformat(),
        },
    )
    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_cerrar_sin_personal_avisa_en_vez_de_fallar(
    client: AsyncClient,
) -> None:
    _, token = await register_and_login(
        client, slug="cierre-sin-staff", email="cierre-sin@test.com"
    )
    ahora = datetime.now(timezone.utc) + timedelta(days=5)
    res = await client.post(
        "/appointment-blocks/store-wide",
        headers=auth_headers(token),
        json={
            "starts_at": ahora.isoformat(),
            "ends_at": (ahora + timedelta(hours=8)).isoformat(),
        },
    )
    assert res.status_code == 422, res.text
    assert "personal" in res.text.lower()


# ---------------------------------------------------------------------------
# Recordatorios multicanal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_el_recordatorio_prefiere_whatsapp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El telefono es obligatorio al reservar; el mail no."""
    import modules.notifications.tasks as tasks

    enviados: list[tuple[str, str]] = []

    async def fake_whatsapp(to: str, body: str) -> bool:
        enviados.append(("whatsapp", to))
        return True

    async def fake_email(to: str, subject: str, body: str) -> bool:
        enviados.append(("email", to))
        return True

    monkeypatch.setattr(tasks, "_send_whatsapp", fake_whatsapp)
    monkeypatch.setattr(tasks, "_send_email", fake_email)

    res = await tasks.notify_client_reminder(
        phone="+5491155512345",
        email="cliente@test.com",
        details={"public_id": "A1", "service": "Corte", "staff": "Pro", "date": "hoy"},
    )
    assert res["channel"] == "whatsapp"
    assert enviados == [("whatsapp", "+5491155512345")], "no debe mandar los dos"


@pytest.mark.asyncio
async def test_sin_whatsapp_el_recordatorio_cae_al_mail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import modules.notifications.tasks as tasks

    async def sin_whatsapp(to: str, body: str) -> bool:
        return False

    async def fake_email(to: str, subject: str, body: str) -> bool:
        return True

    monkeypatch.setattr(tasks, "_send_whatsapp", sin_whatsapp)
    monkeypatch.setattr(tasks, "_send_email", fake_email)

    res = await tasks.notify_client_reminder(
        phone="+5491155512345",
        email="cliente@test.com",
        details={"public_id": "A2", "service": "Corte", "staff": "Pro", "date": "hoy"},
    )
    assert res["channel"] == "email"


@pytest.mark.asyncio
async def test_un_cliente_sin_mail_ni_whatsapp_no_rompe_el_lote(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Antes esto reventaba: se llamaba al mail con None."""
    import modules.notifications.tasks as tasks

    async def sin_whatsapp(to: str, body: str) -> bool:
        return False

    monkeypatch.setattr(tasks, "_send_whatsapp", sin_whatsapp)

    res = await tasks.notify_client_reminder(
        phone="+5491155512345",
        email=None,
        details={"public_id": "A3", "service": "Corte", "staff": "Pro", "date": "hoy"},
    )
    assert res["status"] == "skipped"


@pytest.mark.asyncio
async def test_sin_credenciales_de_twilio_whatsapp_no_intenta_enviar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No puede colgarse llamando a Twilio sin estar configurado."""
    import modules.notifications.tasks as tasks
    from core.config import settings

    monkeypatch.setattr(settings, "TWILIO_ACCOUNT_SID", None)
    monkeypatch.setattr(settings, "TWILIO_AUTH_TOKEN", None)
    monkeypatch.setattr(settings, "TWILIO_WHATSAPP_FROM", None)

    def explotar(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("no deberia abrir un cliente HTTP")

    monkeypatch.setattr("modules.notifications.tasks.httpx.AsyncClient", explotar)

    assert await tasks._send_whatsapp("+5491155512345", "hola") is False


# ---------------------------------------------------------------------------
# Carga del dueno: sin antelacion minima, pero nunca en el pasado
# ---------------------------------------------------------------------------


async def _staff_disponible_hoy(client: AsyncClient, token: str) -> tuple[str, str]:
    """Servicio + staff con horario amplio para HOY, para probar la carga admin."""
    servicio = await create_service(client, token)
    alta = await client.post(
        "/staff/",
        headers=auth_headers(token),
        json={
            "display_name": "Pro Hoy",
            "first_name": "Pro",
            "last_name": "Hoy",
            "email": f"prohoy-{token[-8:]}@test.com",
            "service_ids": [servicio],
        },
    )
    staff = cast(str, alta.json()["public_id"])
    hoy = datetime.now(timezone.utc)
    await client.post(
        f"/staff/{staff}/schedules",
        headers=auth_headers(token),
        json={
            "day_of_week": hoy.weekday(),
            "start_time": "00:00:00",
            "end_time": "23:59:00",
        },
    )
    return servicio, staff


@pytest.mark.asyncio
async def test_el_dueno_puede_cargar_saltando_la_antelacion_minima(
    client: AsyncClient,
) -> None:
    """Un walk-in que llega ahora: el dueño lo carga aunque la tienda pida 2hs.

    La antelacion minima es una regla para el cliente, no para la tienda.
    """
    _, token = await register_and_login(
        client, slug="admin-walkin", email="admin-walkin@test.com"
    )
    # Antelacion minima alta: 24hs. Aun asi el dueño debe poder cargar ya mismo.
    await client.patch(
        "/stores/me", headers=auth_headers(token), json={"min_booking_notice_hours": 24}
    )
    servicio, staff = await _staff_disponible_hoy(client, token)

    dentro_de_10_min = datetime.now(timezone.utc) + timedelta(minutes=10)
    res = await client.post(
        "/appointments/",
        headers=auth_headers(token),
        json={
            "service_id": servicio,
            "staff_id": staff,
            "starts_at": dentro_de_10_min.isoformat(),
            "idempotency_key": "admin-walkin-0001",
        },
    )
    assert res.status_code == 201, res.text


@pytest.mark.asyncio
async def test_el_dueno_no_puede_cargar_en_el_pasado(client: AsyncClient) -> None:
    """El piso es 'ahora': no tiene sentido agendar para una hora ya pasada."""
    _, token = await register_and_login(
        client, slug="admin-pasado", email="admin-pasado@test.com"
    )
    servicio, staff = await _staff_disponible_hoy(client, token)

    hace_una_hora = datetime.now(timezone.utc) - timedelta(hours=1)
    res = await client.post(
        "/appointments/",
        headers=auth_headers(token),
        json={
            "service_id": servicio,
            "staff_id": staff,
            "starts_at": hace_una_hora.isoformat(),
            "idempotency_key": "admin-pasado-0001",
        },
    )
    assert res.status_code == 422, res.text
    assert "pasado" in res.text.lower()


@pytest.mark.asyncio
async def test_el_cliente_sigue_respetando_la_antelacion_de_la_tienda(
    client: AsyncClient,
) -> None:
    """La flexibilidad es solo del panel: el booking publico mantiene la regla."""
    store_public_id, token = await register_and_login(
        client, slug="cliente-antelacion", email="cli-ant@test.com"
    )
    await client.patch(
        "/stores/me", headers=auth_headers(token), json={"min_booking_notice_hours": 24}
    )
    servicio, staff = await _staff_disponible_hoy(client, token)

    # El cliente intenta reservar dentro de 10 min, con la tienda pidiendo 24hs.
    dentro_de_10_min = datetime.now(timezone.utc) + timedelta(minutes=10)
    res = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store_public_id,
            "service_id": servicio,
            "staff_id": staff,
            "starts_at": dentro_de_10_min.isoformat(),
            "client_name": "Cliente Apurado",
            "client_phone": "+5491155500222",
            "accepts_terms": True,
            "idempotency_key": "cliente-antelacion-0001",
        },
    )
    assert res.status_code == 400, res.text
    assert "BOOKING_NOTICE_REQUIRED" in res.text
