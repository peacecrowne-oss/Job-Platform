from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# `prepend_sys_path = .` in alembic.ini adds the current working directory to
# sys.path — these imports rely on Alembic always being invoked with cwd set
# to backend/ (e.g. `cd backend && alembic ...`, or `docker compose exec
# backend alembic ...`, whose WORKDIR is the container equivalent of backend/).
from app.config import get_settings
from app.db import Base

# Importing model modules registers their classes onto Base.metadata as a
# side effect — without this import, target_metadata below would be empty
# regardless of what models exist, since nothing would have loaded them.
import app.models.job  # noqa: F401  (STORY-010)
import app.models.company  # noqa: F401  (STORY-011)
import app.models.source  # noqa: F401  (STORY-014)
import app.models.ingestion_run  # noqa: F401  (STORY-015)

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# No credentials live in alembic.ini (STORY-006/STORY-009) — the real URL
# comes from the same Settings object the rest of the backend already uses.
config.set_main_option("sqlalchemy.url", get_settings().database_url)

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
