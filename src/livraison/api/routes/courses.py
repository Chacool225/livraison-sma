import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from livraison.agents.flotte import CourseEnCours, Flotte, LivreurHorsLigne
from livraison.api.deps import livreur_valide, obtenir_flotte
from livraison.api.schemas import EtapeIn, MesCourses, PositionIn, ReponseProposition
from livraison.db.modeles import Livreur
from livraison.db.session import obtenir_session
from livraison.services import livraisons

router = APIRouter(prefix="/livreurs/moi", tags=["courses du livreur"])


@router.post("/en-ligne")
async def passer_en_ligne(
    position: PositionIn,
    livreur: Livreur = Depends(livreur_valide),
    flotte: Flotte = Depends(obtenir_flotte),
):
    """Le livreur se met à disposition : son agent est créé et inscrit à l'annuaire."""
    await flotte.mettre_en_ligne(livreur, (position.longitude, position.latitude))
    return {"en_ligne": True}


@router.post("/hors-ligne")
async def passer_hors_ligne(
    livreur: Livreur = Depends(livreur_valide), flotte: Flotte = Depends(obtenir_flotte)
):
    """Impossible tant que le livreur a une course ou une proposition en cours."""
    try:
        await flotte.mettre_hors_ligne(livreur.utilisateur_id)
    except CourseEnCours as erreur:
        raise HTTPException(
            409, "Terminez vos courses en cours avant de vous déconnecter."
        ) from erreur
    return {"en_ligne": False}


@router.put("/position")
async def envoyer_position(
    position: PositionIn,
    livreur: Livreur = Depends(livreur_valide),
    flotte: Flotte = Depends(obtenir_flotte),
):
    """À envoyer régulièrement (au moins toutes les 30 s environ) : sans position récente, la course
    en cours peut être réattribuée."""
    try:
        await flotte.enregistrer_position(
            livreur.utilisateur_id, (position.longitude, position.latitude), position.precision_m
        )
    except LivreurHorsLigne as erreur:
        raise HTTPException(409, "Vous êtes hors ligne : passez en ligne d'abord.") from erreur
    return {"enregistree": True}


@router.get("/courses", response_model=MesCourses)
async def mes_courses(
    livreur: Livreur = Depends(livreur_valide),
    session: AsyncSession = Depends(obtenir_session),
    flotte: Flotte = Depends(obtenir_flotte),
):
    """Propositions à confirmer (durée limitée) et courses en cours."""
    return await livraisons.mes_courses(session, flotte, livreur.utilisateur_id)


@router.post("/courses/{commande_id}/reponse")
async def repondre_a_une_proposition(
    commande_id: uuid.UUID,
    reponse: ReponseProposition,
    livreur: Livreur = Depends(livreur_valide),
    flotte: Flotte = Depends(obtenir_flotte),
):
    """Accepter ou décliner une proposition, avant la fin de son délai."""
    if not flotte.repondre(livreur.utilisateur_id, str(commande_id), reponse.accepte):
        raise HTTPException(404, "Proposition introuvable ou expirée.")
    return {"enregistree": True, "accepte": reponse.accepte}


@router.post("/courses/{commande_id}/etape", status_code=202)
async def signaler_une_etape(
    commande_id: uuid.UUID,
    etape: EtapeIn,
    livreur: Livreur = Depends(livreur_valide),
    session: AsyncSession = Depends(obtenir_session),
    flotte: Flotte = Depends(obtenir_flotte),
):
    """Annonce l'enlèvement, le départ en livraison, la livraison (avec le code de remise du
    destinataire) ou un échec. L'état de la commande se met à jour juste après (réponse 202)."""
    await livraisons.signaler_etape(
        session, flotte, livreur.utilisateur_id, commande_id, etape.etape, etape.code, etape.motif
    )
    return {"annonce": etape.etape}
