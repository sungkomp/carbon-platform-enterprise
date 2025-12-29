from __future__ import annotations
import os
from alembic import context
from sqlalchemy import engine_from_config, pool
from app.db import Base
from app import models  # noqa
from app.auth import models as auth_models  # noqa
from app.tenancy import models as tenancy_models  # noqa
from app.history import models as history_models  # noqa

config = context.config
target_metadata = Base.metadata

def get_url():
    return os.getenv("DATABASE_URL", "postgresql+psycopg://carbon:carbon@localhost:5432/carbon")

def run_migrations_offline():
    context.configure(url=get_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online():
    cfg = config.get_section(config.config_ini_section) or {}
    cfg["sqlalchemy.url"] = get_url()
    connectable = engine_from_config(cfg, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
