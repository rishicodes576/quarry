import os

from alembic import context
from sqlalchemy import create_engine

from quarry.config import settings
from quarry.db import Base

config = context.config
DATABASE_URL = os.environ.get("QUARRY_MIGRATION_DATABASE_URL") or settings().database_url
EXTERNAL_TABLES = {"checkpoints", "checkpoint_blobs", "checkpoint_writes", "checkpoint_migrations"}


def include_object(obj, name, kind, reflected, compare_to):
    return not (kind == "table" and name in EXTERNAL_TABLES)


if context.is_offline_mode():
    context.configure(url=DATABASE_URL, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    with create_engine(DATABASE_URL).connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=Base.metadata,
            compare_type=True,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()
