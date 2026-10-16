"""Run inside the NAS image as postgres; owns only a fresh /tmp fixture cluster.

No network port is published, no real service/configuration is read, and all
subprocess output is private. This is a client-format/TLS/encryption drill, not
the canonical application bookkeeping verifier or actual NAS acceptance.
"""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import tempfile


def execute(args, *, env=None, capture=False):
    return subprocess.run(args, env=env, check=True, stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL, timeout=90).stdout


def main():
    spec = importlib.util.spec_from_file_location("nas", "/opt/tabula/nas_postgres_backup.py")
    nas = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(nas)
    os.umask(0o077)
    root = Path(tempfile.mkdtemp(prefix="tabula-294-smoke-"))
    data = root / "cluster"
    password = secrets.token_urlsafe(24)
    pwfile = root / "password"
    pwfile.write_text(password)
    env = {**os.environ, "PGHOST": "localhost", "PGUSER": "postgres", "PGPASSWORD": password, "PGDATABASE": "postgres"}
    started = False
    stage = "fixture"
    try:
        execute(["openssl", "req", "-new", "-x509", "-nodes", "-days", "1", "-subj", "/CN=localhost",
                 "-addext", "subjectAltName=DNS:localhost", "-keyout", str(root / "server.key"), "-out", str(root / "server.crt")])
        execute(["initdb", "-D", str(data), "-U", "postgres", "-A", "scram-sha-256", "--pwfile", str(pwfile)])
        execute(["pg_ctl", "-D", str(data), "-l", str(root / "server.log"), "-o",
                 f"-c listen_addresses=localhost -c ssl=on -c ssl_cert_file={root}/server.crt -c ssl_key_file={root}/server.key", "-w", "start"])
        started = True
        def sql(query, database="postgres"):
            return execute(["psql", "-X", "-w", "-qAt", "-v", "ON_ERROR_STOP=1", "-d", database, "-c", query], env=env, capture=True)
        sql("CREATE DATABASE ledger")
        sql("""CREATE TABLE alembic_version(version_num varchar(32) PRIMARY KEY);
INSERT INTO alembic_version VALUES ('0005_bookkeeping_cutover');
CREATE EXTENSION pgcrypto;
CREATE TABLE entities(id text PRIMARY KEY);
INSERT INTO entities VALUES ('alpha'), ('beta');
CREATE TABLE postings(entity text REFERENCES entities, id int, amount numeric, PRIMARY KEY(entity,id));
INSERT INTO postings VALUES ('alpha',1,10),('alpha',2,-10),('beta',1,27),('beta',2,-27);
CREATE TABLE control_inventory(id int PRIMARY KEY, label text);
INSERT INTO control_inventory VALUES (1,'outside-bookkeeping-scope');
CREATE FUNCTION preserved_function() RETURNS integer LANGUAGE sql AS 'SELECT 42';
REVOKE ALL ON TABLE control_inventory FROM PUBLIC;""", "ledger")
        storage = root / "backups"
        storage.mkdir(mode=0o700)
        marker = "b" * 32
        (storage / ".tabula-nas-storage").write_text(marker)
        execute(["age-keygen", "-o", str(root / "identity")])
        recipient = execute(["age-keygen", "-y", str(root / "identity")], capture=True)
        recipients = root / "recipients"
        recipients.write_bytes(recipient)
        service = root / "service"
        service.write_text(f"""[backup]
host=localhost
port=5432
dbname=ledger
user=postgres
sslmode=verify-full
sslrootcert={root}/server.crt
channel_binding=require
connect_timeout=15
""")
        passfile = root / "pgpass"
        passfile.write_text(f"localhost:5432:ledger:postgres:{password}\n")
        configfile = root / "backup.json"
        configfile.write_text(json.dumps({"environment": "production", "storage": str(storage), "storage_marker": marker,
                                        "source_sha256": hashlib.sha256(b"localhost:5432/ledger").hexdigest(),
                                        "service_file": str(service), "passfile": str(passfile),
                                        "recipients_file": str(recipients), "minimum_free_bytes": 1}))
        stage = "configuration"
        config = nas.load_config(configfile)
        stage = "source"
        info = nas.source_info(nas.child_environment(config))
        assert info["tls"] is True
        stage = "backup"
        result = nas.backup(config)
        generation = nas.namespace(config) / "complete" / result["generation"]
        nas.verify_generation(config, result["generation"])
        stage = "restore"
        restored_dump = root / "restore.dump"
        execute(["age", "--decrypt", "--identity", str(root / "identity"), "--output", str(restored_dump),
                 str(generation / "database.dump.age")])
        sql("CREATE DATABASE isolated_restore")
        execute(["pg_restore", "-w", "--exit-on-error", "--dbname", "isolated_restore", str(restored_dump)], env=env)
        checks = ["SELECT * FROM entities ORDER BY id", "SELECT * FROM postings ORDER BY entity,id",
                  "SELECT * FROM control_inventory", "SELECT * FROM alembic_version",
                  "SELECT entity,sum(amount) FROM postings GROUP BY entity ORDER BY entity",
                  "SELECT extname,extversion FROM pg_extension ORDER BY extname", "SELECT preserved_function()",
                  "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename",
                  "SELECT table_name,grantee,privilege_type FROM information_schema.table_privileges WHERE table_schema='public' ORDER BY table_name,grantee,privilege_type"]
        stage = "content"
        for index, query in enumerate(checks):
            stage = f"content_{index}"
            assert sql(query, "ledger") == sql(query, "isolated_restore")
        # A real authentication failure leaves the previous usable generation intact.
        stage = "failed_run"
        passfile.write_text("localhost:5432:ledger:postgres:wrong-synthetic-password\n")
        try:
            nas.backup(config)
        except nas.BackupError:
            pass
        else:
            raise AssertionError
        nas.verify_generation(config, result["generation"])
        assert nas.health(config, nas.instant())["status"] == "failed"
        # Corrupt retained ciphertext is detected without decrypting or printing it.
        stage = "corruption"
        archive = generation / "database.dump.age"
        with archive.open("ab") as stream:
            stream.write(b"tamper")
        try:
            nas.verify_generation(config, result["generation"])
        except nas.BackupError:
            pass
        else:
            raise AssertionError
        print(json.dumps({"status": "passed", "scope": "synthetic_client_roundtrip", "tls": True,
                          "restored_entities": 2, "overlapping_local_ids": True}))
        return 0
    except Exception as error:
        print(json.dumps({"status": "failed", "code": "synthetic_roundtrip", "stage": stage,
                          "kind": type(error).__name__}))
        return 1
    finally:
        if started:
            execute(["pg_ctl", "-D", str(data), "-m", "immediate", "-w", "stop"])
        # Only the fresh fixture directory created by this process is removed.
        shutil.rmtree(root)


if __name__ == "__main__":
    raise SystemExit(main())
