"""Connexion asynchrone à PostgreSQL et fournisseur de sessions pour FastAPI."""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from livraison.config import parametres

_moteur: AsyncEngine | None = None
_fabrique: async_sessionmaker[AsyncSession] | None = None


def creer_moteur(url: str | None = None) -> AsyncEngine:
    return create_async_engine(url or parametres.postgres_dsn_async, pool_pre_ping=True)


def fabrique_sessions() -> async_sessionmaker[AsyncSession]:
    """Moteur et fabrique créés à la première utilisation, puis réutilisés."""
    global _moteur, _fabrique
    if _fabrique is None:
        _moteur = creer_moteur()
        _fabrique = async_sessionmaker(_moteur, expire_on_commit=False)
    return _fabrique


async def obtenir_session() -> AsyncIterator[AsyncSession]:
    """Dépendance FastAPI : une session par requête. Les services valident (commit) eux-mêmes."""
    async with fabrique_sessions()() as session:
        yield session
