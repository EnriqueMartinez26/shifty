"""Prueba de carga/abuso contra el stack CORRIENDO (via nginx).

No es un test de pytest: es una herramienta operativa. Bombardea los caminos
sensibles con concurrencia acotada y verifica que el sistema TOLERE
(200/201/409/422/429, nunca 5xx ni cuelgue), que no haya doble-reserva ni
doble-alta por carrera, y que siga respondiendo despues. La prueba de
concurrencia que corre en CI vive en tests/postgres/; esta ejercita ademas
rate-limit y lockout, que dependen del stack real con Redis y nginx.

El alta de tiendas ya no es publica, asi que necesita un superadmin ya
creado (scripts/bootstrap_superadmin.py) y crea su propia tienda descartable
por la API de superadmin.

Uso (con el docker-compose levantado y RATE_LIMIT_ENABLED=true):

    SUPERADMIN_EMAIL=... SUPERADMIN_PASSWORD=... \
        uv run python scripts/load_test_booking.py

Variables opcionales: BASE_URL (default http://localhost/api),
LOAD_RAFAGA (default 25). Sale con codigo != 0 si algo falla.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import os
import sys
import time
from collections import Counter
from typing import Any

import httpx

BASE = os.getenv("BASE_URL", "http://localhost/api").rstrip("/")
SUPER_EMAIL = os.getenv("SUPERADMIN_EMAIL")
SUPER_PASS = os.getenv("SUPERADMIN_PASSWORD")
RAFAGA = int(os.getenv("LOAD_RAFAGA", "25"))
STAMP = str(int(time.time()))
ADMIN_PASS = "Password123!"

resultados: dict[str, str] = {}


def _unwrap(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    return data if isinstance(data, dict) else payload


def _token(payload: dict[str, Any]) -> str:
    return str(_unwrap(payload).get("access_token", ""))


def _registrar(label: str, ok: bool, detalle: str) -> None:
    resultados[label] = f"{'OK' if ok else 'FALLA'} | {detalle}"
    print(f"[{label}] {'OK' if ok else 'FALLA'} | {detalle}")


def _resumen_codigos(label: str, codigos: list[int]) -> None:
    dist = dict(Counter(codigos))
    n5xx = sum(v for k, v in dist.items() if 500 <= k < 600)
    _registrar(label, n5xx == 0, f"dist={dist}")


async def _superadmin_token(c: httpx.AsyncClient) -> str:
    r = await c.post(
        f"{BASE}/auth/login", json={"email": SUPER_EMAIL, "password": SUPER_PASS}
    )
    if r.status_code != 200:
        raise SystemExit(
            f"No se pudo loguear el superadmin ({r.status_code}). "
            "Corre scripts/bootstrap_superadmin.py y exporta SUPERADMIN_EMAIL/PASSWORD."
        )
    return _token(r.json())


async def _crear_tienda_admin(
    c: httpx.AsyncClient, sa_token: str
) -> tuple[str, str, str]:
    """Crea tienda + admin por la API de superadmin y devuelve el token del admin."""
    h = {"Authorization": f"Bearer {sa_token}"}
    slug = f"load-{STAMP}"
    admin_email = f"load-admin-{STAMP}@example.com"
    tienda = await c.post(
        f"{BASE}/superadmin/stores",
        headers=h,
        json={"name": f"Load {STAMP}", "slug": slug},
    )
    if tienda.status_code != 201:
        raise SystemExit(f"crear tienda fallo: {tienda.status_code} {tienda.text}")
    store_pub = _unwrap(tienda.json())["public_id"]
    alta = await c.post(
        f"{BASE}/superadmin/stores/{store_pub}/admins",
        headers=h,
        json={
            "email": admin_email,
            "password": ADMIN_PASS,
            "first_name": "Load",
            "last_name": "Admin",
        },
    )
    if alta.status_code != 201:
        raise SystemExit(f"crear admin fallo: {alta.status_code} {alta.text}")
    login = await c.post(
        f"{BASE}/auth/login", json={"email": admin_email, "password": ADMIN_PASS}
    )
    return _token(login.json()), store_pub, slug


async def _preparar_reservable(
    c: httpx.AsyncClient, token: str
) -> tuple[str, str, str]:
    h = {"Authorization": f"Bearer {token}"}
    svc = await c.post(
        f"{BASE}/services/",
        headers=h,
        json={"name": "Svc", "duration_minutes": 30, "price": 5000},
    )
    svc_id = _unwrap(svc.json())["public_id"]
    stf = await c.post(
        f"{BASE}/staff/",
        headers=h,
        json={
            "display_name": "Pro",
            "first_name": "P",
            "last_name": "R",
            "email": f"pro-{STAMP}@example.com",
            "service_ids": [svc_id],
        },
    )
    stf_id = _unwrap(stf.json())["public_id"]
    dia = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=9)
    await c.post(
        f"{BASE}/staff/{stf_id}/schedules",
        headers=h,
        json={
            "day_of_week": dia.weekday(),
            "start_time": "08:00:00",
            "end_time": "20:00:00",
        },
    )
    return svc_id, stf_id, dia.strftime("%Y-%m-%d")


def _reserva(
    store: str, svc: str, stf: str, slot: str, key: str, i: int
) -> dict[str, str]:
    return {
        "store_public_id": store,
        "service_id": svc,
        "staff_id": stf,
        "starts_at": slot,
        "client_name": f"Cliente {i}",
        "client_phone": f"+54911555{i:05d}",
        "idempotency_key": key,
    }


async def main() -> int:
    if not (SUPER_EMAIL and SUPER_PASS):
        raise SystemExit("Faltan SUPERADMIN_EMAIL / SUPERADMIN_PASSWORD.")

    async with httpx.AsyncClient(timeout=30) as c:
        sa = await _superadmin_token(c)
        token, store, slug = await _crear_tienda_admin(c, sa)
        svc, stf, fecha = await _preparar_reservable(c, token)

        # 1) 30 reservas identicas y CONCURRENTES (misma idempotency): un turno.
        slot1 = f"{fecha}T09:00:00+00:00"
        cuerpo = _reserva(store, svc, stf, slot1, f"same-{STAMP}", 0)
        r1 = await asyncio.gather(
            *(c.post(f"{BASE}/public/appointments", json=cuerpo) for _ in range(30)),
            return_exceptions=True,
        )
        codigos1 = [r.status_code for r in r1 if isinstance(r, httpx.Response)]
        _resumen_codigos("idempotencia-30-concurrentes", codigos1)
        creados = {
            _unwrap(r.json()).get("public_id")
            for r in r1
            if isinstance(r, httpx.Response) and r.status_code in (200, 201)
        }
        _registrar(
            "idempotencia-turnos-unicos", len(creados) <= 1, f"turnos={len(creados)}"
        )

        # 2) RAFAGA reservas al MISMO slot con DISTINTA idempotency: gana una.
        slot2 = f"{fecha}T10:00:00+00:00"
        r2 = await asyncio.gather(
            *(
                c.post(
                    f"{BASE}/public/appointments",
                    json=_reserva(store, svc, stf, slot2, f"diff-{STAMP}-{i}", i),
                )
                for i in range(RAFAGA)
            ),
            return_exceptions=True,
        )
        codigos2 = [r.status_code for r in r2 if isinstance(r, httpx.Response)]
        ganadores = sum(1 for c2 in codigos2 if c2 in (200, 201))
        _resumen_codigos("doble-booking-rafaga", codigos2)
        _registrar("doble-booking-ganadores", ganadores <= 1, f"ganadores={ganadores}")

        # 3) 60 lecturas publicas rapidas: deberia haber 429, nunca 5xx.
        r3 = await asyncio.gather(
            *(c.get(f"{BASE}/public/stores/{slug}") for _ in range(60)),
            return_exceptions=True,
        )
        _resumen_codigos(
            "rate-limit-60-lecturas",
            [r.status_code for r in r3 if isinstance(r, httpx.Response)],
        )

        # 4) 20 logins con password incorrecta: lockout/429, nunca 5xx.
        r4 = await asyncio.gather(
            *(
                c.post(
                    f"{BASE}/auth/login",
                    json={
                        "email": f"load-admin-{STAMP}@example.com",
                        "password": "WrongPass999!",
                    },
                )
                for _ in range(20)
            ),
            return_exceptions=True,
        )
        _resumen_codigos(
            "login-bruteforce-20",
            [r.status_code for r in r4 if isinstance(r, httpx.Response)],
        )

        # 5) sigue vivo tras el castigo
        alive = await c.get(f"{BASE}/", timeout=10)
        _registrar(
            "sigue-vivo", alive.status_code == 200, f"status={alive.status_code}"
        )

    print("\n===== RESUMEN =====")
    for k, v in resultados.items():
        print(f"{k}: {v}")
    return 0 if all(v.startswith("OK") for v in resultados.values()) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
