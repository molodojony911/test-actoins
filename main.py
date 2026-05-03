from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import FastAPI, HTTPException, Query

app = FastAPI(title="Test Backend", version="0.1.0")


@app.get("/time")
def get_server_time() -> dict[str, str]:
    """Текущее локальное время сервера в формате ISO 8601 (с часовым поясом)."""
    return {"server_time": datetime.now().astimezone().isoformat()}


@app.get("/date")
def get_server_date() -> dict[str, str]:
    """Текущая локальная дата сервера (ISO 8601: YYYY-MM-DD)."""
    return {"server_date": datetime.now().astimezone().date().isoformat()}


@app.get("/date/utc")
def get_server_date_utc() -> dict[str, str]:
    """Текущая дата по UTC (ISO 8601: YYYY-MM-DD)."""
    return {"server_date_utc": datetime.now(timezone.utc).date().isoformat()}


@app.get("/time/convert")
def convert_time_to_zone(
    to_zone: str = Query(
        ...,
        alias="to",
        description="Часовой пояс IANA, например Europe/Moscow или America/New_York",
    ),
    at: str | None = Query(
        None,
        description=(
            "Момент времени в ISO 8601 с указанием зоны (Z или ±смещение). "
            "Если не задан — используется текущий момент по UTC."
        ),
    ),
) -> dict[str, str]:
    """Переводит момент времени в выбранный часовой пояс."""
    try:
        target_tz = ZoneInfo(to_zone)
    except ZoneInfoNotFoundError:
        raise HTTPException(status_code=400, detail=f"Неизвестный часовой пояс: {to_zone}")

    if at is not None:
        s = at.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            instant = datetime.fromisoformat(s)
        except ValueError:
            raise HTTPException(status_code=400, detail="Некорректная дата/время ISO 8601")
        if instant.tzinfo is None:
            raise HTTPException(
                status_code=400,
                detail="Укажите зону в строке времени (например Z или +03:00)",
            )
    else:
        instant = datetime.now(timezone.utc)

    utc = instant.astimezone(timezone.utc)
    local = instant.astimezone(target_tz)

    return {
        "to_zone": to_zone,
        "input_utc": utc.isoformat(),
        "local_time": local.isoformat(),
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
