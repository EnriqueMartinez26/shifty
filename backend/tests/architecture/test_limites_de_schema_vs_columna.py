"""El largo que acepta un schema de entrada no supera el de su columna.

2026-10-01, sintoma: ``StaffCreate.display_name`` aceptaba 255 caracteres y
``staff.display_name`` es ``String(100)``. Pydantic lo dejaba pasar, Postgres lo
rechazaba (``value too long``, SQLSTATE 22001) y la API contestaba 500 (regla
20). La suite de integracion corre en SQLite, que no aplica el largo del
``VARCHAR``: ningun test lo veia.

Este guardia compara, para los schemas de entrada de staff, users, superadmin,
public_api, waitlist, appointments y stores, el ``max_length`` de cada campo
``str`` contra el ``String(n)`` de la columna del mismo nombre. El mapa es una
tabla explicita (``CAMPOS_MAPEADOS``), no introspeccion: un campo que se
guarda en una columna con OTRO nombre, o repartido entre varias, no se mapea
aca (p. ej. ``custom_fields`` de la reserva o ``notes_staff``, que es ``Text``)
y queda fuera a proposito. Tampoco mira lo que se deriva de un campo: el
``client_name`` de la reserva se compara con ``appointments.client_name``, no
con el ``first_name``/``last_name`` que se parten de el.

Falla si el limite del schema supera la columna o si un campo mapeado no tiene
limite. Las columnas ``Text`` no tienen largo y no se mapean. ``EmailStr``
sin ``max_length`` cuenta como 254, el tope de ``email-validator`` (lo prueba
``test_emailstr_rechaza_mas_de_254``).

``DESCUADRES_CONOCIDOS`` es deuda declarada y fechada: solo puede bajar. Falla
si aparece un descuadre nuevo y tambien si una entrada ya no es un descuadre
(se borra de la tabla), igual que ``COMMITS_DECLARADOS_FUERA_DE_SERVICE`` en
``test_boundaries.py``. Postgres no se levanta aca: es un chequeo estatico.
"""

from __future__ import annotations

from typing import Any, get_args

import pytest
from pydantic import BaseModel, EmailStr, TypeAdapter, ValidationError
from sqlalchemy import String

from infrastructure.persistence.models.appointment import AppointmentModel
from infrastructure.persistence.models.staff import StaffModel
from infrastructure.persistence.models.user import UserModel
from modules.appointments.schemas import AppointmentCreate, AppointmentReschedule
from modules.billing.model import Plan, SaaSCoupon, StoreSubscription
from modules.public_api.schemas import ClientRescheduleRequest, PublicBookingCreate
from modules.staff.schemas import StaffCreate, StaffUpdate
from modules.stores.model import Store
from modules.stores.schemas import StoreUpdate
from modules.superadmin.schemas import (
    CouponCreate,
    CouponUpdate,
    PlanCreate,
    PlanUpdate,
    StoreAdminCreate,
    StoreCreate,
    StoreGlobalUpdate,
    StoreSubscriptionCreate,
    UserGlobalUpdate,
)
from modules.users.schemas import UserCreate, UserUpdate
from modules.waitlist.model import WaitlistEntry
from modules.waitlist.schemas import WaitlistJoinRequest

# Tope de largo total que acepta email-validator: lo que ``EmailStr`` deja
# pasar cuando el campo no declara ``max_length``.
EMAIL_STR_MAX_LENGTH = 254

# (schema de entrada, campo) -> (modelo, columna). Una fila por campo; el
# nombre del campo y el de la columna son el mismo salvo que se indique.
CAMPOS_MAPEADOS: tuple[tuple[type[BaseModel], str, type[Any], str], ...] = (
    # staff
    (StaffCreate, "display_name", StaffModel, "display_name"),
    (StaffCreate, "first_name", StaffModel, "first_name"),
    (StaffCreate, "last_name", StaffModel, "last_name"),
    (StaffCreate, "email", StaffModel, "email"),
    (StaffUpdate, "display_name", StaffModel, "display_name"),
    (StaffUpdate, "first_name", StaffModel, "first_name"),
    (StaffUpdate, "last_name", StaffModel, "last_name"),
    (StaffUpdate, "email", StaffModel, "email"),
    # users (el alta del personal tambien escribe estas columnas de users)
    (StaffCreate, "first_name", UserModel, "first_name"),
    (StaffCreate, "last_name", UserModel, "last_name"),
    (StaffCreate, "email", UserModel, "email"),
    (StaffUpdate, "first_name", UserModel, "first_name"),
    (StaffUpdate, "last_name", UserModel, "last_name"),
    (StaffUpdate, "email", UserModel, "email"),
    (UserCreate, "email", UserModel, "email"),
    (UserCreate, "first_name", UserModel, "first_name"),
    (UserCreate, "last_name", UserModel, "last_name"),
    (UserCreate, "phone", UserModel, "phone"),
    (UserUpdate, "first_name", UserModel, "first_name"),
    (UserUpdate, "last_name", UserModel, "last_name"),
    (UserUpdate, "phone", UserModel, "phone"),
    # superadmin: cuentas
    (StoreAdminCreate, "email", UserModel, "email"),
    (StoreAdminCreate, "first_name", UserModel, "first_name"),
    (StoreAdminCreate, "last_name", UserModel, "last_name"),
    (StoreAdminCreate, "phone", UserModel, "phone"),
    (UserGlobalUpdate, "first_name", UserModel, "first_name"),
    (UserGlobalUpdate, "last_name", UserModel, "last_name"),
    (UserGlobalUpdate, "phone", UserModel, "phone"),
    # superadmin: tiendas
    (StoreCreate, "name", Store, "name"),
    (StoreCreate, "slug", Store, "slug"),
    (StoreCreate, "logo_url", Store, "logo_url"),
    (StoreGlobalUpdate, "name", Store, "name"),
    (StoreGlobalUpdate, "slug", Store, "slug"),
    (StoreGlobalUpdate, "logo_url", Store, "logo_url"),
    # superadmin: planes, cupones y suscripciones
    (PlanCreate, "name", Plan, "name"),
    (PlanCreate, "currency", Plan, "currency"),
    (PlanCreate, "billing_interval", Plan, "billing_interval"),
    (PlanUpdate, "name", Plan, "name"),
    (PlanUpdate, "currency", Plan, "currency"),
    (PlanUpdate, "billing_interval", Plan, "billing_interval"),
    (CouponCreate, "code", SaaSCoupon, "code"),
    (CouponCreate, "currency", SaaSCoupon, "currency"),
    (CouponUpdate, "code", SaaSCoupon, "code"),
    (CouponUpdate, "currency", SaaSCoupon, "currency"),
    (StoreSubscriptionCreate, "currency", StoreSubscription, "currency"),
    # stores (panel de la tienda)
    (StoreUpdate, "name", Store, "name"),
    (StoreUpdate, "slug", Store, "slug"),
    (StoreUpdate, "logo_url", Store, "logo_url"),
    # appointments (alta desde el panel y reprogramacion)
    (AppointmentCreate, "client_name", AppointmentModel, "client_name"),
    (AppointmentCreate, "client_phone", AppointmentModel, "client_phone"),
    (AppointmentCreate, "client_email", AppointmentModel, "client_email"),
    (AppointmentCreate, "idempotency_key", AppointmentModel, "idempotency_key"),
    (AppointmentReschedule, "idempotency_key", AppointmentModel, "idempotency_key"),
    # public_api (reserva del portal)
    (PublicBookingCreate, "client_name", AppointmentModel, "client_name"),
    (PublicBookingCreate, "client_phone", AppointmentModel, "client_phone"),
    (PublicBookingCreate, "client_email", AppointmentModel, "client_email"),
    (PublicBookingCreate, "idempotency_key", AppointmentModel, "idempotency_key"),
    (ClientRescheduleRequest, "idempotency_key", AppointmentModel, "idempotency_key"),
    # waitlist
    (WaitlistJoinRequest, "client_name", WaitlistEntry, "client_name"),
    (WaitlistJoinRequest, "client_phone", WaitlistEntry, "client_phone"),
    (WaitlistJoinRequest, "client_email", WaitlistEntry, "client_email"),
)

# (nombre del schema, campo, nombre del modelo, columna) -> motivo. Descuadres
# que ya existian cuando se escribio el guardia (2026-10-01): se declaran, no
# se arreglan en silencio, y la tabla solo puede bajar.
_IDEMPOTENCY_KEY_100 = (
    "2026-10-01: la clave del cliente se guarda tal cual en "
    "appointments.idempotency_key (String(100), infrastructure/persistence/"
    "models/appointment.py:120) y el schema acepta hasta 128: una clave de 101 "
    "a 128 caracteres pasa Pydantic y Postgres la rechaza (500). Arreglo: "
    "max_length=100 en el schema, o ensanchar la columna con una migracion."
)
DESCUADRES_CONOCIDOS: dict[tuple[str, str, str, str], str] = {
    # modules/appointments/schemas.py:44
    (
        "AppointmentCreate",
        "idempotency_key",
        "AppointmentModel",
        "idempotency_key",
    ): _IDEMPOTENCY_KEY_100,
    # modules/appointments/schemas.py:175
    (
        "AppointmentReschedule",
        "idempotency_key",
        "AppointmentModel",
        "idempotency_key",
    ): _IDEMPOTENCY_KEY_100,
    # modules/public_api/schemas.py:93
    (
        "PublicBookingCreate",
        "idempotency_key",
        "AppointmentModel",
        "idempotency_key",
    ): _IDEMPOTENCY_KEY_100,
    # modules/public_api/schemas.py:249
    (
        "ClientRescheduleRequest",
        "idempotency_key",
        "AppointmentModel",
        "idempotency_key",
    ): _IDEMPOTENCY_KEY_100,
}


def _clave(
    schema: type[BaseModel], campo: str, modelo: type[Any], columna: str
) -> tuple[str, str, str, str]:
    return (schema.__name__, campo, modelo.__name__, columna)


def _es_emailstr(anotacion: Any) -> bool:
    if anotacion is EmailStr:
        return True
    return any(_es_emailstr(arg) for arg in get_args(anotacion))


def _limite_del_schema(schema: type[BaseModel], campo: str) -> int | None:
    info = schema.model_fields[campo]
    for meta in info.metadata:
        tope = getattr(meta, "max_length", None)
        if tope is not None:
            return int(tope)
    if _es_emailstr(info.annotation):
        return EMAIL_STR_MAX_LENGTH
    return None


def _largo_de_la_columna(modelo: type[Any], columna: str) -> int:
    tipo = modelo.__table__.c[columna].type
    assert isinstance(tipo, String) and tipo.length is not None, (
        f"{modelo.__name__}.{columna} no es String(n): no se mapea"
    )
    return int(tipo.length)


def _descuadre(
    schema: type[BaseModel], campo: str, modelo: type[Any], columna: str
) -> str | None:
    """Por que el campo no cabe en la columna, o ``None`` si cabe."""
    largo = _largo_de_la_columna(modelo, columna)
    limite = _limite_del_schema(schema, campo)
    if limite is None:
        return f"sin max_length (la columna es String({largo}))"
    if limite > largo:
        return f"max_length={limite} > String({largo})"
    return None


def _nombre(fila: tuple[type[BaseModel], str, type[Any], str]) -> str:
    schema, campo, modelo, columna = fila
    return f"{schema.__name__}.{campo} -> {modelo.__name__}.{columna}"


def test_la_tabla_de_campos_apunta_a_campos_y_columnas_reales() -> None:
    for schema, campo, modelo, columna in CAMPOS_MAPEADOS:
        assert campo in schema.model_fields, f"{schema.__name__} no tiene {campo}"
        assert columna in modelo.__table__.c, f"{modelo.__name__} no tiene {columna}"
        _largo_de_la_columna(modelo, columna)


def test_la_tabla_de_campos_no_repite_filas() -> None:
    claves = [_clave(*fila) for fila in CAMPOS_MAPEADOS]
    assert len(claves) == len(set(claves))


@pytest.mark.parametrize("fila", CAMPOS_MAPEADOS, ids=_nombre)
def test_un_campo_de_entrada_no_supera_el_largo_de_su_columna(
    fila: tuple[type[BaseModel], str, type[Any], str],
) -> None:
    if _clave(*fila) in DESCUADRES_CONOCIDOS:
        pytest.skip("descuadre declarado en DESCUADRES_CONOCIDOS")
    motivo = _descuadre(*fila)
    assert motivo is None, (
        f"{_nombre(fila)}: {motivo}. Un valor mas largo que la columna pasa "
        "Pydantic, lo rechaza Postgres y sale como 500 (regla 20): bajale el "
        "max_length al schema."
    )


def test_los_descuadres_conocidos_siguen_siendo_descuadres() -> None:
    """Una entrada que ya cuadra se borra: la tabla solo puede bajar."""
    por_clave = {_clave(*fila): fila for fila in CAMPOS_MAPEADOS}
    for clave in DESCUADRES_CONOCIDOS:
        assert clave in por_clave, f"{clave} no esta en CAMPOS_MAPEADOS"
        assert _descuadre(*por_clave[clave]) is not None, (
            f"{clave} ya cuadra con su columna: borralo de DESCUADRES_CONOCIDOS"
        )


def _email_de(largo: int) -> str:
    """Un email bien formado de ``largo`` caracteres (local 64, etiquetas de 60)."""
    dominio = largo - 65
    etiquetas = (dominio - 3) // 61
    resto = dominio - 61 * etiquetas
    assert 2 <= resto <= 63
    return (
        "a" * 64 + "@" + "".join("d" * 60 + "." for _ in range(etiquetas)) + "c" * resto
    )


def test_emailstr_rechaza_mas_de_254() -> None:
    """Sostiene EMAIL_STR_MAX_LENGTH: sin esto, un EmailStr sin max_length no
    estaria acotado y el guardia lo contaria de mas."""
    validador = TypeAdapter(EmailStr)
    assert validador.validate_python(_email_de(EMAIL_STR_MAX_LENGTH))
    with pytest.raises(ValidationError):
        validador.validate_python(_email_de(EMAIL_STR_MAX_LENGTH + 1))
