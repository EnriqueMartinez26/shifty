"""El link "reserva de nuevo" usa solo el id publico del profesional.

B4-11 (2026-09-18): ``rebook_url`` tenia ``getattr(staff, "public_id", None)
or getattr(staff, "id", None)``. Con el modelo real la segunda mitad no se
alcanza nunca: ``Staff.public_id`` es una propiedad que devuelve ``id``, asi
que el link que recibe el cliente siempre llevo el mismo identificador (el
primer test lo deja escrito: el fallback NO expuso un id distinto). La rama
muerta documentaba mal: sugeria que podia salir un id interno en un mail al
cliente. Sin ella, un objeto sin ``public_id`` no pone ``staff=`` en el link
en vez de filtrar su ``id``.
"""

from __future__ import annotations

from types import SimpleNamespace

from modules.notifications.tasks import rebook_url
from modules.staff.model import Staff

BASE = "https://shifty.test"
SERVICIO = SimpleNamespace(public_id="svc-1")


def test_con_el_modelo_real_el_link_lleva_el_id_publico() -> None:
    staff = Staff(id="st-real", display_name="Ana")
    assert staff.public_id == staff.id, "Staff.public_id es el mismo id"
    assert rebook_url(BASE, "demo", SERVICIO, staff) == (
        f"{BASE}/b/demo?service=svc-1&staff=st-real"
    )


def test_un_objeto_sin_public_id_no_filtra_su_id_en_el_link() -> None:
    sin_public_id = SimpleNamespace(id="id-interno-no-publicable")
    assert rebook_url(BASE, "demo", SERVICIO, sin_public_id) == (
        f"{BASE}/b/demo?service=svc-1"
    )


def test_sin_profesional_el_link_sigue_armandose() -> None:
    # waitlist/offers.py obtiene el profesional con db.get y puede ser None.
    assert rebook_url(BASE, "demo", SERVICIO, None) == f"{BASE}/b/demo?service=svc-1"
