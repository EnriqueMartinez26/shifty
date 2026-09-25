"""``GET /stores/media/{media_id}`` valida el path param como el resto de la API.

Auditoria B3-17, 2026-09-18. Sintoma: era el unico path param del lote sin
validacion (``media_id: str``). La ruta es publica y consulta ``StoreMedia.id``
bajo bypass de RLS: cualquier string, de cualquier largo, llegaba a la base y
volvia 404. Ahora un id fuera de ``PUBLIC_ID_PATTERN`` se corta en 422 antes de
abrir el bypass; un id bien formado que no existe sigue siendo 404.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "media_id",
    ["a" * 65, "x" * 10_000, "id con espacio", "id.con.puntos", "id'--"],
    ids=["65-chars", "10k-chars", "espacio", "puntos", "comilla"],
)
async def test_un_id_malformado_se_rechaza_sin_consultar(
    client: AsyncClient, media_id: str
) -> None:
    res = await client.get(f"/stores/media/{media_id}")
    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_un_id_bien_formado_que_no_existe_sigue_siendo_404(
    client: AsyncClient,
) -> None:
    res = await client.get("/stores/media/01JNOEXISTE0000000000000000")
    assert res.status_code == 404, res.text
    assert res.json()["error_code"] == "MEDIA_NOT_FOUND"
