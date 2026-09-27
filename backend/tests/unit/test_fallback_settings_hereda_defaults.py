"""El respaldo de settings hereda los defaults de la clase, no los copia.

2026-09-17 (audit B7-05): ``_fallback_settings`` reescribia a mano 60+
valores por defecto de ``Settings`` (91 lineas). Sintoma: una segunda tabla de
configuracion que nadie mantiene; campos agregados despues
(``MAX_UPLOAD_BODY_BYTES``, ``WAITLIST_OFFER_MINUTES``) ya no figuraban en la
copia, y cambiar un default en la clase no cambiaba el del respaldo.

``Settings.model_construct`` completa con el default de la clase todo campo
no provisto, asi que el respaldo solo tiene que declarar lo que de verdad
difiere: obligatorios, endurecimientos deliberados y lo que lee del entorno.
"""

from typing import Any

import pytest

from core.config import Environment, Settings, _fallback_settings

# Lo UNICO que el respaldo puede fijar distinto del default de la clase.
# Cualquier otro campo tiene que salir de ``Settings`` para que no haya dos
# tablas de defaults. Agregar algo aca es una decision, no un descuido.
CAMPOS_PROPIOS_DEL_RESPALDO = {
    # Obligatorios: no tienen default en la clase.
    "SECRET_KEY",
    "DATABASE_URL",
    "REDIS_URL",
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_USER",
    "SMTP_PASS",
    "EMAILS_FROM_EMAIL",
    # Endurecimientos deliberados del respaldo.
    "COOKIE_SECURE",
    "EXPOSE_API_DOCS",
    "RATE_LIMIT_ENABLED",
    "FIELD_ENCRYPTION_KEY",
    # Leidos del entorno para que el 503 salga con las URLs del deploy.
    "FRONTEND_URL",
    "PUBLIC_API_URL",
    "CORS_ORIGINS",
}


def test_el_respaldo_hereda_un_default_cambiado_en_la_clase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si la clase cambia un default, el respaldo lo refleja sin tocar nada mas."""
    campo = Settings.model_fields["REPORT_MAX_RANGE_DAYS"]
    assert campo.default == 370
    monkeypatch.setattr(campo, "default", 999)

    assert _fallback_settings().REPORT_MAX_RANGE_DAYS == 999


def test_el_respaldo_no_redeclara_ningun_default_de_la_clase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # El conftest deja estas tres iguales al default de la clase; con valores
    # propios se ve que el respaldo las toma del entorno y de ningun otro lado.
    monkeypatch.setenv("FRONTEND_URL", "https://app.example.com")
    monkeypatch.setenv("PUBLIC_API_URL", "https://api.example.com")
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com")
    defaults = Settings.model_construct()
    respaldo = _fallback_settings()
    distintos: dict[str, tuple[Any, Any]] = {}
    for nombre in Settings.model_fields:
        esperado = getattr(defaults, nombre, "<sin default>")
        real = getattr(respaldo, nombre, "<sin valor>")
        if esperado != real:
            distintos[nombre] = (esperado, real)

    assert set(distintos) == CAMPOS_PROPIOS_DEL_RESPALDO, distintos


def test_el_respaldo_tiene_valor_para_todos_los_campos() -> None:
    """Un obligatorio olvidado no falla al construir: falla con AttributeError al usarlo."""
    respaldo = _fallback_settings()
    for nombre in Settings.model_fields:
        assert hasattr(respaldo, nombre), nombre


def test_el_respaldo_conserva_los_endurecimientos() -> None:
    """Riesgo del cambio: que un endurecimiento vuelva al default laxo de la clase."""
    respaldo = _fallback_settings()

    assert respaldo.ENV == Environment.DEVELOPMENT
    assert respaldo.EXPOSE_API_DOCS is False
    assert respaldo.RATE_LIMIT_ENABLED is False
    assert respaldo.COOKIE_SECURE is True
    # Secretos aleatorios por proceso: nada firma ni cifra con un valor del repo.
    assert respaldo.SECRET_KEY.startswith("boot-failed-")
    assert len(respaldo.SECRET_KEY) > len("boot-failed-") + 32
    assert respaldo.FIELD_ENCRYPTION_KEY is not None
    assert respaldo.FIELD_ENCRYPTION_KEY.startswith("boot-failed-")
    assert _fallback_settings().SECRET_KEY != respaldo.SECRET_KEY


def test_el_respaldo_lee_las_urls_del_entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FRONTEND_URL", "https://app.example.com")
    monkeypatch.setenv("PUBLIC_API_URL", "https://api.example.com")
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com")

    respaldo = _fallback_settings()

    assert respaldo.FRONTEND_URL == "https://app.example.com"
    assert respaldo.PUBLIC_API_URL == "https://api.example.com"
    assert respaldo.CORS_ORIGINS == "https://app.example.com"
