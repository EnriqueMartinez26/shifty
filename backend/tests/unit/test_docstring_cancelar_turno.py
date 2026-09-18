"""El contrato publicado de ``PATCH /appointments/{id}/cancel`` dice lo que hace.

Audit B1-20 (2026-09-18). El docstring (que FastAPI publica como descripcion
en OpenAPI) decia "Disponible para el cliente duenio, staff y admin": el rol
cliente no puede iniciar sesion (``test_authz_client_login.py``) y cancela
por ``/public/client/appointments/{id}/cancel``, y el endpoint no verifica
titularidad. Quien leyera la descripcion podia asumir un control de acceso
que no existe.
"""

from main import app


def _descripcion() -> str:
    operacion = app.openapi()["paths"]["/appointments/{public_id}/cancel"]["patch"]
    return str(operacion.get("description") or operacion.get("summary") or "")


def test_la_descripcion_no_promete_acceso_del_cliente() -> None:
    texto = _descripcion().lower()
    assert "cliente due" not in texto, texto
    assert "/public/client/appointments" in texto, texto


def test_la_descripcion_declara_que_no_verifica_titularidad() -> None:
    assert "titularidad" in _descripcion().lower()
