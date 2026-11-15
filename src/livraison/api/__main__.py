"""Lance l'API : python -m livraison.api   (ou : python -m livraison.api --reload)

Sous Windows, la bibliothèque XMPP des agents est testée avec la boucle d'événements « Selector » ;
ce lanceur l'impose, quelles que soient les options d'uvicorn.
"""

import argparse
import asyncio
import sys

import uvicorn

from livraison.config import parametres


def main() -> None:
    analyseur = argparse.ArgumentParser(description="Lance l'API Livraison SMA")
    analyseur.add_argument(
        "--reload", action="store_true", help="redémarre à chaque modification du code"
    )
    args = analyseur.parse_args()
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    uvicorn.run(
        "livraison.api.main:app",
        host=parametres.api_host,
        port=parametres.api_port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
