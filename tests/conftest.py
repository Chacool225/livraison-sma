"""Fixtures communes. Les tests de base de données utilisent une base dédiée « livraison_test »
(recréée à chaque session de tests, jamais la vraie base) et exigent PostgreSQL/PostGIS :
sans lui, ils sont ignorés (docker compose up -d)."""

import asyncio
import socket
from pathlib import Path

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from livraison.api.main import app
from livraison.config import parametres
from livraison.db.session import obtenir_session

RACINE = Path(__file__).resolve().parent.parent
BASE_TEST = "livraison_test"


def _postgres_actif() -> bool:
    try:
        with socket.create_connection(
            (parametres.postgres_host, parametres.postgres_port), timeout=1
        ):
            return True
    except OSError:
        return False


async def _recreer_base_de_test() -> None:
    connexion = await asyncpg.connect(
        host=parametres.postgres_host,
        port=parametres.postgres_port,
        user=parametres.postgres_user,
        password=parametres.postgres_password,
        database="postgres",
    )
    try:
        await connexion.execute(f"DROP DATABASE IF EXISTS {BASE_TEST} WITH (FORCE)")
        await connexion.execute(f"CREATE DATABASE {BASE_TEST}")
    finally:
        await connexion.close()


@pytest.fixture(scope="session")
def url_base_test() -> str:
    if not _postgres_actif():
        pytest.skip("PostgreSQL absent (lancer : docker compose up -d)")
    asyncio.run(_recreer_base_de_test())
    url = (
        f"postgresql+asyncpg://{parametres.postgres_user}:{parametres.postgres_password}"
        f"@{parametres.postgres_host}:{parametres.postgres_port}/{BASE_TEST}"
    )
    config = Config(str(RACINE / "alembic.ini"))
    config.set_main_option("script_location", str(RACINE / "migrations"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")  # teste aussi la migration
    return url


@pytest.fixture
async def moteur(url_base_test):
    moteur = create_async_engine(url_base_test, poolclass=NullPool)
    async with moteur.begin() as connexion:
        # DELETE (et non TRUNCATE ... CASCADE) : on garde les réglages de départ de la migration.
        await connexion.execute(text("UPDATE parametres SET modifie_par = NULL"))
        for table in (
            "evenements",
            "factures",
            "paiements",
            "offres",
            "commandes",
            "positions",
            "livreurs",
            "codes_verification",
            "utilisateurs",
        ):
            await connexion.execute(text(f"DELETE FROM {table}"))
    yield moteur
    await moteur.dispose()


@pytest.fixture
async def session(moteur):
    async with async_sessionmaker(moteur, expire_on_commit=False)() as session:
        yield session


@pytest.fixture
async def client(moteur, monkeypatch):
    monkeypatch.setattr(parametres, "environnement", "dev")  # l'API renvoie alors le code SMS
    fabrique = async_sessionmaker(moteur, expire_on_commit=False)

    async def session_de_test():
        async with fabrique() as session:
            yield session

    app.dependency_overrides[obtenir_session] = session_de_test
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


def _xmpp_actif() -> bool:
    try:
        with socket.create_connection((parametres.xmpp_host, parametres.xmpp_port), timeout=1):
            return True
    except OSError:
        return False


@pytest.fixture
def xmpp():
    if not _xmpp_actif():
        pytest.skip("serveur XMPP absent (lancer : spade run --memory)")
