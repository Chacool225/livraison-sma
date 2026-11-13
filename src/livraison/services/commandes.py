"""Opérations sur les commandes utilisées par le dispatcher : chaque fonction est une petite
transaction (elle valide elle-même) et respecte le cycle de vie du § 3.4."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from geoalchemy2 import Geometry
from sqlalchemy import cast, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from livraison.db.modeles import (
    Commande,
    EtatCommande,
    Evenement,
    Offre,
    Parametre,
    ResultatOffre,
    TailleColis,
)
from livraison.modele.etats import verifier_transition
from livraison.modele.geo import Point

DEFAUTS = {
    "penalite_charge": 3,
    "delai_confirmation_s": 30,
    "delai_offres_s": 3,
    "rayon_recherche_initial_m": 3000,
    "rayon_pas_elargissement_m": 2000,
    "tentatives_attribution_max": 3,
    "age_max_position_s": 60,
    "delai_relance_s": 5,
    "candidats_max": 20,
    "perte_signal_s": 120,
    "controle_gps_intervalle_s": 15,
}

_HORODATAGE_PAR_ETAT = {
    EtatCommande.ATTRIBUEE: "attribuee_le",
    EtatCommande.ENLEVEE: "enlevee_le",
    EtatCommande.LIVREE: "livree_le",
    EtatCommande.CLOTUREE: "cloturee_le",
    EtatCommande.ANNULEE: "annulee_le",
}


@dataclass
class CommandeAAttribuer:
    id: uuid.UUID
    etat: EtatCommande
    taille: TailleColis
    enlevement: Point
    livraison: Point


async def lire_reglages(session: AsyncSession, forces: dict | None = None) -> dict:
    """Réglages de la table `parametres` (modifiables par l'administrateur), complétés par des
    valeurs par défaut ; `forces` sert aux tests."""
    lignes = await session.execute(select(Parametre.cle, Parametre.valeur))
    reglages = {**DEFAUTS, **{cle: valeur for cle, valeur in lignes}}
    return {**reglages, **(forces or {})}


async def charger(session: AsyncSession, commande_id: uuid.UUID) -> CommandeAAttribuer | None:
    def coord(colonne, fonction):
        return fonction(cast(colonne, Geometry)).label

    ligne = (
        await session.execute(
            select(
                Commande.id,
                Commande.etat,
                Commande.taille_colis,
                func.ST_X(cast(Commande.point_enlevement, Geometry)).label("elon"),
                func.ST_Y(cast(Commande.point_enlevement, Geometry)).label("elat"),
                func.ST_X(cast(Commande.point_livraison, Geometry)).label("llon"),
                func.ST_Y(cast(Commande.point_livraison, Geometry)).label("llat"),
            ).where(Commande.id == commande_id)
        )
    ).first()
    if ligne is None:
        return None
    return CommandeAAttribuer(
        ligne.id, ligne.etat, ligne.taille_colis, (ligne.elon, ligne.elat), (ligne.llon, ligne.llat)
    )


async def journaliser(
    session: AsyncSession,
    commande_id: uuid.UUID | None,
    type_: str,
    auteur: str,
    detail: dict | None = None,
) -> None:
    session.add(Evenement(commande_id=commande_id, type=type_, auteur=auteur, detail=detail or {}))
    await session.commit()


async def changer_etat(
    session: AsyncSession,
    commande_id: uuid.UUID,
    nouvel_etat: EtatCommande,
    auteur: str,
    detail: dict | None = None,
    **champs,
) -> Commande:
    """Change l'état en vérifiant la transition, horodate, et écrit l'événement."""
    commande = await session.scalar(
        select(Commande).where(Commande.id == commande_id).with_for_update()
    )
    verifier_transition(commande.etat, nouvel_etat)
    commande.etat = nouvel_etat
    colonne_date = _HORODATAGE_PAR_ETAT.get(nouvel_etat)
    if colonne_date:
        setattr(commande, colonne_date, datetime.now(UTC))
    for nom, valeur in champs.items():
        setattr(commande, nom, valeur)
    session.add(
        Evenement(
            commande_id=commande_id,
            type=f"etat_{nouvel_etat.value}",
            auteur=auteur,
            detail=detail or {},
        )
    )
    await session.commit()
    return commande


async def marquer_en_recherche(session: AsyncSession, commande_id: uuid.UUID, auteur: str) -> None:
    commande = await session.get(Commande, commande_id)
    if commande.etat != EtatCommande.EN_RECHERCHE:
        await changer_etat(session, commande_id, EtatCommande.EN_RECHERCHE, auteur)


async def noter_rayon(
    session: AsyncSession, commande_id: uuid.UUID, rayon_m: int, tentative: int
) -> None:
    await session.execute(
        update(Commande)
        .where(Commande.id == commande_id)
        .values(rayon_recherche_m=rayon_m, tentatives_attribution=tentative)
    )
    await session.commit()


async def enregistrer_offres(
    session: AsyncSession,
    commande_id: uuid.UUID,
    tentative: int,
    offres: list[dict],
    refus: list[dict],
) -> None:
    for o in offres:
        session.add(
            Offre(
                commande_id=commande_id,
                livreur_id=uuid.UUID(o["livreur_id"]),
                tentative=tentative,
                cout=o["cout"],
                eta_s=round(o["eta_s"]),
                resultat=ResultatOffre.PROPOSEE,
            )
        )
    for r in refus:
        session.add(
            Offre(
                commande_id=commande_id,
                livreur_id=uuid.UUID(r["livreur_id"]),
                tentative=tentative,
                resultat=ResultatOffre.REFUSEE,
                motif=r.get("raison"),
            )
        )
    await session.commit()


async def resoudre_offre(
    session: AsyncSession,
    commande_id: uuid.UUID,
    livreur_id: str,
    tentative: int,
    resultat: ResultatOffre,
    motif: str | None = None,
) -> None:
    await session.execute(
        update(Offre)
        .where(
            Offre.commande_id == commande_id,
            Offre.livreur_id == uuid.UUID(livreur_id),
            Offre.tentative == tentative,
        )
        .values(resultat=resultat, motif=motif)
    )
    await session.commit()


async def attribuer_a(
    session: AsyncSession, commande_id: uuid.UUID, livreur_id: str, tentative: int, auteur: str
) -> None:
    await changer_etat(
        session,
        commande_id,
        EtatCommande.ATTRIBUEE,
        auteur,
        {"livreur_id": livreur_id, "tentative": tentative},
        livreur_id=uuid.UUID(livreur_id),
    )
    await resoudre_offre(session, commande_id, livreur_id, tentative, ResultatOffre.RETENUE)


async def liberer(
    session: AsyncSession, commande_id: uuid.UUID, livreur_id: str, motif: str, auteur: str
) -> None:
    """Incident avant l'enlèvement : la commande retourne en recherche (réattribution)."""
    await changer_etat(
        session,
        commande_id,
        EtatCommande.EN_RECHERCHE,
        auteur,
        {"livreur_id": livreur_id, "motif": motif},
        livreur_id=None,
        attribuee_le=None,
    )
    await journaliser(
        session,
        commande_id,
        "reattribution",
        auteur,
        {"livreur_precedent": livreur_id, "motif": motif},
    )


async def derniere_tentative(session: AsyncSession, commande_id: uuid.UUID) -> int:
    """Plus grand numéro de tour déjà utilisé pour cette commande (0 si aucun). Une réattribution
    continue la numérotation au lieu de repartir de 1."""
    return await session.scalar(
        select(func.coalesce(func.max(Offre.tentative), 0)).where(Offre.commande_id == commande_id)
    )


async def courses_actives(session: AsyncSession) -> list[tuple[uuid.UUID, EtatCommande, uuid.UUID]]:
    """(commande, état, livreur) de toutes les courses confiées à un livreur et pas encore livrées."""
    lignes = await session.execute(
        select(Commande.id, Commande.etat, Commande.livreur_id).where(
            Commande.etat.in_(
                [EtatCommande.ATTRIBUEE, EtatCommande.ENLEVEE, EtatCommande.EN_LIVRAISON]
            ),
            Commande.livreur_id.is_not(None),
        )
    )
    return [tuple(ligne) for ligne in lignes]
