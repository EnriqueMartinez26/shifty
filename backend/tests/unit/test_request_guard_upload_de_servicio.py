"""La subida de imagen de servicio pasa por la excepcion multipart (regla 18).

F1-28 (2026-09-24): ``POST /services/{public_id}/image`` es multipart. El
guard solo admite multipart en las rutas de subida; el resto de la API sigue
restringida a JSON (anti-CSRF). La excepcion es por patron exacto: otra ruta
de /services con multipart sigue siendo 415.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from core.security_middleware import RequestGuardMiddleware, is_upload_path


async def _eco(request: Request) -> JSONResponse:
    return JSONResponse({"bytes": len(await request.body())})


def _cliente() -> AsyncClient:
    app = Starlette(routes=[Route("/{ruta:path}", _eco, methods=["POST", "PATCH"])])
    return AsyncClient(
        transport=ASGITransport(app=RequestGuardMiddleware(app)),
        base_url="http://test",
    )


@pytest.mark.parametrize(
    ("path", "es_subida"),
    [
        ("/stores/me/media", True),
        ("/services/01JABCDEFGHJKMNPQRSTVWXYZ0/image", True),
        ("/services/01JABC/image/", False),
        ("/services/01JABC", False),
        ("/services/a/b/image", False),
        ("/services//image", False),
        ("/services/" + "x" * 65 + "/image", False),
    ],
)
def test_solo_las_rutas_de_subida_admiten_multipart(path: str, es_subida: bool) -> None:
    assert is_upload_path(path) is es_subida


@pytest.mark.asyncio
async def test_multipart_de_la_imagen_de_servicio_llega_al_router() -> None:
    async with _cliente() as client:
        res = await client.post(
            "/services/01JABC/image",
            files={"file": ("a.png", b"\x89PNG" + b"\x00" * 2048, "image/png")},
        )
    assert res.status_code == 200, res.text


@pytest.mark.asyncio
async def test_multipart_en_otra_ruta_de_servicios_sigue_siendo_415() -> None:
    async with _cliente() as client:
        res = await client.patch(
            "/services/01JABC",
            files={"file": ("a.png", b"\x89PNG", "image/png")},
        )
    assert res.status_code == 415
    assert res.json()["error_code"] == "UNSUPPORTED_MEDIA_TYPE"
