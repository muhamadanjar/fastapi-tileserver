from logging.config import fileConfig
import os
import re

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context
from sqlmodel import SQLModel
from app.domain.models import UploadSession, Layer
from app.core.config import settings

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Override sqlalchemy.url from .env instead of using hardcoded ini value
config.set_main_option("sqlalchemy.url", settings.database.get_database_url(sync=True))

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = SQLModel.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.

def get_next_revision_id() -> str:
    """Generate next sequential revision ID based on existing migrations."""
    versions_dir = os.path.join(os.path.dirname(__file__), "versions")
    if not os.path.exists(versions_dir):
        return "0001"

    # Find all migration files with numeric prefix
    migration_files = [f for f in os.listdir(versions_dir) if f.endswith(".py") and not f.startswith("__")]

    if not migration_files:
        return "0001"

    # Extract numeric prefix from filenames
    numbers = []
    for f in migration_files:
        match = re.match(r"^(\d+)", f)
        if match:
            numbers.append(int(match.group(1)))

    if not numbers:
        return "0001"

    # Get next number with leading zeros
    next_num = max(numbers) + 1
    return f"{next_num:04d}"

def process_revision_directives(context, revision, directives):
    """Assign sequential revision IDs to new migrations."""
    if directives:
        for directive in directives:
            if directive.upgrade_ops.is_empty():
                return
            directive.revision = get_next_revision_id()
            directive.branch_labels = None


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
        process_revision_directives=process_revision_directives,
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
            connection=connection,
            target_metadata=target_metadata,
            process_revision_directives=process_revision_directives,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
