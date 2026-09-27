"""Un error de base no lleva los parametros de la consulta.

PV-08 (auditoria de privacidad, 2026-09-24): el engine se creaba sin
``hide_parameters``, asi que el texto de cualquier ``DBAPIError`` terminaba
en ``[parameters: (...)]`` con emails y telefonos. Ese texto va al log
``db_error`` de ``main.py`` (con ``exc_info``) y al evento de Sentry.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from core.database import engine


@pytest.mark.asyncio
async def test_el_error_de_base_no_repite_los_parametros() -> None:
    telefono = "+5491155550042"

    with pytest.raises(DBAPIError) as exc_info:
        async with engine.connect() as conn:
            await conn.execute(
                text("SELECT * FROM tabla_que_no_existe WHERE phone = :phone"),
                {"phone": telefono},
            )

    assert telefono not in str(exc_info.value)
    assert "hide_parameters" in str(exc_info.value)
