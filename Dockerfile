FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

COPY pyproject.toml ./
RUN pip install --upgrade pip setuptools wheel && \
    pip install fastapi 'uvicorn[standard]' numpy pydantic

COPY world ./world

EXPOSE 8000
CMD ["uvicorn", "world.api:app", "--host", "0.0.0.0", "--port", "8000"]
