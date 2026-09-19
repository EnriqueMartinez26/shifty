"""La respuesta de configuracion del gateway no tiene donde llevar un secreto.

2026-09-18, X-05: se borra ``_gateway_config_response`` (payments/router.py),
un helper sin llamadores que armaba ``GatewayConfigResponse`` con
``access_token_masked="********"``. La proteccion que expresaba -- no exponer
el access token de Mercado Pago en una respuesta -- no dependia de el: vive en
el schema (``GatewayConfigResponse`` no tiene ningun campo para el token, el
refresh token ni el webhook secret) y en los tres handlers que lo arman (GET y
PUT ``/payments/gateway-config``, POST ``/payments/mercadopago/oauth/refresh``),
cubiertos por ``test_payments_feature_flag_and_webhook_idempotency``. Este test
fija la parte estructural para que ningun helper futuro pueda volver a
exponerlos.
"""

from modules.payments.schemas import GatewayConfigResponse

SECRETOS = {"access_token", "refresh_token", "webhook_secret", "client_secret"}


def test_la_respuesta_del_gateway_no_tiene_campos_para_secretos() -> None:
    campos = set(GatewayConfigResponse.model_fields)
    assert not campos & SECRETOS, campos & SECRETOS
    assert "access_token_masked" in campos
