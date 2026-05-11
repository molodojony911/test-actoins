import base64
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from logging_loki import loki_static_labels_from_env, setup_logging

logger = logging.getLogger("app")


def send_log_to_loki(
    message: str,
    *,
    push_url: str | None = None,
    stream_labels: dict[str, str] | None = None,
    merge_with_defaults: bool = True,
    level: str | None = "info",
    timestamp_ns: int | None = None,
    org_id: str | None = None,
    basic_user: str | None = None,
    basic_password: str | None = None,
    basic_token: str | None = None,
    timeout: float | None = None,
) -> None:
    """POST тела Loki push API: одна строка в ``streams[].values``.

    Эндпоинт: ``{base}/loki/api/v1/push``. При ``merge_with_defaults=True``
    к ``stream_labels`` добавляются лейблы из окружения (как у ``setup_logging``).
    """
    if push_url is None:
        url = (os.environ.get("LOKI_URL") or "").strip() or "http://loki:3100"
        base = url.rstrip("/").removesuffix("/loki/api/v1/push")
        push_url = f"{base}/loki/api/v1/push"

    if merge_with_defaults:
        labels: dict[str, str] = {**loki_static_labels_from_env(), **(stream_labels or {})}
        if level:
            labels["level"] = level.lower()
    else:
        labels = dict(stream_labels or {})

    if timestamp_ns is None:
        timestamp_ns = int(time.time() * 1_000_000_000)

    payload: dict[str, Any] = {
        "streams": [
            {
                "stream": labels,
                "values": [[str(timestamp_ns), message]],
            }
        ]
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = Request(
        push_url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    if org_id is None:
        org_id = (os.environ.get("LOKI_ORG_ID") or "").strip() or None
    if org_id:
        req.add_header("X-Scope-OrgID", org_id)

    token = basic_token
    if token is None and basic_user is not None and basic_password is not None:
        raw = f"{basic_user}:{basic_password}".encode("utf-8")
        token = base64.b64encode(raw).decode("ascii")
    if token is None:
        u = (os.environ.get("LOKI_BASIC_AUTH_USER") or "").strip() or None
        p = (os.environ.get("LOKI_BASIC_AUTH_PASSWORD") or "").strip() or None
        if u is not None and p is not None:
            raw = f"{u}:{p}".encode("utf-8")
            token = base64.b64encode(raw).decode("ascii")
    if token:
        req.add_header("Authorization", f"Basic {token}")

    to = timeout if timeout is not None else float(os.environ.get("LOKI_TIMEOUT", "5"))
    urlopen(req, timeout=to)


def _detail_for_log(detail: object) -> str:
    """Сериализация exc.detail для JSON-лога."""
    if isinstance(detail, str):
        return detail
    try:
        return json.dumps(detail, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(detail)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    yield


app = FastAPI(title="Test Backend", version="0.1.0", lifespan=lifespan)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """4xx/5xx: структурированный JSON-лог в Loki."""
    logger.warning(
        "ошибка запроса",
        extra={
            "method": request.method,
            "path": request.url.path,
            "status_code": exc.status_code,
            "detail": _detail_for_log(exc.detail),
        },
    )
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    logger.info(
        "Request processed",
        extra={
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": round(duration_ms, 3),
        },
    )
    return response


# (IANA, подсказки для поиска — город или вариант написания)
_ZONE_HINTS: list[tuple[str, tuple[str, ...]]] = [
    ("Europe/Moscow", ("москва", "moscow", "санкт-петербург", "спб", "питер", "saint petersburg")),
    ("Europe/Kaliningrad", ("калининград", "kaliningrad")),
    ("Europe/Samara", ("самара", "samara")),
    ("Asia/Yekaterinburg", ("екатеринбург", "yekaterinburg")),
    ("Asia/Omsk", ("омск", "omsk")),
    ("Asia/Krasnoyarsk", ("красноярск", "krasnoyarsk")),
    ("Asia/Irkutsk", ("иркутск", "irkutsk")),
    ("Asia/Yakutsk", ("якутск", "yakutsk")),
    ("Asia/Vladivostok", ("владивосток", "vladivostok")),
    ("Europe/Kyiv", ("киев", "kyiv", "kiev")),
    ("Europe/Minsk", ("минск", "minsk")),
    ("Europe/Warsaw", ("варшава", "warsaw")),
    ("Europe/Berlin", ("берлин", "berlin")),
    ("Europe/Paris", ("париж", "paris")),
    ("Europe/London", ("лондон", "london")),
    ("America/New_York", ("нью-йорк", "new york", "нью йорк")),
    ("America/Chicago", ("чикаго", "chicago")),
    ("America/Denver", ("денвер", "denver")),
    ("America/Los_Angeles", ("лос-анджелес", "los angeles")),
    ("Asia/Dubai", ("дубай", "dubai")),
    ("Asia/Almaty", ("алматы", "almaty", "астана", "astana")),
    ("Asia/Tokyo", ("токио", "tokyo")),
    ("Asia/Seoul", ("сеул", "seoul")),
    ("Asia/Shanghai", ("шанхай", "shanghai")),
    ("Asia/Beijing", ("пекин", "beijing")),
    ("Asia/Hong_Kong", ("гонконг", "hong kong")),
    ("Australia/Sydney", ("сидней", "sydney")),
    ("Pacific/Auckland", ("окленд", "auckland")),
    ("UTC", ("utc", "всемирное", "гринвич", "greenwich")),
]

_CITY_TO_IANA: dict[str, str] = {}
for iana, hints in _ZONE_HINTS:
    for h in hints:
        _CITY_TO_IANA[h.casefold()] = iana


def _resolve_timezone(user_input: str) -> str:
    key = user_input.strip().casefold()
    if key in _CITY_TO_IANA:
        return _CITY_TO_IANA[key]
    try:
        ZoneInfo(user_input.strip())
    except ZoneInfoNotFoundError:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Не удалось понять город или пояс «{user_input}». "
                "Откройте GET /time/cities — там список городов и точных имён поясов (IANA)."
            ),
        )
    return user_input.strip()


def _parse_local_clock(time_str: str, from_tz: ZoneInfo) -> datetime:
    raw = time_str.strip()
    now = datetime.now(from_tz)
    formats: tuple[tuple[str, bool], ...] = (
        ("%Y-%m-%d %H:%M", False),
        ("%d.%m.%Y %H:%M", False),
        ("%H:%M", True),
    )
    for fmt, today_only in formats:
        try:
            dt = datetime.strptime(raw, fmt)
            if today_only:
                dt = dt.replace(year=now.year, month=now.month, day=now.day)
            return dt.replace(tzinfo=from_tz)
        except ValueError:
            continue
    raise HTTPException(
        status_code=400,
        detail="Время: укажите как ЧЧ:ММ (сегодня у вас в городе) или 2026-05-03 14:30 или 03.05.2026 14:30",
    )


@app.get("/time")
def get_server_time() -> dict[str, str]:
    """Текущее локальное время сервера в формате ISO 8601 (с часовым поясом)."""
    iso = datetime.now().astimezone().isoformat()
    logger.info(
        "эндпоинт /time: ответ с локальным временем",
        extra={"endpoint": "/time", "server_time": iso},
    )
    return {"server_time": iso}


@app.get("/date")
def get_server_date() -> dict[str, str]:
    """Текущая локальная дата сервера (ISO 8601: YYYY-MM-DD)."""
    d = datetime.now().astimezone().date().isoformat()
    logger.info(
        "эндпоинт /date: ответ с локальной датой",
        extra={"endpoint": "/date", "server_date": d},
    )
    return {"server_date": d}


@app.get("/date/utc")
def get_server_date_utc() -> dict[str, str]:
    """Текущая дата по UTC (ISO 8601: YYYY-MM-DD)."""
    d = datetime.now(timezone.utc).date().isoformat()
    logger.info(
        "эндпоинт /date/utc: ответ с датой UTC",
        extra={"endpoint": "/date/utc", "server_date_utc": d},
    )
    return {"server_date_utc": d}


def _zone_label(hints: tuple[str, ...]) -> str:
    for h in hints:
        if any("\u0400" <= c <= "\u04ff" for c in h):
            return h.capitalize()
    h0 = hints[0]
    if h0.casefold() == "utc":
        return "UTC"
    return h0.replace("_", " ").title()


@app.get("/time/cities")
def list_time_cities() -> dict[str, list[dict[str, str]]]:
    """Города и пояса для подсказок в форме (можно искать по городу или вставить IANA)."""
    items: list[dict[str, str]] = []
    for iana, hints in _ZONE_HINTS:
        items.append(
            {
                "label": _zone_label(hints),
                "zone": iana,
                "examples": ", ".join(sorted(set(hints), key=str.lower)),
            }
        )
    n = len(items)
    logger.info(
        "эндпоинт /time/cities: отдан список городов",
        extra={"endpoint": "/time/cities", "cities_count": n},
    )
    return {"cities": items}


@app.get("/time/convert")
def convert_local_time_to_zone(
    time: str = Query(
        ...,
        description="Ваши часы: 14:30 (сегодня) или 2026-05-03 14:30 или 03.05.2026 14:30",
    ),
    from_city: str = Query(
        ...,
        description="Город, где вы сейчас (например Москва, London) или IANA вроде Europe/Moscow",
    ),
    to: str = Query(
        ...,
        description="Куда перевести: город (Токио) или пояс IANA (Asia/Tokyo)",
    ),
) -> dict[str, str]:
    """Сколько времени в другом городе/поясе, если у вас на часах указано время в вашем городе."""
    from_iana = _resolve_timezone(from_city)
    to_iana = _resolve_timezone(to)
    from_tz = ZoneInfo(from_iana)
    to_tz = ZoneInfo(to_iana)

    instant = _parse_local_clock(time, from_tz)
    there = instant.astimezone(to_tz)

    logger.info(
        "эндпоинт /time/convert: конвертация времени",
        extra={
            "endpoint": "/time/convert",
            "time_input": time.strip(),
            "from_city": from_city.strip(),
            "to_city": to.strip(),
            "from_iana": from_iana,
            "to_iana": to_iana,
            "result_local_iso": there.isoformat(),
        },
    )
    return {
        "your_input": time.strip(),
        "your_city_or_zone": from_city.strip(),
        "your_timezone": from_iana,
        "your_time_local": instant.isoformat(),
        "target_city_or_zone": to.strip(),
        "target_timezone": to_iana,
        "time_there": there.isoformat(),
        "time_there_clock": there.strftime("%H:%M, %d.%m.%Y"),
    }


@app.get("/health")
def health() -> dict[str, str]:
    logger.info(
        "эндпоинт /health: ok",
        extra={"endpoint": "/health", "health_status": "ok"},
    )
    return {"status": "ok"}
