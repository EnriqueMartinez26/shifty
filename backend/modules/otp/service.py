from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import inspect
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from core.config import settings
from core.exceptions import OTPException, OTPRateLimitedException, ValidationException
from core.redis import REDIS_UNAVAILABLE_ERRORS, get_redis
from core.security import hash_otp_code
from modules.notifications.tasks import is_deliverable_email
from modules.otp.model import OtpVerification
from modules.users.model import User, UserRole

logger = structlog.get_logger()

# Un solo mensaje/codigo para TODO fallo de verificacion: distinguir
# "incorrecto" de "expirado/inexistente" le decia a un atacante si un telefono
# tiene un OTP vivo en esa tienda.
_OTP_INVALID = OTPException

# Motivo del rechazo, para el LOG DEL SERVIDOR. Nunca viaja al cliente: la
# respuesta sigue siendo un 403 con el mismo mensaje neutro (regla 20), porque
# cada motivo es un oraculo anonimo distinto ("ese telefono es cliente", "esa
# ficha tiene email cargado"). El log es lo unico que permite atender un ticket
# de un cliente legitimo trabado sin adivinar.
OTP_GATE_OK = "ok"
OTP_GATE_NEVER_VERIFIED = "never_verified"
OTP_GATE_EMAIL_MISMATCH = "verified_against_other_email"
OTP_GATE_NO_DELIVERABLE_CONTACT = "client_without_deliverable_email"


def mask_phone(phone: str | None) -> str:
    """Ultimos 4 digitos. Alcanza para cruzar con un ticket y no deja el
    numero completo en los logs; mismo criterio que `_mask_email` en
    `modules/notifications/tasks.py`."""
    digits = re.sub(r"\D", "", phone or "")
    if not digits:
        return "***"
    return f"***{digits[-4:]}"


def normalize_phone(raw_phone: str) -> str:
    cleaned = re.sub(r"[^\d+]", "", raw_phone or "")
    if cleaned.startswith("00"):
        cleaned = f"+{cleaned[2:]}"
    if not cleaned.startswith("+"):
        cleaned = f"+{cleaned}"
    if len(cleaned) < 8 or len(cleaned) > 20:
        raise ValidationException("Telefono invalido")
    return cleaned


def canonical_phone_forms(normalized_phone: str) -> list[str]:
    """Las formas en que ese telefono puede estar guardado en ``users.phone``.

    AUD2-B4-03 (2026-09-19): ``normalize_phone`` canoniza el prefijo (``00``
    pasa a ``+``), pero el alta publica guarda los digitos TAL CUAL, con el
    ``00`` adelante (``public_api/schemas.py`` solo saca separadores y ``+``).
    La guarda del OTP comparaba contra dos formas y no encontraba al cliente
    que habia reservado con ``0054...``: el codigo salia al email tipeado y el
    secuestro de contacto volvia a abrirse. Hasta unificar el guardado (ver el
    reporte: exige migrar datos), la BUSQUEDA compara las tres formas.
    """
    digits = normalized_phone.lstrip("+")
    return [digits, f"+{digits}", f"00{digits}"]


def _normalize_email(email: str | None) -> str | None:
    cleaned = (email or "").strip().lower()
    return cleaned or None


def _budget_key(kind: str, store_id: str, phone: str) -> str:
    material = f"{store_id}:{phone}".encode("utf-8")
    return f"otp:{kind}:{hashlib.sha256(material).hexdigest()[:32]}"


async def _consume_budget(kind: str, store_id: str, phone: str, limit: int) -> None:
    """Presupuesto ACUMULADO por telefono en ventana de 1 hora.

    Independiente de la IP (que se puede rotar) y del registro OTP (que antes
    se renovaba con cada codigo nuevo, reseteando los intentos). Corta tanto la
    fuerza bruta del espacio de 10^6 como el SMS-bombing al titular del numero.
    """
    if not settings.RATE_LIMIT_ENABLED:
        return
    try:
        redis = await get_redis()
        key = _budget_key(kind, store_id, phone)
        pipe = redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, 3600)
        current, _ = await pipe.execute()
        if int(current) > limit:
            raise OTPRateLimitedException()
    except REDIS_UNAVAILABLE_ERRORS as exc:
        # AUD2-B4-08: solo el tipo. El texto de un RedisError repite la
        # URL de conexion, que lleva credenciales.
        logger.warning("otp_budget_redis_unavailable", error_type=type(exc).__name__)
        if settings.RATE_LIMIT_FAIL_CLOSED:
            raise OTPRateLimitedException() from exc


def _otp_subject(store_name: str) -> str:
    """Mismo asunto para el codigo y para el aviso sin codigo: el asunto
    tampoco puede discriminar (AUD2-B4-05)."""
    return f"Tu codigo de verificacion - {store_name or 'Shifty'}"


def _code_body(code: str, store_name: str) -> str:
    tienda = store_name or "Shifty"
    return (
        "Hola,\n\n"
        f"Tu codigo para {tienda} es: {code}\n\n"
        f"Vence en {settings.OTP_CODE_EXPIRE_MINUTES} minutos. "
        "Si no pediste este codigo, ignora este mensaje.\n\n"
        "- El equipo de Shifty"
    )


def _notice_body(store_name: str) -> str:
    """Aviso SIN codigo al email tipeado cuando el codigo fue a otro buzon.

    AUD2-B4-05 (2026-09-20): si el telefono ya es de un cliente con email
    entregable, el codigo va a ESE email y no al tipeado. Quien pide controla
    la casilla que tipea: pedir el codigo de un telefono ajeno con la casilla
    propia y mirar si llega ALGO decia si ese telefono es cliente de esa
    tienda; repetido contra varias tiendas, mapeaba donde es cliente una
    persona. Ahora al email tipeado le llega un mail en los dos casos, con el
    mismo asunto; este no trae el codigo y le dice al titular legitimo donde
    buscarlo.

    Queda un residuo declarado: quien LEE el cuerpo del mail que recibe sigue
    distinguiendo "codigo" de "aviso". Cerrarlo del todo exigiria no mandar
    nunca el codigo a una casilla tipeada, que es el caso del telefono que
    todavia no es de nadie. Lo que se cierra aca es el oraculo barato -el que
    solo mira si hubo entrega- y el vector automatizable.
    """
    tienda = store_name or "Shifty"
    return (
        "Hola,\n\n"
        f"Recibimos un pedido de codigo de verificacion para {tienda}.\n\n"
        "Si el telefono es tuyo, el codigo fue a la direccion de correo que "
        "tenes registrada. Si no reconoces este pedido, ignora este mensaje: "
        "no hace falta que hagas nada.\n\n"
        "- El equipo de Shifty"
    )


# Entrega el mail (destino, asunto, cuerpo) FUERA del proceso de la API:
# ``notifications.tasks.enqueue_otp_email`` en el router (AUD2-B4-06). El
# servicio decide destino y contenido; quien llama decide el transporte, y
# nunca manda en linea. Puede ser async (``enqueue_otp_email``, F1-03: encola
# con tope de tiempo sin bloquear el loop) o sync (dobles de los tests).
DispatchScheduler = Callable[[str, str, str], Awaitable[None] | None]


async def _dispatch(
    schedule_dispatch: DispatchScheduler, to: str, subject: str, body: str
) -> None:
    pending = schedule_dispatch(to, subject, body)
    if inspect.isawaitable(pending):
        await pending


async def _schedule_otp_mail(
    schedule_dispatch: DispatchScheduler,
    *,
    destination: str | None,
    notice_to: str | None,
    code: str,
    store_name: str,
) -> None:
    """El codigo al buzon que decidio ``_resolve_destination``; el aviso sin
    codigo (AUD2-B4-05) al email tipeado cuando el codigo fue a otro lado.

    Los dos usan el mismo asunto y estan acotados por
    ``OTP_MAX_REQUESTS_PER_HOUR``.
    """
    asunto = _otp_subject(store_name)
    if destination:
        await _dispatch(
            schedule_dispatch, destination, asunto, _code_body(code, store_name)
        )
    if notice_to:
        await _dispatch(schedule_dispatch, notice_to, asunto, _notice_body(store_name))


def _debug_code(code: str, *, decoy: bool) -> str:
    """Lo que va en ``debug_code`` (solo con ``OTP_DEBUG_EXPOSE_CODE``).

    AUD2-SYNC-01 (2026-09-23): el merge con origin/main dejo de devolver el
    senuelo del camino sin coincidencia (290ab9f lo tenia). Con el flag
    activo -cualquier entorno que no sea produccion, que lo fuerza a false-,
    pedir el OTP de un telefono ajeno con la casilla propia devolvia el
    codigo REAL, el mismo que viajaba al email de la ficha, y con eso
    alcanzaba para autogestionar los turnos de la victima. Cuando el codigo
    no fue al email tipeado, la respuesta lleva un codigo de mentira con la
    misma forma y siempre distinto del guardado, que no conoce nadie.

    AUD2-SYNC-02 (2026-09-23): el senuelo se decidia por "hubo aviso sin
    codigo", que solo existe si alguien TIPEO un email distinto. Sin email
    tipeado y con el codigo yendo a la casilla de la ficha, volvia el codigo
    real. Decision del dueno: senuelo siempre que el destino no sea el email
    tipeado, tipee algo o no; quien llama lo decide por ``destination !=
    typed``, no por el aviso.
    """
    if not decoy:
        return code
    senuelo = (int(code) + 1 + secrets.randbelow(999_999)) % 1_000_000
    return f"{senuelo:06d}"


class OtpService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _registered_client_email(
        self, store_id: str, normalized_phone: str
    ) -> str | None:
        """Email ENTREGABLE (normalizado) del cliente de la tienda duenio de
        ese telefono; ``None`` si no hay ficha o tiene el tecnico ``.noreply``.

        La reserva publica guarda el telefono del cliente solo con digitos y
        conserva el prefijo ``00``; ``normalize_phone`` lo canoniza a ``+``.
        Se buscan todas las formas equivalentes (AUD2-B4-03): encontrar la
        ficha solo endurece el chequeo, nunca lo afloja, asi que no
        encontrarla mandaba el codigo al email tipeado (secuestro) y trababa
        con 403 al cliente legitimo.
        """
        result = await self.db.execute(
            select(User.email)
            .where(
                User.store_id == store_id,
                User.role == UserRole.CLIENT.value,
                User.phone.in_(canonical_phone_forms(normalized_phone)),
            )
            .order_by(User.created_at.desc())
            .limit(1)
        )
        registered = result.scalar_one_or_none()
        return (
            _normalize_email(registered) if is_deliverable_email(registered) else None
        )

    async def _resolve_destination(
        self, store_id: str, normalized_phone: str, typed: str | None
    ) -> tuple[str | None, str | None]:
        """(buzon del codigo, buzon del aviso sin codigo). NO lo elige quien pide.

        ``typed`` es el email tipeado ya pasado por ``_normalize_email``
        (``None`` si no se tipeo ninguno).

        B4-01 (2026-09-18) y 2026-09-20: el codigo prueba posesion del EMAIL al
        que llega, y ``/public/otp/request`` es publico. Si el telefono ya es
        de un cliente de la tienda con email entregable, el codigo va SOLO a
        ese email y el tipeado se ignora como destino: saber un telefono ajeno
        ya no alcanza para recibir el codigo de esa persona. Si el tipeado es
        otro, ahi va el aviso sin codigo de AUD2-B4-05 (la entrega tampoco
        dice si el telefono es cliente). Telefono nuevo, o cliente sin email
        entregable: el codigo va al email tipeado, como siempre.
        """
        registered = await self._registered_client_email(store_id, normalized_phone)
        if registered is None:
            return typed, None
        if typed == registered:
            return registered, None
        # Solo hay "falta de coincidencia" si alguien TIPEO un email. Los
        # canales de desarrollo (whatsapp/sms) no traen email: loguear ahi
        # convertia en ruido la senal de un posible secuestro de contacto
        # (AUD2-SYNC-01, 2026-09-23).
        if typed is not None:
            logger.info("otp_request_email_mismatch_for_known_client")
        return registered, typed

    async def _store_code(
        self,
        store_id: str,
        normalized_phone: str,
        channel: str,
        code: str,
        *,
        email: str | None,
    ) -> OtpVerification:
        """Invalida los codigos vivos de ese telefono y guarda el nuevo, con el
        buzon al que se despacho (``otp_verifications.email``)."""
        now = datetime.now(timezone.utc)
        await self.db.execute(
            update(OtpVerification)
            .where(
                OtpVerification.store_id == store_id,
                OtpVerification.phone == normalized_phone,
                OtpVerification.consumed_at.is_(None),
            )
            .values(consumed_at=now)
        )
        otp = OtpVerification(
            store_id=store_id,
            phone=normalized_phone,
            channel=channel,
            # HMAC con pepper y contexto: un SHA-256 pelado de 6 digitos se
            # invierte con una tabla de 10^6 entradas ante cualquier lectura
            # de la tabla (backup, replica).
            code_hash=hash_otp_code(store_id, normalized_phone, code),
            expires_at=now + timedelta(minutes=settings.OTP_CODE_EXPIRE_MINUTES),
            email=email,
            provider_message_id="email" if channel == "email" else "console-dispatch",
        )
        self.db.add(otp)
        await self.db.commit()
        await self.db.refresh(otp)
        return otp

    async def request_code(
        self,
        *,
        store_id: str,
        phone: str,
        channel: str,
        email: str | None = None,
        store_name: str = "",
        schedule_dispatch: DispatchScheduler,
    ) -> dict[str, object]:
        """Genera y guarda el codigo; el mail lo entrega ``schedule_dispatch``
        fuera del proceso de la API (B4-01 lo saco del camino sincronico;
        AUD2-B4-06 lo saco tambien del request). La respuesta no espera al
        SMTP y su tiempo no depende del destino. El parametro es obligatorio
        a proposito, para que ningun llamador vuelva a mandar en linea."""
        normalized_phone = normalize_phone(phone)
        if channel not in {"email", "whatsapp", "sms"}:
            raise ValidationException("Canal invalido")
        # Hasta 2026-09-10 NINGUN canal despachaba el codigo (solo se exponia
        # en la respuesta en desarrollo). Email es el unico con envio real;
        # whatsapp/sms quedan como canales de desarrollo con el codigo visible.
        if channel != "email" and settings.OTP_PROVIDER != "console":
            raise ValidationException(
                "Ese canal no esta disponible; pedi el codigo por email"
            )
        if channel == "email" and not email:
            raise ValidationException("Falta el email para enviar el codigo")

        await _consume_budget(
            "req", store_id, normalized_phone, settings.OTP_MAX_REQUESTS_PER_HOUR
        )

        # El buzon se decide para todos los canales: es lo que queda en
        # ``otp_verifications.email`` y contra lo que se compara despues
        # (``is_client_contact_verified``), aunque solo el canal email mande.
        typed = _normalize_email(email)
        destination, notice_to = await self._resolve_destination(
            store_id, normalized_phone, typed
        )

        # secrets, no random: un OTP con PRNG predecible se puede adivinar.
        code = f"{secrets.randbelow(1_000_000):06d}"
        otp = await self._store_code(
            store_id, normalized_phone, channel, code, email=destination
        )

        if channel == "email":
            # Despues del commit (el codigo ya esta guardado cuando se encola
            # el mail) y fuera del proceso de la API: la respuesta es la
            # misma, y tarda lo mismo, haya envio o no, para no revelar si el
            # telefono es cliente ni convertir el SMTP en un oraculo. Tampoco
            # dice a que buzon fue: eso delataria si el telefono es cliente.
            await _schedule_otp_mail(
                schedule_dispatch,
                destination=destination,
                notice_to=notice_to,
                code=code,
                store_name=store_name,
            )

        response = {"ok": True, "expires_at": otp.expires_at.isoformat()}
        if settings.OTP_DEBUG_EXPOSE_CODE:
            # Senuelo SIEMPRE que el codigo fue a un buzon distinto del que
            # tipeo quien pide, haya tipeado algo o no: la regla es sobre el
            # DESTINO, no sobre el aviso (AUD2-SYNC-02). Los canales de
            # consola no despachan nada y siguen mostrando el codigo.
            decoy = channel == "email" and destination != typed
            response["debug_code"] = _debug_code(code, decoy=decoy)
        return response

    async def verify_code(
        self, *, store_id: str, phone: str, code: str
    ) -> dict[str, object]:
        normalized_phone = normalize_phone(phone)

        await _consume_budget(
            "verify",
            store_id,
            normalized_phone,
            settings.OTP_MAX_VERIFY_ATTEMPTS_PER_HOUR,
        )

        now = datetime.now(timezone.utc)
        result = await self.db.execute(
            select(OtpVerification)
            .where(
                OtpVerification.store_id == store_id,
                OtpVerification.phone == normalized_phone,
            )
            .order_by(OtpVerification.created_at.desc())
            .limit(1)
            # Lock de fila: sin esto, dos verify concurrentes leen el mismo
            # attempts y ambos incrementan a N+1 (read-modify-write), dejando
            # exceder OTP_MAX_ATTEMPTS. No-op en SQLite (tests).
            .with_for_update()
        )
        otp = result.scalar_one_or_none()
        if not otp or otp.is_consumed or otp.is_expired:
            raise _OTP_INVALID()
        if otp.attempts >= settings.OTP_MAX_ATTEMPTS:
            raise OTPRateLimitedException()

        otp.attempts += 1
        expected = hash_otp_code(store_id, normalized_phone, code)
        if not hmac.compare_digest(otp.code_hash, expected):
            await self.db.commit()
            raise _OTP_INVALID()

        otp.consumed_at = now
        # Marca que alguien demostro posesion del EMAIL `otp.email`, NO del
        # telefono: el codigo viaja a una direccion, y el telefono solo es la
        # clave con la que se pidio. Cualquier privilegio que dependa del
        # telefono tiene que mirar tambien contra que email se verifico
        # (`may_book_with_otp` / `is_client_contact_verified`). 2026-09-20.
        otp.verified_at = now
        await self.db.commit()
        return {"ok": True, "verified_at": now.isoformat(), "phone": normalized_phone}

    async def client_contact_verification_reason(
        self, *, store_id: str, phone: str, window_minutes: int = 30
    ) -> str:
        """Motivo (para el log) del veredicto de `is_client_contact_verified`."""
        normalized_phone = normalize_phone(phone)
        contact = await self._registered_client_email(store_id, normalized_phone)
        if not contact:
            return OTP_GATE_NO_DELIVERABLE_CONTACT
        if await self._matches_verified_email(
            store_id=store_id,
            normalized_phone=normalized_phone,
            email=contact,
            window_minutes=window_minutes,
        ):
            return OTP_GATE_OK
        # Distinguir "nunca verifico" de "verifico contra otro buzon" es lo
        # unico que separa un cliente que no termino el flujo de un intento de
        # secuestro. Solo va al log.
        if await self._matches_verified_email(
            store_id=store_id,
            normalized_phone=normalized_phone,
            email=None,
            window_minutes=window_minutes,
        ):
            return OTP_GATE_EMAIL_MISMATCH
        return OTP_GATE_NEVER_VERIFIED

    async def is_client_contact_verified(
        self, *, store_id: str, phone: str, window_minutes: int = 30
    ) -> bool:
        """El email verificado COINCIDE con el contacto guardado de esa ficha.

        Es el unico predicado que habilita autogestion, historial y contacto:
        listar, cancelar o reprogramar turnos ajenos, y decidir si se trae
        `get_client_history` o `UNKNOWN_HISTORY`.

        False si no hay cliente con ese telefono en la tienda, si su email no
        es entregable (el tecnico `{tel}@store{id}.noreply`) o si la
        verificacion no registro email. 2026-09-20.
        """
        reason = await self.client_contact_verification_reason(
            store_id=store_id, phone=phone, window_minutes=window_minutes
        )
        return reason == OTP_GATE_OK

    async def booking_otp_reason(
        self, *, store_id: str, phone: str, window_minutes: int = 30
    ) -> str:
        """Motivo (para el log) del veredicto de `may_book_with_otp`."""
        normalized_phone = normalize_phone(phone)
        contact = await self._registered_client_email(store_id, normalized_phone)
        if contact:
            # Hay una victima posible: se exige lo mismo que para autogestion.
            return await self.client_contact_verification_reason(
                store_id=store_id, phone=phone, window_minutes=window_minutes
            )
        # Sin ficha (o con el email tecnico `.noreply`) no hay nada que
        # filtrar: basta con haber probado ALGUN buzon. El codigo fue a ese
        # email porque `_resolve_destination` no tenia a quien proteger.
        if await self._matches_verified_email(
            store_id=store_id,
            normalized_phone=normalized_phone,
            email=None,
            window_minutes=window_minutes,
        ):
            return OTP_GATE_OK
        return OTP_GATE_NEVER_VERIFIED

    async def may_book_with_otp(
        self, *, store_id: str, phone: str, window_minutes: int = 30
    ) -> bool:
        """Gate del feature flag `otp_booking` al RESERVAR.

        NO recibe email a proposito. Exigir que el email del formulario
        coincida con el verificado no aportaba seguridad -- quien ataca
        controla los dos campos igual -- y rompia el wizard publico, que tiene
        el email del cliente y el del codigo como campos independientes y
        opcionales. La seguridad la da el PUNTO DE DESPACHO: si el telefono
        tiene ficha con email entregable, `_resolve_destination` manda el
        codigo a ESE buzon y el solicitante ya no lo elige. 2026-09-20.
        """
        reason = await self.booking_otp_reason(
            store_id=store_id, phone=phone, window_minutes=window_minutes
        )
        return reason == OTP_GATE_OK

    async def _matches_verified_email(
        self,
        *,
        store_id: str,
        normalized_phone: str,
        email: str | None,
        window_minutes: int,
    ) -> bool:
        """Hay una verificacion reciente de ese telefono contra ESE email.

        Con `email=None` la pregunta es "contra ALGUN email", que sigue siendo
        fail closed: exige `otp_verifications.email IS NOT NULL`.

        Es PRIVADO a proposito. Como API publica era el footgun que este fix
        vino a eliminar: un predicado que acepta un email arbitrario del
        llamador deja que cada call site elija mal (y el gate de reserva eligio
        el email del formulario, que el atacante tambien controla). La
        ramificacion vive en `may_book_with_otp` /
        `is_client_contact_verified`, en un solo lugar testeado. 2026-09-20.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
        # Las filas sin email (anteriores al 2026-09-20) NUNCA matchean: por
        # igualdad porque `NULL = 'x'` es NULL, y con `email=None` porque se
        # pide explicitamente `IS NOT NULL`. Fail closed por SQL, no por
        # acordarse.
        email_clause: ColumnElement[bool] = OtpVerification.email.is_not(None)
        if email is not None:
            normalized_email = _normalize_email(email)
            if not normalized_email:
                return False
            email_clause = OtpVerification.email == normalized_email
        result = await self.db.execute(
            select(OtpVerification.id)
            .where(
                OtpVerification.store_id == store_id,
                OtpVerification.phone == normalized_phone,
                OtpVerification.verified_at.is_not(None),
                OtpVerification.verified_at >= cutoff,
                email_clause,
            )
            .order_by(OtpVerification.verified_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none() is not None
