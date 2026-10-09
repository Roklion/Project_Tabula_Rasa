FROM node:24-bookworm-slim AS browser
WORKDIR /build/web
COPY web/package*.json ./
RUN npm ci
COPY web/index.html web/tsconfig.json web/vite.config.ts ./
COPY web/src ./src
RUN npm run build

FROM python:3.12-slim-bookworm AS runtime
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=10000
COPY requirements-api.txt requirements-postgres.txt ./
RUN pip install --no-cache-dir -r requirements-api.txt -r requirements-postgres.txt \
    && useradd --uid 10001 --create-home app
COPY tabula_rasa ./tabula_rasa
COPY --from=browser /build/web/dist ./web/dist
ARG RELEASE_ID
ARG SCHEMA_REVISION
LABEL org.opencontainers.image.revision=$RELEASE_ID io.tabula.schema=$SCHEMA_REVISION
ENV TABULA_RASA_RELEASE_ID=$RELEASE_ID
USER 10001
EXPOSE 10000
CMD ["python", "-m", "tabula_rasa.http.serve"]
