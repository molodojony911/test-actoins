from datetime import datetime, timezone

from fastapi import FastAPI

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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
