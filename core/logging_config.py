from __future__ import annotations

import contextvars
import json
import logging
import os
from datetime import datetime, timezone

_request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


class RequestIDFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=True)


def set_request_id(request_id: str) -> contextvars.Token:
    return _request_id_var.set(request_id)


def reset_request_id(token: contextvars.Token) -> None:
    _request_id_var.reset(token)


def get_request_id() -> str:
    return _request_id_var.get()


def _resolve_log_format() -> str:
    configured = os.getenv("ECOM_LOG_FORMAT", "").strip().lower()
    if configured in {"json", "text"}:
        return configured

    env = os.getenv("ECOM_ENV") or os.getenv("PYTHON_ENV") or os.getenv("ENV") or ""
    if env.strip().lower() == "production":
        return "json"
    return "text"


def setup_logging() -> None:
    root = logging.getLogger()
    log_level = os.getenv("ECOM_LOG_LEVEL", "INFO").upper()
    root.setLevel(getattr(logging, log_level, logging.INFO))

    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler()
    if _resolve_log_format() == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s [request_id=%(request_id)s] %(message)s"))

    handler.addFilter(RequestIDFilter())
    root.addHandler(handler)
