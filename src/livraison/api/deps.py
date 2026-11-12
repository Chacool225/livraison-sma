"""Dépendances FastAPI : utilisateur connecté et contrôle des rôles."""

import uuid

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from livraison.db.modeles import Role, StatutCompte, Utilisateur
from livraison.db.session import obtenir_session
from livraison.services import securite

_schema = HTTPBearer(auto_error=False)


async def utilisateur_courant(
    identifiants: HTTPAuthorizationCredentials | None = Depends(_schema),
    session: AsyncSession = Depends(obtenir_session),
) -> Utilisateur:
    if identifiants is None:
        raise HTTPException(
            401, "Authentification requise.", headers={"WWW-Authenticate": "Bearer"}
        )
    try:
        contenu = securite.lire_jeton(identifiants.credentials)
        utilisateur = await session.get(Utilisateur, uuid.UUID(contenu["sub"]))
    except (securite.JetonInvalide, ValueError):
        utilisateur = None
    if utilisateur is None:
        raise HTTPException(
            401, "Jeton invalide ou expiré.", headers={"WWW-Authenticate": "Bearer"}
        )
    if utilisateur.statut == StatutCompte.SUSPENDU:
        raise HTTPException(403, "Compte suspendu.")
    return utilisateur


def exiger_roles(*roles: Role):
    """Dépendance : l'utilisateur doit avoir l'un des rôles. Le rôle est relu en base
    (pas dans le jeton) : un changement de rôle ou une suspension agit tout de suite."""

    async def verifier(utilisateur: Utilisateur = Depends(utilisateur_courant)) -> Utilisateur:
        if utilisateur.role not in roles:
            raise HTTPException(403, "Droits insuffisants pour cette action.")
        return utilisateur

    return verifier


# Dépendances prêtes à l'emploi, à utiliser dans les routes : Depends(LIVREUR_SEUL), etc.
LIVREUR_SEUL = exiger_roles(Role.LIVREUR)
ADMIN_SEUL = exiger_roles(Role.ADMINISTRATEUR)
