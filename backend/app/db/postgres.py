from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings


def _build_engine() -> AsyncEngine:
    # Neon URLs often include libpq-style params like sslmode/channel_binding.
    # asyncpg doesn't accept sslmode directly, so convert to asyncpg-friendly args.
    url = make_url(settings.postgres_dsn)
    connect_args: dict = {}

    query = dict(url.query)
    sslmode = query.pop("sslmode", None)
    query.pop("channel_binding", None)

    if sslmode:
        # For asyncpg, ssl should be a bool or SSLContext; True is enough for Neon TLS.
        connect_args["ssl"] = True

    normalized_url = url.set(query=query).render_as_string(hide_password=False)
    return create_async_engine(
        normalized_url,
        future=True,
        pool_pre_ping=True,
        connect_args=connect_args,
    )


engine: AsyncEngine = _build_engine()
async_session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncSession:
    async with async_session_factory() as session:
        yield session

