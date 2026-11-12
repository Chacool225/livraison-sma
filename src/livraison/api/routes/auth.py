from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from livraison.api.deps import utilisateur_courant
from livraison.api.schemas import (
    DemandeCode,
    Jeton,
    ReponseDemandeCode,
    UtilisateurSortie,
    VerificationCode,
)
from livraison.config import parametres
from livraison.db.modeles import Role, Utilisateur
from livraison.db.session import obtenir_session
from livraison.services import comptes

router = APIRouter(tags=["authentification"])


@router.post("/auth/demander-code", response_model=ReponseDemandeCode)
async def demander_code(demande: DemandeCode, session: AsyncSession = Depends(obtenir_session)):
    """Envoie un code à 6 chiffres par SMS (valable quelques minutes)."""
    code = await comptes.demander_code(session, demande.telephone)
    en_dev = parametres.environnement == "dev"
    return ReponseDemandeCode(message="Code envoyé par SMS.", code_dev=code if en_dev else None)


@router.post("/auth/verifier-code", response_model=Jeton)
async def verifier_code(
    verification: VerificationCode, session: AsyncSession = Depends(obtenir_session)
):
    """Vérifie le code. Crée le compte à la première connexion. Renvoie un jeton JWT."""
    utilisateur, jeton = await comptes.verifier_code(
        session,
        verification.telephone,
        verification.code,
        Role(verification.role),
        verification.nom,
    )
    return Jeton(access_token=jeton, utilisateur=UtilisateurSortie.model_validate(utilisateur))


@router.get("/moi", response_model=UtilisateurSortie)
async def moi(utilisateur: Utilisateur = Depends(utilisateur_courant)):
    return utilisateur
