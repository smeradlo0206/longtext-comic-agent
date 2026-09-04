FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY comic_agent ./comic_agent
COPY src ./src
COPY web_console ./web_console
COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir uv && uv pip install --system -e .
CMD ["uvicorn", "comic_agent.main:app", "--host", "0.0.0.0", "--port", "8000"]
