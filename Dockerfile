# AgentBase Runtime contract: port 8080, GET /health → 200.
# KHÔNG bake credential vào image — inject qua env khi deploy.
FROM python:3.12.10-slim

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir .

COPY app/ app/
COPY web/ web/
COPY migrations/ migrations/
COPY seeds/ seeds/
COPY alembic.ini ./

# SQLite fallback cho contest (data/ là ephemeral nếu không mount volume).
# Production: set DATABASE_URL=postgresql://... qua env để dùng Postgres bền vững.
RUN mkdir -p /app/data
ENV DATABASE_URL=sqlite:////app/data/hub.db

EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
