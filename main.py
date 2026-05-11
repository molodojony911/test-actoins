import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from logging_loki import setup_logging

logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    yield


app = FastAPI(title="Test Backend", version="0.1.0", lifespan=lifespan)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """4xx/5xx в Loki (logger app + uvicorn.error)."""
    logger.warning(
        "ошибка %s %s: статус=%s деталь=%s",
        request.method,
        request.url.path,
        exc.status_code,
        exc.detail,
    )
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    logger.info(
        "%s %s -> %s %.1fms",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
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
    logger.info("эндпоинт /time: отдано server_time=%s", iso)
    return {"server_time": iso}


@app.get("/date")
def get_server_date() -> dict[str, str]:
    """Текущая локальная дата сервера (ISO 8601: YYYY-MM-DD)."""
    d = datetime.now().astimezone().date().isoformat()
    logger.info("эндпоинт /date: отдана server_date=%s", d)
    return {"server_date": d}


@app.get("/date/utc")
def get_server_date_utc() -> dict[str, str]:
    """Текущая дата по UTC (ISO 8601: YYYY-MM-DD)."""
    d = datetime.now(timezone.utc).date().isoformat()
    logger.info("эндпоинт /date/utc: отдана server_date_utc=%s", d)
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
    logger.info("эндпоинт /time/cities: отдано городов=%s", len(items))
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
        "эндпоинт /time/convert: время=%s от=%s (%s) в=%s (%s)",
        time.strip(),
        from_city.strip(),
        from_iana,
        to.strip(),
        to_iana,
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
    logger.info("эндпоинт /health: ok")
    return {"status": "ok"}
