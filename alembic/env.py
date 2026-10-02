from alembic import context
from app import models  # noqa: F401
from app.db import Base, get_engine

if context.is_offline_mode():
    from app.config import get_settings

    context.configure(
        url=get_settings().database_url, target_metadata=Base.metadata, literal_binds=True
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    with get_engine().connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
