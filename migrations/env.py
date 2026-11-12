"""Environnement Alembic (asynchrone). L'URL vient du fichier .env, sauf si elle est imposée
par le code appelant (les tests passent `sqlalchemy.url`)."""

import asyncio
from logging.config import fileConfig

import geoalchemy2  # noqa: F401  (enregistre le type Geography pour la comparaison)
from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

from livraison.config import parametres
from livraison.db import modeles  # noqa: F401  (déclare toutes les tables)
from livraison.db.base import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _url() -> str:
    return config.get_main_option("sqlalchemy.url") or parametres.postgres_dsn_async


def include_object(objet, nom, type_, reflected, compare_to):
    # Table interne de PostGIS : ne jamais la gérer.
    return not (type_ == "table" and nom == "spatial_ref_sys")


def _configurer(**options):
    context.configure(
        target_metadata=target_metadata,
        include_object=include_object,
        compare_type=True,
        **options,
    )


def run_migrations_offline() -> None:
    _configurer(url=_url(), literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def _executer(connexion) -> None:
    _configurer(connection=connexion)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    moteur = create_async_engine(_url(), poolclass=pool.NullPool)
    async with moteur.connect() as connexion:
        await connexion.run_sync(_executer)
    await moteur.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
