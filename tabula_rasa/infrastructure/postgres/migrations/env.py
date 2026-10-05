"""Migrations accept a connection only; no URL, credentials, or logging config."""

from alembic import context

connection = context.config.attributes.get("connection")
if connection is None:
    raise RuntimeError("Use python -m tabula_rasa.infrastructure.postgres upgrade/current/downgrade.")

context.configure(connection=connection, transactional_ddl=True)
with context.begin_transaction():
    context.run_migrations()
