"""Identificador opaco para una fila de auditoria.

``AuditLog.id`` es un entero autoincremental GLOBAL (sin ULID, por
performance de insercion). Devolverlo tal cual al panel regalaba el contador
de acciones auditadas de toda la plataforma: con dos lecturas se estima el
volumen y el crecimiento del resto de los tenants (AUD2-B3-14, 2026-09-20).

El opaco es un HMAC del entero con la clave del servidor, mismo patron que
``core.security.hash_otp_code``: sin la clave no se invierte aunque el espacio
de enteros sea chico, es estable entre lecturas (el front lo usa como clave de
cada entrada) y distinto por fila. No es resoluble de vuelta a la fila: ningun
endpoint busca una entrada de auditoria por este id. Si algun dia hace falta,
la respuesta es un ULID persistido con su migracion, no publicar el entero.
"""

import hashlib
import hmac

from core.config import settings

_PREFIJO = b"audit_log:"


def opaque_audit_log_id(log_id: int) -> str:
    material = _PREFIJO + str(log_id).encode("utf-8")
    digest = hmac.new(settings.SECRET_KEY.encode("utf-8"), material, hashlib.sha256)
    # 128 bits alcanzan para que no haya colisiones entre filas y no delatan
    # nada del contador; el hex completo solo alargaria la respuesta.
    return digest.hexdigest()[:32]
