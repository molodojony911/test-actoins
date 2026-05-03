from datetime import datetime

from fastapi import FastAPI

app = FastAPI(title="Test Backend", version="0.1.0")


@app.get("/time")
def get_server_time() -> dict[str, str]:
    """Текущее локальное время сервера в формате ISO 8601 (с часовым поясом)."""
    return {"server_time": datetime.now().astimezone().isoformat()}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
