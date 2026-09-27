"""La auditoria de las notas del profesional registra el cambio, no el texto.

2026-09-25, L3-02 (agrava PV-10). ``update_staff_notes`` copiaba el texto
completo de ``notes_staff`` (hasta 1000 caracteres, del tipo "nota clinica")
antes y despues de cada cambio a ``audit_logs``, una tabla sin purga que ademas
leen ``/reports/audit-logs`` y el superadmin. Queda quien (actor), cuando
(``created_at``) y el largo de antes y de despues; nunca el texto.
"""

from __future__ import annotations

import json

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.audit.model import AuditAction, AuditLog
from tests.integration.test_aislamiento_multitenant import _montar, _turno
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)

PRIMERA = "Paciente con antecedente de ansiedad, medicacion X"
SEGUNDA = "Refiere alergia a la penicilina"


@pytest.mark.asyncio
async def test_editar_la_nota_audita_el_hecho_sin_el_texto(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    tienda = await _montar(client, slug="l302-notas", email="l302@test.com")
    turno = await _turno(client, tienda, hora=10, clave="l302-notas-1")
    for texto in (PRIMERA, SEGUNDA):
        res = await client.patch(
            f"/appointments/{turno}/notes-staff",
            json={"notes_staff": texto},
            headers=auth_headers(tienda.token),
        )
        assert res.status_code == 200, res.text
        assert res.json()["notes_staff"] == texto

    filas = (
        (
            await test_session.execute(
                select(AuditLog)
                .where(
                    AuditLog.resource_id == turno,
                    AuditLog.action == AuditAction.UPDATE.value,
                )
                .order_by(AuditLog.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(filas) == 2
    primera, segunda = filas
    assert primera.actor_id is not None and primera.created_at is not None
    assert primera.payload_before == {
        "notes_staff_changed": True,
        "notes_staff_length": 0,
    }
    assert primera.payload_after == {
        "notes_staff_changed": True,
        "notes_staff_length": len(PRIMERA),
    }
    assert segunda.payload_before == {
        "notes_staff_changed": True,
        "notes_staff_length": len(PRIMERA),
    }
    assert segunda.payload_after == {
        "notes_staff_changed": True,
        "notes_staff_length": len(SEGUNDA),
    }

    lectura = await client.get(
        "/reports/audit-logs",
        params={"resource_id": turno},
        headers=auth_headers(tienda.token),
    )
    assert lectura.status_code == 200, lectura.text
    texto = json.dumps(lectura.json())
    assert "ansiedad" not in texto and "penicilina" not in texto
