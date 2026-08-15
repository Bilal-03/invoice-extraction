from logging.config import fileConfig

from alembic import context
import sqlalchemy as sa
from sqlalchemy import engine_from_config, pool
from sqlalchemy.dialects.postgresql import JSONB

from app.core.config import get_settings
from app.core.database import Base
import app.domain.entities  # noqa: F401

config = context.config
database_url = get_settings().database_url.replace("+asyncpg", "+psycopg")
if ("supabase.co" in database_url or "supabase.com" in database_url) and "sslmode=" not in database_url:
    database_url = f"{database_url}?sslmode=require"
# ConfigParser treats percent signs as interpolation markers; database passwords
# are URL-encoded and therefore commonly contain them.
config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
if config.config_file_name:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def include_object(object_, name, type_, reflected, compare_to):
    """Keep legacy migration index names stable during autogenerate checks.

    The initial migrations use explicit composite/index names while a few ORM
    fields use SQLAlchemy's automatic ``ix_*`` names. Indexes are maintained by
    explicit migrations, so autogenerate should focus on table/column changes.
    """

    return type_ != "index"


def compare_type(context_, inspected_column, metadata_column, inspected_type, metadata_type):
    """Treat Supabase JSONB and SQLAlchemy's portable JSON as equivalent."""

    if isinstance(inspected_type, JSONB) and isinstance(metadata_type, sa.JSON):
        return False
    return None


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        include_object=include_object,
        compare_type=compare_type,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
            compare_type=compare_type,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
