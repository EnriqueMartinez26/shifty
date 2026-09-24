"""Prueba de aceptacion de capacidad (plan §9, plan-capacidad §5).

200 usuarios contra un STAGING sembrado con ``scripts/seed_capacidad.py``:

- 150 clientes publicos: tienda al azar -> vitrina -> servicios -> staff ->
  disponibilidad de 2-4 fechas de los proximos 14 dias -> preview de sena ->
  30 % reserva un slot libre (sin email: sale el ``.noreply`` y no se manda
  correo). Pensar 2-8 s entre pasos.
- 45 duenos: login una vez (escalonado por la rampa) -> dashboard y avisos ->
  agenda del dia y de manana -> confirmar o cancelar turnos -> editar nombre y
  telefono de la tienda -> editar un servicio -> crear un bloqueo lejano ->
  refresh del token cada 14 minutos. Pensar 3-10 s.
- 5 superadmin: listado paginado de tiendas, detalle y edicion del nombre de
  una tienda ``cap-``. Pensar 5-15 s.
- Rafaga: cada 5 minutos, 10 reservas del MISMO slot a la vez; se espera
  1 x 201 y 9 x 409 (CLAUDE.md §4).

Rampa de 5 minutos y 20 de meseta (``AceptacionShape``); al entrar en la
meseta se reinician las estadisticas, asi el p95 del CSV es el de la carga
plena. Durante la corrida se muestrea ``/ops/slo`` cada 30 s con el
superadmin. Al terminar quedan, junto al ``--csv``:

- ``<prefijo>_codigos.json``: codigos por ruta, errores de conexion y rafagas;
- ``<prefijo>_slo.jsonl``: una muestra del SLO por linea.

El veredicto lo da ``scripts/perf_acceptance_check.py``. Como correrla:
``docs/PERF_ACCEPTANCE.md``. Variables:

- ``SHIFTY_MANIFEST``: manifiesto JSON del seed (obligatorio).
- ``SEED_OWNER_PASSWORD``: contrasena de los duenos sembrados.
- ``SHIFTY_SUPERADMIN_EMAIL`` / ``SHIFTY_SUPERADMIN_PASSWORD``.
- ``SHIFTY_THINK_SCALE``: multiplica los tiempos de pensar (0.15 = variante
  agresiva, informativa).

Un solo proceso de Locust (sin ``--processes``): la rafaga y el muestreo del
SLO corren en el runner local. ``--host`` lleva el prefijo ``/api``.
"""

from __future__ import annotations

import itertools
import json
import os
import random
import sys
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import gevent
import requests
from locust import HttpUser, LoadTestShape, between, events, task
from locust.clients import HttpSession
from locust.env import Environment
from locust.runners import LocalRunner

sys.path.insert(0, str(Path(__file__).resolve().parent))

from aceptacion import (  # noqa: E402
    CLIENTES,
    DUENOS,
    MESETA_S,
    RAFAGA_CADA_S,
    RAFAGA_TAMANO,
    RAMPA_S,
    SLO_CADA_S,
    SUPERADMINS,
    TOTAL_USUARIOS,
    ConteoDeCodigos,
    TiendaSembrada,
    cargar_manifiesto,
    datos_de,
    fechas_de_consulta,
    forma_de_carga,
    slot_libre,
)

THINK_SCALE = float(os.getenv("SHIFTY_THINK_SCALE", "1"))
OWNER_PASSWORD = os.getenv("SEED_OWNER_PASSWORD", "")
SUPERADMIN_EMAIL = os.getenv("SHIFTY_SUPERADMIN_EMAIL", "")
SUPERADMIN_PASSWORD = os.getenv("SHIFTY_SUPERADMIN_PASSWORD", "")
MANIFEST = os.getenv("SHIFTY_MANIFEST", "")
REFRESH_EVERY_S = 14 * 60
# Solo para un ensayo corto antes de la corrida real (docs/PERF_ACCEPTANCE.md):
# la aceptacion se juzga con los valores del plan.
RAMPA = int(os.getenv("SHIFTY_RAMPA_S", str(RAMPA_S)))
MESETA = int(os.getenv("SHIFTY_MESETA_S", str(MESETA_S)))
RAFAGA_CADA = int(os.getenv("SHIFTY_RAFAGA_CADA_S", str(RAFAGA_CADA_S)))
USUARIOS = int(os.getenv("SHIFTY_USUARIOS", str(TOTAL_USUARIOS)))

TIENDAS: list[TiendaSembrada] = cargar_manifiesto(MANIFEST) if MANIFEST else []
CONTEO = ConteoDeCodigos()
_DUENO_SIGUIENTE = itertools.count()
_RNG = random.Random()
# Estados de negocio que no son errores: un slot tomado entre la
# disponibilidad y la reserva (409) o un bloqueo sobre otro (409).
OK_NEGOCIO = (200, 201, 204, 409)


def _hoy() -> date:
    # Solo elige fechas de consulta; la hora de negocio la resuelve el backend.
    return (datetime.now(timezone.utc) - timedelta(hours=3)).date()


def _pensar(desde: float, hasta: float) -> None:
    gevent.sleep(_RNG.uniform(desde, hasta) * THINK_SCALE)


def _pedir(
    client: HttpSession,
    metodo: str,
    url: str,
    *,
    name: str,
    ok: tuple[int, ...] = OK_NEGOCIO,
    **kwargs: Any,
) -> Any:
    """Request que marca como exito los codigos de negocio esperados."""
    with client.request(
        metodo, url, name=name, catch_response=True, **kwargs
    ) as respuesta:
        if respuesta.status_code in ok:
            respuesta.success()
        else:
            respuesta.failure(f"HTTP {respuesta.status_code}")
        return respuesta


def _json(respuesta: Any) -> Any:
    try:
        return datos_de(respuesta.json())
    except ValueError:
        return None


@events.request.add_listener  # type: ignore[untyped-decorator]
def _contar(
    request_type: str,
    name: str,
    response: Any = None,
    exception: Any = None,
    **_kwargs: Any,
) -> None:
    codigo = getattr(response, "status_code", 0) if response is not None else 0
    CONTEO.registrar(request_type, name, codigo)


@events.init.add_listener  # type: ignore[untyped-decorator]
def _validar(environment: Environment, **_kwargs: Any) -> None:
    if not TIENDAS:
        raise SystemExit("Falta SHIFTY_MANIFEST (manifiesto de seed_capacidad.py)")
    if not OWNER_PASSWORD:
        raise SystemExit("Falta SEED_OWNER_PASSWORD")


class ClientePublico(HttpUser):
    weight = CLIENTES
    wait_time = between(2 * THINK_SCALE, 8 * THINK_SCALE)

    @task
    def reservar(self) -> None:
        tienda = _RNG.choice(TIENDAS)
        consulta = {"store_public_id": tienda.store_public_id}
        _pedir(
            self.client,
            "GET",
            f"/public/stores/{tienda.slug}",
            name="/public/stores/{slug}",
        )
        _pensar(2, 8)
        _pedir(
            self.client,
            "GET",
            "/public/services",
            name="/public/services",
            params=consulta,
        )
        servicio = _RNG.choice(tienda.service_ids)
        _pedir(
            self.client,
            "GET",
            "/public/staff",
            name="/public/staff",
            params={**consulta, "service_id": servicio},
        )
        _pensar(2, 8)
        elegido: Any = None
        for fecha in fechas_de_consulta(_hoy(), _RNG, cantidad=_RNG.randint(2, 4)):
            respuesta = _pedir(
                self.client,
                "GET",
                "/public/availability",
                name="/public/availability",
                params={**consulta, "service_id": servicio, "date": fecha},
            )
            slots = _json(respuesta)
            elegido = slot_libre(slots if isinstance(slots, list) else [], _RNG)
            _pensar(2, 8)
            if elegido:
                break
        if not elegido:
            return
        _pedir(
            self.client,
            "GET",
            "/public/deposit/preview",
            name="/public/deposit/preview",
            params={
                **consulta,
                "service_id": servicio,
                "starts_at": elegido["starts_at"],
            },
        )
        if _RNG.random() >= 0.30:
            return
        _pensar(2, 8)
        _pedir(
            self.client,
            "POST",
            "/public/appointments",
            name="/public/appointments",
            json=_reserva(tienda, servicio, elegido),
        )


def _reserva(
    tienda: TiendaSembrada, servicio: str, slot: dict[str, Any]
) -> dict[str, Any]:
    return {
        "store_public_id": tienda.store_public_id,
        "service_id": servicio,
        "staff_id": slot["staff_id"],
        "starts_at": slot["starts_at"],
        "client_name": "Cliente Carga",
        # Numero de prueba unico por reserva: sin OTP nunca adopta a nadie.
        "client_phone": f"+54911{_RNG.randint(10_000_000, 99_999_999)}",
        "accepts_terms": True,
        "idempotency_key": f"cap-{uuid.uuid4().hex}",
    }


class _ConSesion(HttpUser):
    abstract = True
    email = ""
    password = ""

    def on_start(self) -> None:
        self._login()

    def _login(self) -> None:
        respuesta = _pedir(
            self.client,
            "POST",
            "/auth/login",
            name="/auth/login",
            ok=(200,),
            json={"email": self.email, "password": self.password},
        )
        cuerpo = _json(respuesta) or {}
        self.token = str(cuerpo.get("access_token", ""))
        self.logueado_en = time.monotonic()

    def _headers(self) -> dict[str, str]:
        if time.monotonic() - self.logueado_en > REFRESH_EVERY_S:
            respuesta = _pedir(
                self.client,
                "POST",
                "/auth/refresh",
                name="/auth/refresh",
                ok=(200,),
            )
            cuerpo = _json(respuesta) or {}
            if cuerpo.get("access_token"):
                self.token = str(cuerpo["access_token"])
                self.logueado_en = time.monotonic()
            else:
                self._login()
        return {"Authorization": f"Bearer {self.token}"}


class Dueno(_ConSesion):
    weight = DUENOS
    wait_time = between(3 * THINK_SCALE, 10 * THINK_SCALE)

    def on_start(self) -> None:
        self.tienda = TIENDAS[next(_DUENO_SIGUIENTE) % len(TIENDAS)]
        self.email = self.tienda.owner_email
        self.password = OWNER_PASSWORD
        super().on_start()

    @task(3)
    def dashboard(self) -> None:
        h = self._headers()
        _pedir(
            self.client,
            "GET",
            "/dashboard/summary",
            name="/dashboard/summary",
            headers=h,
        )
        _pedir(self.client, "GET", "/notifications", name="/notifications", headers=h)

    @task(4)
    def agenda(self) -> None:
        dia = _hoy() + timedelta(days=_RNG.choice((0, 1)))
        respuesta = _pedir(
            self.client,
            "GET",
            "/appointments/",
            name="/appointments/",
            headers=self._headers(),
            params={"date": dia.isoformat()},
        )
        turnos = _json(respuesta)
        self.turnos = turnos if isinstance(turnos, list) else []

    @task(1)
    def confirmar_o_cancelar(self) -> None:
        turnos = getattr(self, "turnos", [])
        pendientes = [t for t in turnos if t.get("status") == "pending"]
        confirmados = [t for t in turnos if t.get("status") == "confirmed"]
        if pendientes and _RNG.random() < 0.8:
            turno, accion = _RNG.choice(pendientes), "confirm"
        elif confirmados:
            turno, accion = _RNG.choice(confirmados), "cancel"
        else:
            return
        _pedir(
            self.client,
            "PATCH",
            f"/appointments/{turno['public_id']}/{accion}",
            name=f"/appointments/{{public_id}}/{accion}",
            headers=self._headers(),
            ok=(200, 409, 422),
        )
        turnos.remove(turno)

    @task(1)
    def editar_tienda(self) -> None:
        sufijo = _RNG.randint(100, 999)
        _pedir(
            self.client,
            "PATCH",
            "/stores/me",
            name="/stores/me",
            headers=self._headers(),
            json={
                "name": f"Capacidad {self.tienda.slug} {sufijo}",
                "whatsapp_number": f"+54911{_RNG.randint(10_000_000, 99_999_999)}",
            },
        )

    @task(1)
    def editar_servicio(self) -> None:
        servicio = _RNG.choice(self.tienda.service_ids)
        _pedir(
            self.client,
            "PATCH",
            f"/services/{servicio}",
            name="/services/{public_id}",
            headers=self._headers(),
            json={"price": float(_RNG.randint(80, 200) * 100)},
        )

    @task(1)
    def crear_bloqueo(self) -> None:
        # Lejos de la ventana de reservas (14 dias) para no pisar la prueba.
        dia = _hoy() + timedelta(days=_RNG.randint(60, 110))
        inicio = datetime(
            dia.year, dia.month, dia.day, 12 + _RNG.randint(0, 6), tzinfo=timezone.utc
        )
        _pedir(
            self.client,
            "POST",
            "/appointment-blocks/",
            name="/appointment-blocks/",
            headers=self._headers(),
            json={
                "staff_id": _RNG.choice(self.tienda.staff_ids),
                "starts_at": inicio.isoformat(),
                "ends_at": (inicio + timedelta(minutes=30)).isoformat(),
                "reason": "Prueba de carga",
            },
        )


class Superadmin(_ConSesion):
    weight = SUPERADMINS
    wait_time = between(5 * THINK_SCALE, 15 * THINK_SCALE)

    def on_start(self) -> None:
        self.email = SUPERADMIN_EMAIL
        self.password = SUPERADMIN_PASSWORD
        super().on_start()

    @task(3)
    def listar(self) -> None:
        _pedir(
            self.client,
            "GET",
            "/superadmin/stores",
            name="/superadmin/stores",
            headers=self._headers(),
            params={"limit": 50, "offset": _RNG.randint(0, 150)},
        )

    @task(2)
    def detalle(self) -> None:
        tienda = _RNG.choice(TIENDAS)
        _pedir(
            self.client,
            "GET",
            f"/superadmin/stores/{tienda.store_public_id}",
            name="/superadmin/stores/{store_public_id}",
            headers=self._headers(),
        )

    @task(1)
    def editar(self) -> None:
        tienda = _RNG.choice(TIENDAS)
        _pedir(
            self.client,
            "PATCH",
            f"/superadmin/stores/{tienda.store_public_id}",
            name="/superadmin/stores/{store_public_id}",
            headers=self._headers(),
            json={"name": f"Capacidad {tienda.slug}"},
        )


class AceptacionShape(LoadTestShape):
    """Rampa de 5 min a 200 usuarios y 20 min de meseta."""

    _reiniciado = False

    def tick(self) -> tuple[int, float] | None:
        tiempo = float(self.get_run_time())  # type: ignore[no-untyped-call]
        if not self._reiniciado and tiempo >= RAMPA and self.runner is not None:
            # El p95 se juzga en la meseta: la rampa sale del CSV.
            self.runner.stats.reset_all()
            self._reiniciado = True
        objetivo: tuple[int, float] | None = forma_de_carga(
            tiempo, total=USUARIOS, rampa_s=RAMPA, meseta_s=MESETA
        )
        return objetivo


def _prefijo(environment: Environment) -> str:
    opciones = environment.parsed_options
    return str(getattr(opciones, "csv_prefix", None) or "aceptacion")


def _rafagas(environment: Environment) -> None:
    """Cada 5 minutos de meseta, 10 reservas del mismo slot a la vez."""
    # Primera al minuto de la meseta; con 20 minutos entran 4.
    gevent.sleep(RAMPA + min(60, RAFAGA_CADA // 5))
    for _numero in range(max(1, MESETA // RAFAGA_CADA)):
        _una_rafaga(environment)
        gevent.sleep(RAFAGA_CADA)


def _una_rafaga(environment: Environment) -> None:
    host = environment.host or ""
    sondeo = HttpSession(
        base_url=host, request_event=environment.events.request, user=None
    )
    for _intento in range(20):
        tienda = _RNG.choice(TIENDAS)
        servicio = _RNG.choice(tienda.service_ids)
        # Fecha lejana (15-40 dias): fuera de lo que reservan los clientes.
        dia = _hoy() + timedelta(days=_RNG.randint(15, 40))
        respuesta = sondeo.get(
            "/public/availability",
            name="/public/availability [rafaga]",
            params={
                "store_public_id": tienda.store_public_id,
                "service_id": servicio,
                "date": dia.isoformat(),
            },
        )
        slots = _json(respuesta)
        slot = slot_libre(slots if isinstance(slots, list) else [], _RNG)
        if slot:
            break
    else:
        CONTEO.registrar_rafaga([])
        return

    def reservar(_i: int) -> int:
        sesion = HttpSession(
            base_url=host, request_event=environment.events.request, user=None
        )
        with sesion.post(
            "/public/appointments",
            name="/public/appointments [rafaga]",
            json=_reserva(tienda, servicio, slot),
            catch_response=True,
        ) as r:
            if r.status_code in (201, 409):
                r.success()
            return int(r.status_code or 0)

    hilos = [gevent.spawn(reservar, i) for i in range(RAFAGA_TAMANO)]
    gevent.joinall(hilos)
    CONTEO.registrar_rafaga([h.value for h in hilos])


def _muestrear_slo(environment: Environment) -> None:
    """``/ops/slo`` cada 30 s con el superadmin; fuera de las estadisticas."""
    host = environment.host or ""
    destino = Path(f"{_prefijo(environment)}_slo.jsonl")
    sesion = requests.Session()
    token = ""
    while True:
        try:
            if not token:
                login = sesion.post(
                    f"{host}/auth/login",
                    timeout=10,
                    json={"email": SUPERADMIN_EMAIL, "password": SUPERADMIN_PASSWORD},
                )
                token = str(datos_de(login.json()).get("access_token", ""))
            respuesta = sesion.get(
                f"{host}/ops/slo",
                timeout=10,
                headers={"Authorization": f"Bearer {token}"},
            )
            if respuesta.status_code == 401:
                token = ""
            elif respuesta.ok:
                cuerpo = datos_de(respuesta.json())
                muestra = {
                    "t": datetime.now(timezone.utc).isoformat(),
                    "status": cuerpo.get("status"),
                    "metrics": cuerpo.get("metrics", {}),
                }
                with destino.open("a", encoding="utf-8") as archivo:
                    archivo.write(json.dumps(muestra) + "\n")
        except requests.RequestException, ValueError:
            token = ""
        gevent.sleep(SLO_CADA_S)


@events.test_start.add_listener  # type: ignore[untyped-decorator]
def _arrancar(environment: Environment, **_kwargs: Any) -> None:
    if not isinstance(environment.runner, LocalRunner):
        print("AVISO: rafaga y SLO solo corren con un proceso local de Locust")
        return
    destino = Path(f"{_prefijo(environment)}_slo.jsonl")
    destino.unlink(missing_ok=True)
    gevent.spawn(_rafagas, environment)
    gevent.spawn(_muestrear_slo, environment)


@events.quitting.add_listener  # type: ignore[untyped-decorator]
def _guardar(environment: Environment, **_kwargs: Any) -> None:
    destino = Path(f"{_prefijo(environment)}_codigos.json")
    destino.write_text(json.dumps(CONTEO.como_dict(), indent=2), encoding="utf-8")
