"""Lance l'application : python -m livraison.interfaces [--web] [--url http://127.0.0.1:8000]

L'API (et le serveur XMPP) doivent déjà tourner. Par défaut, une fenêtre s'ouvre ; avec --web,
l'application est servie à un navigateur (utile pour l'essayer sur un téléphone du même réseau :
--web --hote 0.0.0.0, puis http://<adresse du PC>:8550).
"""

import argparse

import flet as ft

from livraison.config import parametres
from livraison.interfaces.application import creer_application


def main() -> None:
    analyseur = argparse.ArgumentParser(description="Application Livraison SMA")
    analyseur.add_argument(
        "--url",
        default=f"http://{parametres.api_host}:{parametres.api_port}",
        help="adresse de l'API",
    )
    analyseur.add_argument(
        "--web", action="store_true", help="servir l'application à un navigateur"
    )
    analyseur.add_argument("--hote", default="127.0.0.1", help="adresse d'écoute en mode --web")
    analyseur.add_argument("--port", type=int, default=8550, help="port en mode --web")
    args = analyseur.parse_args()
    principal = creer_application(args.url)
    if args.web:
        ft.run(principal, view=ft.AppView.WEB_BROWSER, host=args.hote, port=args.port)
    else:
        ft.run(principal)


if __name__ == "__main__":
    main()
