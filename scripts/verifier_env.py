"""Vérifie que l'environnement de développement est complet.
Lancement depuis la racine du projet : python scripts/verifier_env.py
"""

import asyncio
import importlib
import socket
import sys

RESULTATS: list[tuple[str, bool, str]] = []


def noter(nom: str, ok: bool, detail: str = "") -> None:
    RESULTATS.append((nom, ok, detail))


def verifier_python() -> None:
    v = sys.version_info
    noter("Python >= 3.11", v >= (3, 11), f"{v.major}.{v.minor}.{v.micro}")


def verifier_bibliotheques() -> None:
    for module in (
        "spade",
        "fastapi",
        "flet",
        "sqlalchemy",
        "asyncpg",
        "redis",
        "ortools",
        "httpx",
    ):
        try:
            m = importlib.import_module(module)
            noter(f"Bibliothèque {module}", True, getattr(m, "__version__", ""))
        except Exception as e:  # noqa: BLE001
            noter(f"Bibliothèque {module}", False, str(e))


async def verifier_postgres(p) -> None:
    try:
        import asyncpg

        cx = await asyncio.wait_for(asyncpg.connect(p.postgres_dsn), timeout=5)
        try:
            await cx.execute("CREATE EXTENSION IF NOT EXISTS postgis")
            version = await cx.fetchval("SELECT postgis_version()")
        finally:
            await cx.close()
        noter("PostgreSQL + PostGIS", True, f"PostGIS {version.split()[0]}")
    except Exception as e:  # noqa: BLE001
        noter("PostgreSQL + PostGIS", False, f"{type(e).__name__}: {e}")


async def verifier_redis(p) -> None:
    try:
        import redis.asyncio as redis

        r = redis.from_url(p.redis_url, socket_connect_timeout=5)
        try:
            await r.ping()
        finally:
            await r.aclose()
        noter("Redis", True)
    except Exception as e:  # noqa: BLE001
        noter("Redis", False, f"{type(e).__name__}: {e}")


def verifier_xmpp(p) -> None:
    try:
        with socket.create_connection((p.xmpp_host, p.xmpp_port), timeout=3):
            noter("Serveur XMPP", True, f"{p.xmpp_host}:{p.xmpp_port}")
    except OSError:
        noter("Serveur XMPP", False, "injoignable : lancez « spade run » dans un autre terminal")


async def verifier_osrm(p) -> None:
    try:
        import httpx

        # Deux points d'Abidjan (longitude,latitude) : Plateau -> Cocody
        url = f"{p.osrm_url}/route/v1/driving/-4.0197,5.3236;-3.9870,5.3480?overview=false"
        async with httpx.AsyncClient(timeout=5) as client:
            route = (await client.get(url)).json()["routes"][0]
        noter(
            "Moteur d'itinéraires",
            True,
            f"{route['distance'] / 1000:.1f} km, {route['duration'] / 60:.0f} min",
        )
    except Exception as e:  # noqa: BLE001
        noter(
            "Moteur d'itinéraires (optionnel)",
            False,
            f"{type(e).__name__} : voir l'étape 7 du README",
        )


async def main() -> int:
    verifier_python()
    verifier_bibliotheques()
    try:
        from livraison.config import parametres as p
    except Exception as e:  # noqa: BLE001
        noter("Paquet livraison", False, f"{e} : lancez « pip install -e . »")
        p = None
    if p:
        await verifier_postgres(p)
        await verifier_redis(p)
        verifier_xmpp(p)
        await verifier_osrm(p)

    echecs = 0
    for nom, ok, detail in RESULTATS:
        optionnel = "optionnel" in nom
        if not ok and not optionnel:
            echecs += 1
        print(
            f"[{'OK' if ok else ('--' if optionnel else 'KO')}] {nom}"
            + (f" ({detail})" if detail else "")
        )
    print("\nEnvironnement prêt." if echecs == 0 else f"\n{echecs} point(s) à corriger.")
    return 1 if echecs else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
