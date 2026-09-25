from __future__ import annotations

import functools
import inspect
from collections.abc import Coroutine
from typing import Any, Callable

from fastapi import APIRouter, Request
from fastapi.datastructures import DefaultPlaceholder
from fastapi.responses import Response
from fastapi.routing import APIRoute

from core.responses import ApiSuccess, mark_canonical_body

# Marca en un ``Response`` que el handler devolvio tal cual (no lo armo el
# envoltorio canonico): el middleware tiene que seguir mirandolo.
_PASSTHROUGH_ATTR = "_shifty_canonical_passthrough"
# Marca en la funcion envoltorio que arma ``{success, data}``.
_WRAPPER_ATTR = "_shifty_canonical_wrapper"


def _passthrough(res: Any) -> Any:
    if isinstance(res, Response):
        setattr(res, _PASSTHROUGH_ATTR, True)
    return res


class CanonicalRoute(APIRoute):
    """Ruta que envuelve la salida en ``ApiSuccess`` via ``response_model``.

    F1-02 (plan de rendimiento, 2026-09-24): cuando la salida la arma este
    envoltorio, FastAPI ya la valida contra ``ApiSuccess[...]`` y la
    serializa canonica. La ruta lo marca en el scope
    (``mark_canonical_body``) y ``CanonicalJsonMiddleware`` no la vuelve a
    leer, decodificar y codificar. Un ``Response`` devuelto por el handler
    queda sin marca: el middleware lo trata como siempre.
    """

    def __init__(
        self,
        path: str,
        endpoint: Callable[..., Any],
        *,
        response_model: Any = None,
        **kwargs: Any,
    ) -> None:
        wrapped_response_model = response_model
        if response_model is not None and not isinstance(
            response_model, DefaultPlaceholder
        ):
            status_code = kwargs.get("status_code", 200)
            if status_code not in (204, 301, 302, 307, 308):
                is_already_wrapped = False
                try:
                    if (
                        hasattr(response_model, "__origin__")
                        and response_model.__origin__ is ApiSuccess
                    ):
                        is_already_wrapped = True
                    elif issubclass(response_model, ApiSuccess):
                        is_already_wrapped = True
                except TypeError:
                    pass

                if not is_already_wrapped:
                    wrapped_response_model = ApiSuccess[response_model]

        wrapped_endpoint = endpoint
        if (
            response_model is not None
            and not isinstance(response_model, DefaultPlaceholder)
            and wrapped_response_model is not response_model
        ):
            if inspect.iscoroutinefunction(endpoint):

                @functools.wraps(endpoint)
                async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                    res = await endpoint(*args, **kwargs)
                    if isinstance(res, Response) or (
                        isinstance(res, dict) and "success" in res
                    ):
                        return _passthrough(res)
                    return {"success": True, "data": res}

                setattr(async_wrapper, _WRAPPER_ATTR, True)
                wrapped_endpoint = async_wrapper
            else:

                @functools.wraps(endpoint)
                def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                    res = endpoint(*args, **kwargs)
                    if isinstance(res, Response) or (
                        isinstance(res, dict) and "success" in res
                    ):
                        return _passthrough(res)
                    return {"success": True, "data": res}

                setattr(sync_wrapper, _WRAPPER_ATTR, True)
                wrapped_endpoint = sync_wrapper

        # Antes de super().__init__: ahi se llama a get_route_handler. Se mira
        # la marca de la funcion y no si se envolvio ACA: ``include_router``
        # vuelve a crear la ruta con el endpoint ya envuelto y el
        # ``response_model`` ya en ``ApiSuccess``, y en esa segunda pasada no
        # se envuelve nada.
        self._emits_canonical_body = bool(
            getattr(wrapped_endpoint, _WRAPPER_ATTR, False)
        )
        super().__init__(
            path,
            wrapped_endpoint,
            response_model=wrapped_response_model,
            **kwargs,
        )

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()
        if not self._emits_canonical_body:
            return handler

        async def canonical_handler(request: Request) -> Response:
            response = await handler(request)
            if not getattr(response, _PASSTHROUGH_ATTR, False):
                mark_canonical_body(request.scope)
            return response

        return canonical_handler


class CanonicalAPIRouter(APIRouter):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("route_class", CanonicalRoute)
        super().__init__(*args, **kwargs)
