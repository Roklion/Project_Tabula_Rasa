"""Private metadata subprocess; launched only with the runner's sanitized PG environment."""

import json


def source_metadata():
    # Keep the parent runner independent of application/Psycopg imports.
    import psycopg

    with psycopg.connect("service=backup", sslmode="verify-full",
                         channel_binding="require", connect_timeout=15) as connection:
        # PQsslInUse measures this client's TLS session, including a TLS proxy.
        # Backend pg_stat_ssl cannot establish whether the client link is secure.
        tls = connection.pgconn.ssl_in_use
        if not tls:
            raise ValueError("source")
        connection.execute("SET TRANSACTION READ ONLY")
        schema = connection.execute(
            "SELECT string_agg(version_num, ',' ORDER BY version_num) FROM public.alembic_version"
        ).fetchone()[0]
        return {"server_version_num": connection.info.server_version,
                "schema_version": schema, "tls": bool(tls)}


def main():
    try:
        metadata = source_metadata()
    except Exception:
        # Provider exceptions can include endpoints, roles and passwords.
        return 1
    print(json.dumps(metadata))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
