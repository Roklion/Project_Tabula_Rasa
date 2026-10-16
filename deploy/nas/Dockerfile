# Client-only job image; its entrypoint never initializes a database server.
# Build for linux/arm64 on the selected DS220j; retain the resulting image digest.
FROM postgres:18.6-bookworm@sha256:afc7e2d441324c0388fa80c3d24f733b4194a4eb7f47dd8ee2b08eb1a24a647c
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 age tzdata ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY scripts/nas_postgres_backup.py /opt/tabula/nas_postgres_backup.py
ENV PYTHONDONTWRITEBYTECODE=1
ENTRYPOINT ["python3", "/opt/tabula/nas_postgres_backup.py"]
