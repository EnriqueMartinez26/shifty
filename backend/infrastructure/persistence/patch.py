"""Aplicar un PATCH a una entidad mapeada respetando el ``null`` explicito.

Vivia como ``_apply_patch`` dentro de ``modules/superadmin/repository.py``
(B3-19, 2026-09-18) y por eso la regla valia en un router y no en el de al
lado: ``/users/`` seguia con ``if value is not None: setattr(...)``, asi que
desde el panel de la tienda no se podia borrar el telefono de un usuario
(AUD2-B3-08, 2026-09-20). Al ser una regla de persistencia y no de un modulo,
se comparte desde aca.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import inspect as sa_inspect


def apply_patch(entity: Any, payload: dict[str, Any]) -> None:
    """Aplica un PATCH respetando el null explicito.

    El llamador ya descarto lo que no vino (``model_dump(exclude_unset=True)``),
    asi que cada clave del payload es algo que el cliente mando. Un ``null``
    borra el valor si la columna admite NULL (telefono, logo, descripcion,
    vencimiento); en una columna NOT NULL se ignora, en vez de terminar en un
    409 que el usuario no puede interpretar.

    La nulabilidad se lee del mapeo real y no de una lista escrita a mano: una
    lista se desactualiza con la primera migracion que cambie una columna.
    """
    columnas = sa_inspect(type(entity)).columns
    for key, value in payload.items():
        if value is None:
            columna = columnas.get(key)
            if columna is None or not columna.nullable:
                continue
        setattr(entity, key, value)
