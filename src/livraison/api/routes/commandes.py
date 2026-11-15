import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from livraison.agents.flotte import Flotte
from livraison.api.deps import (
    CLIENT_SEUL,
    SUPERVISEUR,
    flotte_facultative,
    obtenir_flotte,
    utilisateur_courant,
)
from livraison.api.schemas import (
    AgentEnLigne,
    CommandeCreee,
    CommandeDetail,
    CommandeResume,
    NouvelleCommande,
)
from livraison.db.modeles import EtatCommande, ModePaiement, Utilisateur
from livraison.db.session import obtenir_session
from livraison.services import livraisons

router = APIRouter(tags=["commandes"])


@router.post("/commandes", response_model=CommandeCreee, status_code=201)
async def creer_commande(
    donnees: NouvelleCommande,
    client: Utilisateur = Depends(CLIENT_SEUL),
    session: AsyncSession = Depends(obtenir_session),
    flotte: Flotte = Depends(obtenir_flotte),
):
    """Crée une commande : calcule le prix, la valide (espèces) et lance la recherche d'un livreur.
    Le `code_remise` est à donner au destinataire ; il n'est montré qu'ici."""
    commande, code = await livraisons.creer_commande(
        session,
        flotte,
        client,
        adresse_enlevement=donnees.enlevement.adresse,
        point_enlevement=(donnees.enlevement.longitude, donnees.enlevement.latitude),
        adresse_livraison=donnees.livraison.adresse,
        point_livraison=(donnees.livraison.longitude, donnees.livraison.latitude),
        taille=donnees.taille_colis,
        description=donnees.description_colis,
        consignes=donnees.consignes,
        destinataire_nom=donnees.destinataire_nom,
        destinataire_telephone=donnees.destinataire_telephone,
        mode_paiement=ModePaiement(donnees.mode_paiement),
    )
    await flotte.soumettre(commande.id)
    detail = await livraisons.detail_commande(session, flotte, commande)
    return {**detail, "code_remise": code}


@router.get("/commandes", response_model=list[CommandeResume])
async def mes_commandes(
    limite: int = Query(20, ge=1, le=100),
    decalage: int = Query(0, ge=0),
    client: Utilisateur = Depends(CLIENT_SEUL),
    session: AsyncSession = Depends(obtenir_session),
):
    return await livraisons.lister_commandes(
        session, client_id=client.id, limite=limite, decalage=decalage
    )


@router.get("/commandes/{commande_id}", response_model=CommandeDetail)
async def detail_commande(
    commande_id: uuid.UUID,
    utilisateur: Utilisateur = Depends(utilisateur_courant),
    session: AsyncSession = Depends(obtenir_session),
    flotte: Flotte | None = Depends(flotte_facultative),
):
    """État, prix, livreur et position du livreur. Le client voit les siennes ; la supervision, toutes."""
    commande = await livraisons.charger_commande_visible(session, commande_id, utilisateur)
    return await livraisons.detail_commande(session, flotte, commande)


@router.post("/commandes/{commande_id}/annulation", response_model=CommandeDetail)
async def annuler_commande(
    commande_id: uuid.UUID,
    utilisateur: Utilisateur = Depends(utilisateur_courant),
    session: AsyncSession = Depends(obtenir_session),
    flotte: Flotte = Depends(obtenir_flotte),
):
    """Possible tant que le colis n'est pas enlevé."""
    commande = await livraisons.annuler_commande(session, flotte, utilisateur, commande_id)
    return await livraisons.detail_commande(session, flotte, commande)


@router.get("/admin/commandes", response_model=list[CommandeResume])
async def toutes_les_commandes(
    etat: EtatCommande | None = None,
    limite: int = Query(50, ge=1, le=200),
    decalage: int = Query(0, ge=0),
    _: Utilisateur = Depends(SUPERVISEUR),
    session: AsyncSession = Depends(obtenir_session),
):
    return await livraisons.lister_commandes(session, etat=etat, limite=limite, decalage=decalage)


@router.get("/admin/agents", response_model=list[AgentEnLigne])
async def livreurs_en_ligne(
    _: Utilisateur = Depends(SUPERVISEUR), flotte: Flotte = Depends(obtenir_flotte)
):
    """Livreurs actuellement en ligne, d'après l'annuaire des agents."""
    return [
        {
            "livreur_id": a["livreur_id"],
            "longitude": a["position"][0],
            "latitude": a["position"][1],
            "age_position_s": a["age_position_s"],
            "vehicule": a["vehicule"],
        }
        for a in flotte.livreurs_en_ligne()
    ]
