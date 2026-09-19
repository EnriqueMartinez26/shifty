from __future__ import annotations

import functools
import inspect
from typing import Any, Callable

from fastapi import APIRouter
from fastapi.datastructures import DefaultPlaceholder
from fastapi.responses import Response
from fastapi.routing import APIRoute

from core.responses import ApiSuccess


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


class CanonicalAPIRouter(APIRouter):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("route_class", CanonicalRoute)
        super().__init__(*args, **kwargs)
