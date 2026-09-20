"""El opaco de auditoria no delata el contador ni cambia entre lecturas (AUD2-B3-14)."""

from modules.audit.public_id import opaque_audit_log_id


def test_es_estable_y_no_es_el_entero() -> None:
    assert opaque_audit_log_id(7) == opaque_audit_log_id(7)
    assert opaque_audit_log_id(7) != "7"
    assert not opaque_audit_log_id(7).isdigit()
    assert len(opaque_audit_log_id(7)) == 32


def test_dos_filas_consecutivas_no_se_parecen() -> None:
    a, b = opaque_audit_log_id(1000), opaque_audit_log_id(1001)
    assert a != b
    # Un contador ofuscado "a medias" (base distinta, offset) conserva el orden
    # o comparte prefijo; un HMAC no.
    assert a[:8] != b[:8]
