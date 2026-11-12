"""Crée (ou promeut) un compte administrateur. Les rôles répartiteur et administrateur ne
peuvent pas être obtenus par l'inscription : ils se donnent depuis ce script.

Usage : python scripts/creer_admin.py +2250700000000 "Nom Prénom"
        python scripts/creer_admin.py +2250700000000 --role repartiteur
"""

import argparse
import asyncio

from sqlalchemy import select

from livraison.db.modeles import Role, Utilisateur
from livraison.db.session import fabrique_sessions
from livraison.services.securite import normaliser_telephone


async def main(telephone: str, nom: str | None, role: Role) -> None:
    telephone = normaliser_telephone(telephone)
    async with fabrique_sessions()() as session:
        utilisateur = await session.scalar(
            select(Utilisateur).where(Utilisateur.telephone == telephone)
        )
        if utilisateur is None:
            utilisateur = Utilisateur(telephone=telephone, nom=nom, role=role)
            session.add(utilisateur)
            action = "créé"
        else:
            utilisateur.role = role
            if nom:
                utilisateur.nom = nom
            action = "mis à jour"
        await session.commit()
    print(f"Compte {action} : {telephone} -> {role.value}")


if __name__ == "__main__":
    analyseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    analyseur.add_argument("telephone")
    analyseur.add_argument("nom", nargs="?")
    analyseur.add_argument(
        "--role",
        choices=[Role.ADMINISTRATEUR.value, Role.REPARTITEUR.value],
        default="administrateur",
    )
    args = analyseur.parse_args()
    asyncio.run(main(args.telephone, args.nom, Role(args.role)))
