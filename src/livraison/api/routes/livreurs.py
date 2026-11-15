import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from livraison.api.deps import ADMIN_SEUL, LIVREUR_SEUL
from livraison.api.schemas import (
    DecisionValidation,
    DossierAValider,
    DossierLivreur,
    DossierLivreurSortie,
)
from livraison.db.modeles import Livreur, StatutValidation, Utilisateur
from livraison.db.session import obtenir_session
from livraison.services import comptes

router = APIRouter(tags=["livreurs"])


@router.put("/livreurs/moi/dossier", response_model=DossierLivreurSortie)
async def deposer_dossier(
    dossier: DossierLivreur,
    utilisateur: Utilisateur = Depends(LIVREUR_SEUL),
    session: AsyncSession = Depends(obtenir_session),
):
    """Dépose ou modifie son dossier (véhicule, capacité, pièces). Repasse en attente de validation."""
    donnees = dossier.model_dump()
    return await comptes.enregistrer_dossier_livreur(session, utilisateur, donnees)


@router.get("/livreurs/moi/dossier", response_model=DossierLivreurSortie)
async def mon_dossier(
    utilisateur: Utilisateur = Depends(LIVREUR_SEUL),
    session: AsyncSession = Depends(obtenir_session),
):
    livreur = await session.get(Livreur, utilisateur.id)
    if livreur is None:
        raise HTTPException(404, "Aucun dossier déposé.")
    return livreur


@router.get("/admin/livreurs", response_model=list[DossierAValider])
async def lister_dossiers(
    statut: StatutValidation = Query(StatutValidation.EN_ATTENTE),
    _: Utilisateur = Depends(ADMIN_SEUL),
    session: AsyncSession = Depends(obtenir_session),
):
    lignes = await session.execute(
        select(Livreur, Utilisateur)
        .join(Utilisateur, Utilisateur.id == Livreur.utilisateur_id)
        .where(Livreur.statut_validation == statut)
        .order_by(Livreur.cree_le)
    )
    return [
        {
            **DossierLivreurSortie.model_validate(livreur).model_dump(),
            "nom": compte.nom,
            "telephone": compte.telephone,
        }
        for livreur, compte in lignes
    ]


@router.post("/admin/livreurs/{livreur_id}/validation", response_model=DossierLivreurSortie)
async def valider_dossier(
    livreur_id: uuid.UUID,
    decision: DecisionValidation,
    administrateur: Utilisateur = Depends(ADMIN_SEUL),
    session: AsyncSession = Depends(obtenir_session),
):
    return await comptes.decider_validation(session, administrateur, livreur_id, decision.decision)
