"""El telefono no prueba identidad: no adopta el contacto de otro (2026-09-10).

Regresion encontrada al revisar la Fase 4: cualquiera que conociera el
telefono de un cliente podia anotarse en la lista de espera (sin OTP, por
diseno) con ese telefono y SU propio email. ``get_or_create_client`` pisaba
el email tecnico del cliente y, desde ahi, todas las notificaciones de esa
persona -- confirmaciones, recordatorios y sus datos de turno -- llegaban al
atacante.
"""

import re
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import modules.notifications.tasks as tasks
from core.security import hash_password
from modules.otp.model import OtpVerification
from modules.otp.service import OtpService
from modules.users.model import User, UserRole
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)
from tests.integration.test_mails_al_cliente import Buzon
from tests.integration.test_otp_por_email import Cola
from tests.integration.test_sena_por_antelacion_e_historial import (
    _preview,
    _reasons,
    _slot,
    _tienda_con_sena,
)

VICTIMA = "+5491155550999"

_CODIGO = re.compile(r"\b\d{6}\b")


def _destinos_del_codigo(enviados: list[tuple[str, str, str]]) -> list[str]:
    """Buzones que recibieron un mail CON codigo.

    El OTP se encola (AUD2-B4-06), asi que se mira la cola ``send_otp_email``
    y no el sink SMTP. Al email tipeado que no coincide con el de la ficha le
    llega un aviso SIN codigo (AUD2-B4-05: la entrega tampoco dice si el
    telefono es cliente); lo que nunca puede pasar es que el codigo salga ahi.
    """
    return [destino for destino, _asunto, cuerpo in enviados if _CODIGO.search(cuerpo)]


async def _tienda(
    client: AsyncClient, slug: str
) -> tuple[str, str, str, str, datetime]:
    store, token = await register_and_login(
        client, slug=slug, email=f"{slug}@example.com"
    )
    service = await create_service(client, token)
    staff = await create_staff(client, token, service, email=f"pro-{slug}@example.com")
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff, target_date=dia)
    return (
        store,
        token,
        service,
        staff,
        dia.replace(hour=13, minute=0, second=0, microsecond=0),
    )


async def _store_id(session: AsyncSession, slug: str) -> str:
    session.expire_all()
    dueno = (
        await session.execute(select(User).where(User.email == f"{slug}@example.com"))
    ).scalar_one()
    return str(dueno.store_id)


async def _email_del_cliente(session: AsyncSession, phone: str) -> str:
    session.expire_all()
    fila = (
        await session.execute(
            select(User).where(User.phone == phone, User.role == UserRole.CLIENT)
        )
    ).scalar_one()
    return str(fila.email)


@pytest.mark.asyncio
async def test_anotarse_en_la_lista_de_espera_no_secuestra_el_email_del_cliente(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    store, _token, service, staff, slot = await _tienda(client, "secuestro")

    reserva = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store,
            "service_id": service,
            "staff_id": staff,
            "starts_at": slot.isoformat(),
            "client_name": "Victima",
            "client_phone": VICTIMA,
            "accepts_terms": True,
            "idempotency_key": "secuestro-000001",
        },
    )
    assert reserva.status_code == 201, reserva.text
    tecnico = await _email_del_cliente(test_session, "5491155550999")
    assert tecnico.endswith(".noreply")

    alta = await client.post(
        "/public/waitlist",
        json={
            "store_public_id": store,
            "service_id": service,
            "window_starts_at": (slot + timedelta(days=1)).isoformat(),
            "window_ends_at": (slot + timedelta(days=2)).isoformat(),
            "client_name": "Atacante",
            "client_phone": VICTIMA,
            "client_email": "atacante@evil.com",
        },
    )
    assert alta.status_code == 201, alta.text

    assert await _email_del_cliente(test_session, "5491155550999") == tecnico, (
        "el email del cliente no puede cambiarlo un tercero con solo saber el telefono"
    )


@pytest.mark.asyncio
async def test_reservar_sin_otp_no_pisa_el_contacto_pero_si_avisa_a_ese_mail(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    buzon = Buzon()
    monkeypatch.setattr(tasks, "_send_email", buzon)
    store, _token, service, staff, slot = await _tienda(client, "secuestro-reserva")

    primera = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store,
            "service_id": service,
            "staff_id": staff,
            "starts_at": slot.isoformat(),
            "client_name": "Victima",
            "client_phone": VICTIMA,
            "accepts_terms": True,
            "idempotency_key": "secuestro-reserva-01",
        },
    )
    assert primera.status_code == 201, primera.text
    tecnico = await _email_del_cliente(test_session, "5491155550999")

    segunda = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store,
            "service_id": service,
            "staff_id": staff,
            "starts_at": (slot + timedelta(hours=2)).isoformat(),
            "client_name": "Atacante",
            "client_phone": VICTIMA,
            "accepts_terms": True,
            "client_email": "atacante@evil.com",
            "idempotency_key": "secuestro-reserva-02",
        },
    )
    assert segunda.status_code == 201, segunda.text
    assert await _email_del_cliente(test_session, "5491155550999") == tecnico

    # El mail de ESA reserva si va al email que dejaron (es su propia reserva),
    # pero no queda pegado al cliente para las notificaciones futuras.
    assert any(destino == "atacante@evil.com" for destino, _a, _c in buzon.enviados)


@pytest.mark.asyncio
async def test_ni_con_el_telefono_verificado_por_otp_se_pisa_el_contacto_ajeno(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El flujo publico NUNCA adopta el contacto de una ficha existente (2026-09-20).

    Hasta hoy el telefono "verificado por OTP" era la excepcion que permitia
    pisar el email del cliente. Era falsa: el OTP prueba posesion del EMAIL y
    `/public/otp/request` es publico, asi que quien pedia el codigo elegia el
    buzon. La excepcion se fue del todo; el mail de ESA reserva sigue yendo al
    email que dejaron, pero no queda pegado al cliente.
    """
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    store, _token, service, staff, slot = await _tienda(client, "secuestro-otp")

    primera = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store,
            "service_id": service,
            "staff_id": staff,
            "starts_at": slot.isoformat(),
            "client_name": "Duenio del telefono",
            "client_phone": VICTIMA,
            "accepts_terms": True,
            "idempotency_key": "secuestro-otp-01",
        },
    )
    assert primera.status_code == 201, primera.text
    tecnico = await _email_del_cliente(test_session, "5491155550999")
    assert tecnico.endswith(".noreply")

    # Alguien verifica un codigo de ESE telefono contra un email propio.
    store_id = await _store_id(test_session, "secuestro-otp")
    servicio_otp = OtpService(test_session)
    pedido = await servicio_otp.request_code(
        store_id=store_id,
        phone="5491155550999",
        channel="email",
        email="real@example.com",
        store_name="Demo",
        # El envio (post-respuesta desde B4-01) no importa aca.
        schedule_dispatch=lambda *args: None,
    )
    verificado = await servicio_otp.verify_code(
        store_id=store_id,
        phone="5491155550999",
        code=str(pedido["debug_code"]),
    )
    assert verificado

    segunda = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store,
            "service_id": service,
            "staff_id": staff,
            "starts_at": (slot + timedelta(hours=2)).isoformat(),
            "client_name": "Duenio del telefono",
            "client_phone": VICTIMA,
            "accepts_terms": True,
            "client_email": "real@example.com",
            "idempotency_key": "secuestro-otp-02",
        },
    )
    assert segunda.status_code == 201, segunda.text
    assert await _email_del_cliente(test_session, "5491155550999") == tecnico, (
        "un OTP verificado contra un email elegido por quien lo pidio no puede "
        "adoptar la ficha del cliente"
    )


@pytest.mark.asyncio
async def test_el_otp_a_un_email_propio_no_abre_los_turnos_de_otro(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un OTP prueba posesion del EMAIL, no del TELEFONO (2026-09-20).

    Sintoma: `/public/otp/request` es publico y el que pide elige a que email
    va el codigo, pero `verify_code` marca `verified_at` indexado solo por
    (tienda, telefono). Con eso, saber un telefono ajeno y poner el email
    propio alcanzaba para pasar `_require_recent_client_otp` y LISTAR,
    CANCELAR o REPROGRAMAR los turnos de esa persona. El codigo llega al
    buzon del atacante: la victima no se entera de nada.

    La victima reserva CON email entregable A PROPOSITO. Con el email tecnico
    `.noreply` el 403 salia del guard "ficha sin contacto entregable" y la
    clausula de igualdad de email NUNCA se ejecutaba: el test era verde por la
    razon equivocada. Cada asercion dice abajo que guard ejercita.
    """
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    cola = Cola()
    monkeypatch.setattr(tasks, "send_otp_email", cola)
    store, _token, service, staff, slot = await _tienda(client, "otp-ajeno")

    reserva = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store,
            "service_id": service,
            "staff_id": staff,
            "starts_at": slot.isoformat(),
            "client_name": "Victima",
            "client_phone": VICTIMA,
            "accepts_terms": True,
            "client_email": "victima@example.com",
            "idempotency_key": "otp-ajeno-01",
        },
    )
    assert reserva.status_code == 201, reserva.text
    turno = reserva.json()["public_id"]
    assert await _email_del_cliente(test_session, "5491155550999") == (
        "victima@example.com"
    ), "la ficha tiene que tener contacto ENTREGABLE para que el test sirva"

    # GUARD: punto de despacho. El atacante sabe el telefono y pone SU email,
    # pero el codigo va al buzon de la ficha y el del request se ignora como
    # destino del codigo (le llega solo el aviso sin codigo de AUD2-B4-05).
    pedido = await client.post(
        "/public/otp/request",
        json={
            "store_public_id": store,
            "phone": VICTIMA,
            "channel": "email",
            "email": "atacante@evil.com",
        },
    )
    assert pedido.status_code == 200, pedido.text
    destinos = _destinos_del_codigo(cola.enviados)
    assert "atacante@evil.com" not in destinos, (
        f"el codigo del telefono de la victima NO puede llegarle al atacante, "
        f"y fue a {destinos}"
    )
    assert destinos == ["victima@example.com"], (
        f"el codigo tiene que ir al email de la ficha, y fue a {destinos}"
    )

    # GUARD: igualdad de email. El atacante no puede leer ese codigo, asi que
    # se fabrica el estado que SI era alcanzable antes del fix del despacho:
    # una verificacion reciente, consumida y con email NO NULL, contra un buzon
    # que NO es el de la ficha. Es el unico estado que ejercita la comparacion
    # `OtpVerification.email == <email de la ficha>`; sin esta fila el 403 se
    # explicaria solo por "nunca verifico".
    ahora = datetime.now(timezone.utc)
    test_session.add(
        OtpVerification(
            store_id=await _store_id(test_session, "otp-ajeno"),
            phone="+5491155550999",
            channel="email",
            code_hash="verificacion-contra-otro-buzon",
            expires_at=ahora + timedelta(minutes=10),
            consumed_at=ahora,
            verified_at=ahora,
            email="atacante@evil.com",
        )
    )
    await test_session.commit()

    # Los tres endpoints de autogestion pasan por `_require_recent_client_otp`.
    listado = await client.get(f"/public/client/{store}/{VICTIMA}/appointments")
    assert listado.status_code == 403, (
        f"un OTP verificado contra otro email no puede listar los turnos "
        f"ajenos, y devolvio {listado.status_code}: {listado.text}"
    )

    reprogramacion = await client.patch(
        f"/public/client/appointments/{turno}/reschedule",
        json={
            "phone": VICTIMA,
            "new_starts_at": (slot + timedelta(hours=2)).isoformat(),
            "idempotency_key": "otp-ajeno-reschedule",
        },
    )
    assert reprogramacion.status_code == 403, (
        f"tampoco puede reprogramarle el turno, y devolvio "
        f"{reprogramacion.status_code}: {reprogramacion.text}"
    )

    cancelacion = await client.patch(
        f"/public/client/appointments/{turno}/cancel",
        json={"phone": VICTIMA, "reason": "no fui yo"},
    )
    assert cancelacion.status_code == 403, (
        f"tampoco puede cancelarle el turno, y devolvio "
        f"{cancelacion.status_code}: {cancelacion.text}"
    )


@pytest.mark.asyncio
async def test_el_despacho_encuentra_la_ficha_en_las_tres_formas_de_telefono(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`users.phone` y `otp_verifications.phone` no se normalizan igual.

    El validador del schema publico (`phone_must_be_numeric`) saca `\\s-()+`,
    asi que guarda el numero tal como lo tipearon menos esos caracteres;
    `normalize_phone` guarda la forma canonica con `+` y traduce el prefijo
    internacional `00`. Un telefono tipeado como `0034...` quedaba en
    `users.phone` como `0034...` mientras el OTP lo buscaba como `+34...` o
    `34...`: no encontraba la ficha, el codigo se iba al email del request y
    el cliente legitimo se comia un 403 (falla cerrado, pero lo traba).
    2026-09-20.
    """
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    cola = Cola()
    monkeypatch.setattr(tasks, "send_otp_email", cola)
    store, _token, _service, _staff, _slot = await _tienda(client, "otp-formas")
    store_id = await _store_id(test_session, "otp-formas")

    # Las tres formas en que puede quedar `users.phone`: canonica con `+`,
    # pelada (la que produce el validador publico) y con prefijo `00`.
    hash_inutil = hash_password("no-se-usa")
    fichas = {
        "+34600111111": "mas@example.com",
        "34600222222": "pelado@example.com",
        "0034600333333": "doblecero@example.com",
    }
    for guardado, email in fichas.items():
        test_session.add(
            User(
                email=email,
                hashed_password=hash_inutil,
                full_name="Cliente",
                phone=guardado,
                role=UserRole.CLIENT,
                store_id=store_id,
            )
        )
    await test_session.commit()

    for guardado, email in fichas.items():
        cola.enviados.clear()
        pedido = await client.post(
            "/public/otp/request",
            json={
                "store_public_id": store,
                "phone": guardado,
                "channel": "email",
                "email": "atacante@evil.com",
            },
        )
        assert pedido.status_code == 200, pedido.text
        destinos = _destinos_del_codigo(cola.enviados)
        assert destinos == [email], (
            f"con `users.phone` guardado como {guardado!r} el codigo tiene que "
            f"ir al email de la ficha ({email}), y fue a {destinos}"
        )


@pytest.mark.asyncio
async def test_una_verificacion_sin_email_registrado_no_abre_la_autogestion(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """NULL en `otp_verifications.email` es FAIL CLOSED (2026-09-20).

    Las filas anteriores a la columna no dicen contra que direccion se probo la
    posesion, asi que no otorgan NINGUN privilegio. Si no, la migracion misma
    dejaba abierta la puerta que cierra el fix: alcanzaba una verificacion
    vieja (o una fila puesta a mano) para autogestionar turnos ajenos.
    """
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    store, _token, service, staff, slot = await _tienda(client, "otp-sin-email")

    reserva = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store,
            "service_id": service,
            "staff_id": staff,
            "starts_at": slot.isoformat(),
            "client_name": "Duenio",
            "client_phone": VICTIMA,
            "accepts_terms": True,
            # Ficha con email ENTREGABLE: el unico motivo del 403 tiene que ser
            # el email NULL de la verificacion, no la falta de contacto.
            "client_email": "duenio@example.com",
            "idempotency_key": "otp-sin-email-01",
        },
    )
    assert reserva.status_code == 201, reserva.text

    ahora = datetime.now(timezone.utc)
    test_session.add(
        OtpVerification(
            store_id=await _store_id(test_session, "otp-sin-email"),
            phone="+5491155550999",
            channel="email",
            code_hash="verificacion-vieja-sin-email",
            expires_at=ahora + timedelta(minutes=10),
            consumed_at=ahora,
            verified_at=ahora,
            email=None,
        )
    )
    await test_session.commit()

    listado = await client.get(f"/public/client/{store}/{VICTIMA}/appointments")
    assert listado.status_code == 403, (
        f"una verificacion sin email registrado no otorga privilegios, y "
        f"devolvio {listado.status_code}: {listado.text}"
    )


@pytest.mark.asyncio
async def test_el_duenio_del_email_de_la_ficha_lista_y_cancela_sus_turnos(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El camino legitimo sigue abierto: el codigo va al email de la ficha."""
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    cola = Cola()
    monkeypatch.setattr(tasks, "send_otp_email", cola)
    store, _token, service, staff, slot = await _tienda(client, "otp-duenio")

    reserva = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store,
            "service_id": service,
            "staff_id": staff,
            "starts_at": slot.isoformat(),
            "client_name": "Duenio",
            "client_phone": VICTIMA,
            "accepts_terms": True,
            "client_email": "duenio@example.com",
            "idempotency_key": "otp-duenio-01",
        },
    )
    assert reserva.status_code == 201, reserva.text
    turno = reserva.json()["public_id"]

    pedido = await client.post(
        "/public/otp/request",
        json={
            "store_public_id": store,
            "phone": VICTIMA,
            "channel": "email",
            "email": "duenio@example.com",
        },
    )
    assert pedido.status_code == 200, pedido.text
    assert _destinos_del_codigo(cola.enviados) == ["duenio@example.com"]

    verificado = await client.post(
        "/public/otp/verify",
        json={
            "store_public_id": store,
            "phone": VICTIMA,
            "code": str(pedido.json()["debug_code"]),
        },
    )
    assert verificado.status_code == 200, verificado.text

    listado = await client.get(f"/public/client/{store}/{VICTIMA}/appointments")
    assert listado.status_code == 200, listado.text
    assert len(listado.json()["appointments"]) == 1

    cancelacion = await client.patch(
        f"/public/client/appointments/{turno}/cancel",
        json={"phone": VICTIMA, "reason": "no puedo ir"},
    )
    assert cancelacion.status_code == 200, cancelacion.text
    assert cancelacion.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_el_email_del_request_se_ignora_cuando_hay_ficha_con_contacto(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Quien pide el codigo no elige el buzon si hay ficha que proteger."""
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    cola = Cola()
    monkeypatch.setattr(tasks, "send_otp_email", cola)
    store, _token, service, staff, slot = await _tienda(client, "otp-buzon")

    reserva = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store,
            "service_id": service,
            "staff_id": staff,
            "starts_at": slot.isoformat(),
            "client_name": "Duenio",
            "client_phone": VICTIMA,
            "accepts_terms": True,
            "client_email": "duenio@example.com",
            "idempotency_key": "otp-buzon-01",
        },
    )
    assert reserva.status_code == 201, reserva.text

    pedido = await client.post(
        "/public/otp/request",
        json={
            "store_public_id": store,
            "phone": VICTIMA,
            "channel": "email",
            "email": "atacante@evil.com",
        },
    )
    assert pedido.status_code == 200, pedido.text

    destinos = _destinos_del_codigo(cola.enviados)
    assert destinos == ["duenio@example.com"], (
        f"el codigo tiene que ir al email de la ficha y no al del request, "
        f"y fue a {destinos}"
    )
    # Al email tipeado le llega el aviso SIN codigo (AUD2-B4-05): que llegue
    # algo no dice si el telefono es cliente, y el titular legitimo que tipeo
    # otra casilla sabe donde buscar el codigo.
    assert [d for d, _a, _c in cola.enviados] == [
        "duenio@example.com",
        "atacante@evil.com",
    ]


@pytest.mark.asyncio
async def test_pedir_el_codigo_responde_igual_sea_cliente_o_no(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sin enumeracion: la respuesta no dice si ese telefono es cliente."""
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    store, _token, service, staff, slot = await _tienda(client, "otp-enumeracion")

    reserva = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store,
            "service_id": service,
            "staff_id": staff,
            "starts_at": slot.isoformat(),
            "client_name": "Duenio",
            "client_phone": VICTIMA,
            "accepts_terms": True,
            "client_email": "duenio@example.com",
            "idempotency_key": "otp-enumeracion-01",
        },
    )
    assert reserva.status_code == 201, reserva.text

    cuerpo = {
        "store_public_id": store,
        "channel": "email",
        "email": "curioso@example.com",
    }
    es_cliente = await client.post(
        "/public/otp/request", json={**cuerpo, "phone": VICTIMA}
    )
    no_es_cliente = await client.post(
        "/public/otp/request", json={**cuerpo, "phone": "+5491155550777"}
    )

    assert es_cliente.status_code == no_es_cliente.status_code == 200
    assert sorted(es_cliente.json().keys()) == sorted(no_es_cliente.json().keys()), (
        "la forma del body delataria si el telefono es cliente de la tienda"
    )


@pytest.mark.asyncio
async def test_un_cliente_nuevo_reserva_con_otp_booking_activo(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un telefono sin ficha verifica con SU email y reserva: sigue el alta."""
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    store, token, service, staff, slot = await _tienda(client, "otp-alta-nueva")
    flags = await client.put(
        "/stores/me/feature-flags",
        headers=auth_headers(token),
        json={"otp_booking": True},
    )
    assert flags.status_code == 200, flags.text

    pedido = await client.post(
        "/public/otp/request",
        json={
            "store_public_id": store,
            "phone": "+5491155550777",
            "channel": "email",
            "email": "nuevo@example.com",
        },
    )
    assert pedido.status_code == 200, pedido.text
    verificado = await client.post(
        "/public/otp/verify",
        json={
            "store_public_id": store,
            "phone": "+5491155550777",
            "code": str(pedido.json()["debug_code"]),
        },
    )
    assert verificado.status_code == 200, verificado.text

    reserva = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store,
            "service_id": service,
            "staff_id": staff,
            "starts_at": slot.isoformat(),
            "client_name": "Cliente Nuevo",
            "client_phone": "+5491155550777",
            "accepts_terms": True,
            "client_email": "nuevo@example.com",
            "idempotency_key": "otp-alta-nueva-01",
        },
    )
    assert reserva.status_code == 201, reserva.text


@pytest.mark.asyncio
async def test_el_gate_de_reserva_no_exige_que_los_dos_emails_coincidan(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El wizard publico tiene DOS campos de email independientes.

    `client_email` es OPCIONAL y es un campo distinto del email con el que se
    pidio el codigo, y `canSubmit` solo exige que el OTP este verificado. Un
    gate que compare los dos devuelve un 403 determinista al cliente que deja
    el de contacto vacio (o pone otro), rompiendo un flujo que funcionaba, y
    no aporta seguridad: quien ataca controla los dos campos igual. La
    garantia es el punto de DESPACHO, no el match. 2026-09-20.
    """
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    store, token, service, staff, slot = await _tienda(client, "otp-dos-emails")
    flags = await client.put(
        "/stores/me/feature-flags",
        headers=auth_headers(token),
        json={"otp_booking": True},
    )
    assert flags.status_code == 200, flags.text

    pedido = await client.post(
        "/public/otp/request",
        json={
            "store_public_id": store,
            "phone": "+5491155550777",
            "channel": "email",
            "email": "codigo@example.com",
        },
    )
    assert pedido.status_code == 200, pedido.text
    verificado = await client.post(
        "/public/otp/verify",
        json={
            "store_public_id": store,
            "phone": "+5491155550777",
            "code": str(pedido.json()["debug_code"]),
        },
    )
    assert verificado.status_code == 200, verificado.text

    # Sin `client_email`: el caso que el gate viejo rechazaba con `email=""`.
    sin_email = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store,
            "service_id": service,
            "staff_id": staff,
            "starts_at": slot.isoformat(),
            "client_name": "Cliente Nuevo",
            "client_phone": "+5491155550777",
            "accepts_terms": True,
            "idempotency_key": "otp-dos-emails-01",
        },
    )
    assert sin_email.status_code == 201, (
        f"verificar el OTP y dejar el email de contacto vacio tiene que "
        f"reservar, y devolvio {sin_email.status_code}: {sin_email.text}"
    )

    # Con un `client_email` DISTINTO al del codigo: mismo veredicto.
    distinto = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store,
            "service_id": service,
            "staff_id": staff,
            "starts_at": (slot + timedelta(hours=2)).isoformat(),
            "client_name": "Cliente Nuevo",
            "client_phone": "+5491155550777",
            "accepts_terms": True,
            "client_email": "contacto@example.com",
            "idempotency_key": "otp-dos-emails-02",
        },
    )
    assert distinto.status_code == 201, (
        f"los dos campos de email del wizard pueden diverger, y devolvio "
        f"{distinto.status_code}: {distinto.text}"
    )


@pytest.mark.asyncio
async def test_sin_contacto_verificado_la_sena_no_filtra_el_historial(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El preview de la sena no delata las ausencias del cliente real.

    El atacante conoce el telefono y verifica un codigo contra SU email (la
    ficha tiene el email tecnico `.noreply`, asi que el despacho no se
    redirige). Con el predicado viejo eso abria `get_client_history` y el
    preview respondia, a cualquiera y por telefono, si esa persona falto.
    """
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    store, token, service, staff = await _tienda_con_sena(client, "otp-historial")

    turno = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store,
            "service_id": service,
            "staff_id": staff,
            "starts_at": _slot(2).isoformat(),
            "client_name": "Victima",
            "client_phone": VICTIMA,
            "accepts_terms": True,
            "payment_method": "manual",
            "idempotency_key": "otp-historial-01",
        },
    )
    assert turno.status_code == 201, turno.text
    for accion in ("confirm", "absent"):
        res = await client.patch(
            f"/appointments/{turno.json()['public_id']}/{accion}",
            headers=auth_headers(token),
        )
        assert res.status_code == 200, res.text

    pedido = await client.post(
        "/public/otp/request",
        json={
            "store_public_id": store,
            "phone": VICTIMA,
            "channel": "email",
            "email": "atacante@evil.com",
        },
    )
    assert pedido.status_code == 200, pedido.text
    verificado = await client.post(
        "/public/otp/verify",
        json={
            "store_public_id": store,
            "phone": VICTIMA,
            "code": str(pedido.json()["debug_code"]),
        },
    )
    assert verificado.status_code == 200, verificado.text

    preview = await _preview(client, store, service, 2, VICTIMA)
    assert _reasons(preview) == ["base"], (
        f"un telefono sin contacto verificado recibe UNKNOWN_HISTORY, no las "
        f"ausencias del cliente real: {preview['reasons']}"
    )
