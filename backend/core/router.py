from __future__ import annotations

import functools
import inspect
import json
from typing import Any, Callable

from fastapi import APIRouter, Request
from fastapi.datastructures import DefaultPlaceholder
from fastapi.responses import JSONResponse, Response
from fastapi.routing import APIRoute

from core.responses import ApiSuccess, _clone_response


class CanonicalRoute(APIRoute):
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
                        return res
                    return {"success": True, "data": res}

                wrapped_endpoint = async_wrapper
            else:

                @functools.wraps(endpoint)
                def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                    res = endpoint(*args, **kwargs)
                    if isinstance(res, Response) or (
                        isinstance(res, dict) and "success" in res
                    ):
                        return res
                    return {"success": True, "data": res}

                wrapped_endpoint = sync_wrapper

        super().__init__(
            path,
            wrapped_endpoint,
            response_model=wrapped_response_model,
            **kwargs,
        )

    def get_route_handler(self) -> Callable[..., Any]:
        original_route_handler = super().get_route_handler()

        async def custom_route_handler(request: Request) -> Response:
            response = await original_route_handler(request)
            if request.headers.get("x-raw-response") == "true":
                if (
                    response.status_code >= 200
                    and response.status_code < 300
                    and "application/json"
                    in response.headers.get("content-type", "").lower()
                ):
                    body = bytes(response.body)

                    try:
                        payload = json.loads(body)
                        if (
                            isinstance(payload, dict)
                            and payload.get("success") is True
                            and "data" in payload
                        ):
                            unwrapped = JSONResponse(
                                content=payload["data"],
                                status_code=response.status_code,
                            )
                            # Anexar los headers originales en crudo (sin
                            # content-type/length, que ya puso JSONResponse):
                            # un dict colapsaria Set-Cookie duplicados.
                            unwrapped.raw_headers = list(unwrapped.raw_headers) + [
                                (k, v)
                                for k, v in response.raw_headers
                                if k not in (b"content-length", b"content-type")
                            ]
                            return unwrapped
                    except Exception:
                        pass

                    return _clone_response(response, body)
            return response

        return custom_route_handler


class CanonicalAPIRouter(APIRouter):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("route_class", CanonicalRoute)
        super().__init__(*args, **kwargs)
