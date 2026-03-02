"""
Request-ID Middleware.

Behaviour:
  - If the incoming request carries  X-Request-ID  header, reuse it (supports
    propagation from API gateways / load balancers).
  - Otherwise generate a fresh UUID4.
  - Binds  request_id  into structlog contextvars → every log line emitted
    during this request will automatically contain the id.
  - Echoes  X-Request-ID  back in the response header for client-side tracing.
  - Clears contextvars after the request so the next request starts clean.
"""
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

REQUEST_ID_HEADER = "X-Request-ID"

logger = structlog.get_logger(__name__)


class RequestIDMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        # Accept forwarded id or mint a new one
        request_id = (
            request.headers.get(REQUEST_ID_HEADER)
            or str(uuid.uuid4())
        )

        # Store on request.state so route handlers can read it
        request.state.request_id = request_id

        # Inject into structlog context for this request's lifetime
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )

        response = await call_next(request)

        # Echo back to caller
        response.headers[REQUEST_ID_HEADER] = request_id

        # Clean up so the next request (different coroutine, same thread) is uncontaminated
        structlog.contextvars.clear_contextvars()

        return response
