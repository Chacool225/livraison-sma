"""Dépendances FastAPI : utilisateur connecté et contrôle des rôles."""

import uuid

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from livraison.agents.flotte import Flotte
from livraison.db.modeles import Livreur, Role, StatutCompte, StatutValidation, Utilisateur
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
CLIENT_SEUL = exiger_roles(Role.CLIENT)
SUPERVISEUR = exiger_roles(Role.ADMINISTRATEUR, Role.REPARTITEUR)


def flotte_facultative(request: Request) -> Flotte | None:
    """Pour les lectures, qui restent possibles même si les agents sont arrêtés."""
    return getattr(request.app.state, "flotte", None)


def obtenir_flotte(request: Request) -> Flotte:
    """Les agents (attribution des courses). Absents si le serveur XMPP n'était pas joignable."""
    flotte = getattr(request.app.state, "flotte", None)
    if flotte is None:
        raise HTTPException(503, "Le service d'attribution des courses est indisponible.")
    return flotte


async def livreur_valide(
    utilisateur: Utilisateur = Depends(LIVREUR_SEUL),
    session: AsyncSession = Depends(obtenir_session),
) -> Livreur:
    """Un livreur ne travaille qu'une fois son dossier validé par l'administrateur."""
    livreur = await session.get(Livreur, utilisateur.id)
    if livreur is None or livreur.statut_validation != StatutValidation.VALIDE:
        raise HTTPException(403, "Votre dossier de livreur doit d'abord être validé.")
    return livreur
