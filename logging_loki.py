"""Настройка отправки логов в Grafana Loki (HTTP push API) и JSON-форматирование."""

from __future__ import annotations

import base64
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from pythonjsonlogger.jsonlogger import JsonFormatter as BaseJsonFormatter
from urllib.error import URLError

_LOKI_ATTACHED = False


class StructuredJsonFormatter(BaseJsonFormatter):
    """JSON-строка лога: timestamp, level, logger, message + поля из extra и exc_info."""

    def __init__(self) -> None:
        super().__init__(
            fmt="%(levelname)s %(name)s %(message)s",
            json_ensure_ascii=False,
            rename_fields={
                "levelname": "level",
                "name": "logger",
            },
            timestamp=False,
        )

    def add_fields(
        self,
        log_record: dict[str, Any],
        record: logging.LogRecord,
        message_dict: dict[str, Any],
    ) -> None:
        super().add_fields(log_record, record, message_dict)
        log_record["timestamp"] = datetime.fromtimestamp(
            record.created,
            tz=timezone.utc,
        ).isoformat(timespec="microseconds")
        log_record["message"] = record.getMessage()
        if record.exc_info:
            log_record["exc_info"] = self.formatException(record.exc_info)


def get_json_formatter() -> StructuredJsonFormatter:
    return StructuredJsonFormatter()


def loki_static_labels_from_env() -> dict[str, str]:
    """Статические лейблы потока Loki из переменных окружения (как в setup_logging)."""
    app_label = (os.environ.get("LOKI_APP_LABEL") or "").strip() or "test-gitact"
    env_label = (os.environ.get("LOKI_ENV") or "").strip() or "production"
    static_labels: dict[str, str] = {
        "app": app_label,
        "env": env_label,
        "service": "fastapi",
    }
    extra = os.environ.get("LOKI_EXTRA_LABELS", "").strip()
    if extra:
        for part in extra.split(","):
            if "=" in part:
                k, _, v = part.partition("=")
                k, v = k.strip(), v.strip()
                if k and v:
                    static_labels[k] = v
    return static_labels


def _loki_resolve_push_url(url_or_base: str) -> str:
    base = url_or_base.rstrip("/").removesuffix("/loki/api/v1/push")
    return f"{base}/loki/api/v1/push"


class LokiHandler(logging.Handler):
    """Синхронная отправка строк в Loki /loki/api/v1/push."""

    def __init__(
        self,
        push_url: str,
        static_labels: dict[str, str],
        *,
        org_id: str | None = None,
        basic_user: str | None = None,
        basic_password: str | None = None,
        timeout: float = 5.0,
    ) -> None:
        super().__init__()
        self.push_url = _loki_resolve_push_url(push_url)
        self.static_labels = static_labels
        self.org_id = org_id
        self.basic_token: str | None = None
        if basic_user is not None and basic_password is not None:
            raw = f"{basic_user}:{basic_password}".encode("utf-8")
            self.basic_token = base64.b64encode(raw).decode("ascii")
        self.timeout = timeout

    def emit(self, record: logging.LogRecord) -> None:
        try:
            # Ленивый импорт: main уже загружен к моменту первого лога.
            from main import send_log_to_loki

            msg = self.format(record)
            ts_ns = int(record.created * 1_000_000_000)
            stream_labels = {**self.static_labels, "level": record.levelname.lower()}
            send_log_to_loki(
                msg,
                push_url=self.push_url,
                stream_labels=stream_labels,
                merge_with_defaults=False,
                timestamp_ns=ts_ns,
                org_id=self.org_id,
                basic_token=self.basic_token,
                timeout=self.timeout,
            )
        except (OSError, URLError, ValueError):
            self.handleError(record)


def setup_logging() -> None:
    """Консоль и Loki: один JSON-форматтер на строку лога."""
    json_fmt = get_json_formatter()

    app_log = logging.getLogger("app")
    app_log.setLevel(logging.INFO)
    if not app_log.handlers:
        stream = logging.StreamHandler()
        stream.setFormatter(json_fmt)
        app_log.addHandler(stream)
    else:
        for h in app_log.handlers:
            if isinstance(h, logging.StreamHandler):
                h.setFormatter(json_fmt)

    global _LOKI_ATTACHED
    url = (os.environ.get("LOKI_URL") or "").strip() or "http://loki:3100"
    if _LOKI_ATTACHED:
        return
    _LOKI_ATTACHED = True

    static_labels = loki_static_labels_from_env()

    org_id = (os.environ.get("LOKI_ORG_ID") or "").strip() or None
    basic_user = (os.environ.get("LOKI_BASIC_AUTH_USER") or "").strip() or None
    basic_password = (os.environ.get("LOKI_BASIC_AUTH_PASSWORD") or "").strip() or None

    handler = LokiHandler(
        url,
        static_labels,
        org_id=org_id,
        basic_user=basic_user,
        basic_password=basic_password,
        timeout=float(os.environ.get("LOKI_TIMEOUT", "5")),
    )
    handler.setLevel(logging.INFO)
    handler.setFormatter(json_fmt)

    for name in ("app", "uvicorn", "uvicorn.access", "uvicorn.error"):
        log = logging.getLogger(name)
        log.setLevel(logging.INFO)
        log.addHandler(handler)
