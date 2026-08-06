"""Middleware and exception handlers for standard response envelope."""

import uuid
from datetime import datetime, timezone
from typing import Any, Optional
from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

STATUS_CODE_TO_ERROR_CODE = {
    400: "VALIDATION_ERROR",
    401: "UNAUTHORIZED",
    403: "RISK_POLICY_VIOLATION",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "ACTION_PLAN_CHANGED",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    500: "INTERNAL_ERROR",
    503: "INTEGRATION_UNAVAILABLE",
}


def build_meta(request_id: Optional[str] = None, next_cursor: Optional[str] = None) -> dict[str, Any]:
    meta = {
        "request_id": request_id or str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if next_cursor is not None:
        meta["next_cursor"] = next_cursor
    return meta


def build_response(data: Any = None, meta: Optional[dict[str, Any]] = None, error: Optional[dict[str, Any]] = None, status_code: int = 200) -> JSONResponse:
    if meta is None:
        meta = build_meta()
    body = {
        "data": data,
        "meta": meta,
        "error": error,
    }
    return JSONResponse(status_code=status_code, content=body)


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    meta = build_meta(request_id=request_id)

    code = STATUS_CODE_TO_ERROR_CODE.get(exc.status_code, "UNKNOWN_ERROR")
    message = str(exc.detail)
    details = {}

    if isinstance(exc.detail, dict):
        code = exc.detail.get("code", code)
        message = exc.detail.get("message", str(exc.detail))
        details = exc.detail.get("details", {})

    headers = {}
    if exc.status_code == status.HTTP_405_METHOD_NOT_ALLOWED:
        headers["Allow"] = getattr(exc, "headers", {}).get("Allow", "GET, POST, PATCH, PUT, DELETE")

    error_obj = {
        "code": code,
        "message": message,
        "details": details,
    }

    return JSONResponse(
        status_code=exc.status_code,
        headers=headers if headers else None,
        content={
            "data": None,
            "meta": meta,
            "error": error_obj,
        },
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    meta = build_meta(request_id=request_id)

    error_obj = {
        "code": "VALIDATION_ERROR",
        "message": "Request body failed schema validation",
        "details": {"errors": exc.errors()},
    }

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "data": None,
            "meta": meta,
            "error": error_obj,
        },
    )
