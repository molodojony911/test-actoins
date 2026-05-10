FROM python:3.12-slim-bookworm

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LOKI_URL=http://loki:3100

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py logging_loki.py .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
