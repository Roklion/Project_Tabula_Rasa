"""Private metadata subprocess; launched only with the runner's sanitized PG environment."""

import json
import sys


def source_metadata(source_kind=None):
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
        if source_kind == "connection_custody":
            if connection.execute("SELECT to_regclass('public.alembic_version')").fetchone()[0] is not None:
                raise ValueError("source")
            connection.execute("SELECT reference, ciphertext FROM connection_custody.grants LIMIT 0")
            schema = "connection_custody"
        else:
            schema = connection.execute(
                "SELECT string_agg(version_num, ',' ORDER BY version_num) FROM public.alembic_version"
            ).fetchone()[0]
        return {"server_version_num": connection.info.server_version,
                "schema_version": schema, "tls": bool(tls)}


def main(argv=()):
    try:
        if tuple(argv) not in {(), ("connection_custody",)}:
            return 1
        metadata = source_metadata(*argv)
    except Exception:
        # Provider exceptions can include endpoints, roles and passwords.
        return 1
    print(json.dumps(metadata))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
