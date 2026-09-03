"""
bd:deps-2026-09 S2 — `/api/v1` response envelope mechanics (ADR-002).

Single mechanical "wrap point" on the backend, mirroring the single
"unwrap point" ADR-002 mandates on the frontend (`api.js`'s axios
interceptor). Two halves:

  - ``EnvelopingAPIRoute``: wraps 2xx JSON response bodies in
    ``{data, meta}``. Applied via ``route_class=`` on the 12 routers
    mounted under `/api/v1` plus `ai_chat.router` (its JSON endpoints
    adopt the envelope per r3-1 even though the path stays unversioned;
    its streaming `/chat` response is detected and passed through
    untouched).
  - ``install_error_envelope(app)``: global exception handlers that
    envelope ``HTTPException``/``RequestValidationError`` responses for
    `/api/v1/*` and `/api/ai/*` paths only. The 3 unversioned exceptions
    (`/api/health`, `/api/ws/prices`, and `/api/ai/chat`'s own SSE error
    frames) are untouched by these handlers — `/api/health` isn't under
    either prefix; WS doesn't raise HTTPException; SSE errors are yielded
    as stream frames, never hit exception middleware. S-AC-5: error
    bodies never carry an exception class name, traceback, SQL fragment,
    or filesystem path.

Deliberately NOT covered (documented scope boundary, not silently
dropped): unhandled 500s (bugs, not `raise HTTPException(...)`) keep
FastAPI's existing default handling — pre-migration behavior was already
"no debug info leaked" (`main.py` never sets `debug=True`), so this is a
no-regression carve-out, not a gap. Adding a global `Exception` handler
here would intercept ServerErrorMiddleware's already-safe default and was
judged too high a blast-radius change for one atomic commit.
"""
from __future__ import annotations

import json
import uuid
from typing import Callable

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exception_handlers import (
    http_exception_handler as _default_http_exception_handler,
    request_validation_exception_handler as _default_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse, StreamingResponse

from schemas.common import BaseResponse, DataStatus


def _is_enveloped_path(path: str) -> bool:
    """v1 (12 modules) + ai_chat's JSON sub-routes. NOT the 3 unversioned
    exceptions (`/api/health`, `/api/ws/prices`, ai_chat's SSE frames
    don't reach this function at all — they never raise HTTPException)."""
    return path.startswith("/api/v1/") or path.startswith("/api/ai/")


class EnvelopingAPIRoute(APIRoute):
    """Wraps a route's 2xx JSON body in ``{data, meta}``.

    Passes through unchanged: streaming responses (SSE), non-JSON
    responses, 204 No Content (HTTP forbids a body), and anything >= 400
    (errors are the exception handlers' job — see
    ``install_error_envelope``, they run at a different layer and never
    reach this wrapper).
    """

    def get_route_handler(self) -> Callable:
        original_route_handler = super().get_route_handler()

        async def enveloping_handler(request: Request) -> Response:
            response = await original_route_handler(request)

            content_type = response.headers.get("content-type", "")
            if (
                isinstance(response, StreamingResponse)
                or "application/json" not in content_type
                or response.status_code == 204
                or not response.body
                or response.status_code >= 400
            ):
                return response

            try:
                body = json.loads(response.body)
            except (ValueError, TypeError):
                return response

            request_id = getattr(request.state, "request_id", None) or str(uuid.uuid4())
            envelope = BaseResponse.ok(data=body, request_id=request_id)

            # bd:deps-2026-09 S2 (ADR-004) — opt-in pagination meta. A list
            # handler that supports limit/offset sets
            # `request.state.pagination = {"total": ..., "limit": ..., "offset": ...}`
            # before returning; everything else leaves meta.total/limit/offset
            # as None (additive field, schemas/common.py).
            pagination = getattr(request.state, "pagination", None)
            if pagination:
                envelope.meta.total = pagination.get("total")
                envelope.meta.limit = pagination.get("limit")
                envelope.meta.offset = pagination.get("offset")

            return JSONResponse(
                content=envelope.model_dump(mode="json"),
                status_code=response.status_code,
                headers={
                    k: v
                    for k, v in response.headers.items()
                    if k.lower() not in ("content-length", "content-type")
                },
            )

        return enveloping_handler


def enveloped_error_body(request: Request, message: str) -> dict:
    request_id = getattr(request.state, "request_id", None) or str(uuid.uuid4())
    return {
        "data": None,
        "meta": {
            "request_id": request_id,
            "data_status": DataStatus.UNAVAILABLE.value,
            "as_of": None,
            "cached_layer": None,
            "next_refresh_in": None,
            "error": {"message": message},
        },
    }


def install_error_envelope(app: FastAPI) -> None:
    """Register the v1/ai-JSON-scoped error envelope. Call once at app
    construction, after ``app = FastAPI(...)``."""

    # Registered on Starlette's BASE HTTPException (not fastapi's subclass):
    # Starlette's routing layer raises the base class directly for
    # "no route matched" (404) / "method not allowed" (405) — those never
    # go through FastAPI's HTTPException subclass, so a handler keyed to
    # the subclass alone (MRO walks toward parents, never toward
    # children) misses them, leaving a bare {"detail": "Not Found"} body
    # on /api/v1/* typo'd or wrong-method requests — breaking the "every
    # /api/v1/* response is {data,meta}" contract the frontend's single
    # central unwrap point depends on. Registering on the base class
    # still catches fastapi.HTTPException too (it IS a StarletteHTTPException
    # via inheritance, so its MRO includes this key).
    @app.exception_handler(StarletteHTTPException)
    async def _enveloped_http_exception_handler(request: Request, exc: StarletteHTTPException):
        if not _is_enveloped_path(request.url.path):
            return await _default_http_exception_handler(request, exc)
        detail = exc.detail if isinstance(exc.detail, str) else "Request failed"
        return JSONResponse(
            enveloped_error_body(request, detail),
            status_code=exc.status_code,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _enveloped_validation_exception_handler(request: Request, exc: RequestValidationError):
        if not _is_enveloped_path(request.url.path):
            return await _default_validation_exception_handler(request, exc)
        return JSONResponse(
            enveloped_error_body(request, "Validation failed"),
            status_code=422,
        )
