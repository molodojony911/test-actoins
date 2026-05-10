"""Настройка отправки логов в Grafana Loki (HTTP push API)."""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

_LOKI_ATTACHED = False


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
        base = push_url.rstrip("/").removesuffix("/loki/api/v1/push")
        self.push_url = f"{base}/loki/api/v1/push"
        self.static_labels = static_labels
        self.org_id = org_id
        self.basic_token: str | None = None
        if basic_user is not None and basic_password is not None:
            raw = f"{basic_user}:{basic_password}".encode("utf-8")
            self.basic_token = base64.b64encode(raw).decode("ascii")
        self.timeout = timeout

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            ts_ns = str(int(time.time() * 1_000_000_000))
            stream_labels = {**self.static_labels, "level": record.levelname.lower()}
            payload: dict[str, Any] = {
                "streams": [
                    {
                        "stream": stream_labels,
                        "values": [[ts_ns, msg]],
                    }
                ]
            }
            data = json.dumps(payload).encode("utf-8")
            req = Request(
                self.push_url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            if self.org_id:
                req.add_header("X-Scope-OrgID", self.org_id)
            if self.basic_token:
                req.add_header("Authorization", f"Basic {self.basic_token}")
            urlopen(req, timeout=self.timeout)
        except (OSError, URLError, ValueError):
            self.handleError(record)


def setup_logging() -> None:
    """Консоль для приложения; при LOKI_URL — ещё push в Loki (один раз)."""
    app_log = logging.getLogger("app")
    app_log.setLevel(logging.INFO)
    if not app_log.handlers:
        stream = logging.StreamHandler()
        stream.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(message)s"),
        )
        app_log.addHandler(stream)

    global _LOKI_ATTACHED
    url = (os.environ.get("LOKI_URL") or "http://loki:3100").strip()
    if not url or _LOKI_ATTACHED:
        return
    _LOKI_ATTACHED = True

    app_label = (os.environ.get("LOKI_APP_LABEL") or "").strip() or "test-gitact"
    env_label = (os.environ.get("LOKI_ENV") or "").strip() or "production"
    static_labels = {
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
    handler.setFormatter(logging.Formatter("%(message)s"))

    for name in ("app", "uvicorn", "uvicorn.access", "uvicorn.error"):
        log = logging.getLogger(name)
        log.setLevel(logging.INFO)
        log.addHandler(handler)
