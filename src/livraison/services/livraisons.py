"""Règles métier des commandes (côté client) et des courses (côté livreur)."""

import time
import uuid

from geoalchemy2.elements import WKTElement
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from livraison.agents.flotte import Flotte, LivreurHorsLigne
from livraison.db.modeles import (
    Commande,
    EtatCommande,
    Evenement,
    Livreur,
    ModePaiement,
    Priorite,
    Role,
    TailleColis,
    Utilisateur,
)
from livraison.modele.etats import TransitionInterdite
from livraison.modele.geo import Point
from livraison.modele.tarif import calculer_prix
from livraison.services import commandes, securite
from livraison.services.comptes import ErreurMetier

DISTANCE_MIN_M = 50  # en dessous, enlèvement et livraison sont au même endroit
CODES_ERRONES_MAX = 5
ETAT_ACTIFS = (EtatCommande.ATTRIBUEE, EtatCommande.ENLEVEE, EtatCommande.EN_LIVRAISON)
ETATS_AVEC_LIVREUR = (
    *ETAT_ACTIFS,
    EtatCommande.LIVREE,
    EtatCommande.CLOTUREE,
    EtatCommande.ECHEC_LIVRAISON,
)

# Étape annoncée par le livreur -> états de commande dans lesquels elle est possible.
ETAPES_POSSIBLES = {
    "enlevee": {EtatCommande.ATTRIBUEE},
    "en_livraison": {EtatCommande.ENLEVEE},
    "livree": {EtatCommande.ENLEVEE, EtatCommande.EN_LIVRAISON},
    "echec": set(ETAT_ACTIFS),
}


def _wkt(point: Point) -> WKTElement:
    return WKTElement(f"POINT({point[0]} {point[1]})", srid=4326)


# --------------------------------------------------------------------------- côté client
async def estimer(
    session: AsyncSession, flotte: Flotte, point_enlevement: Point, point_livraison: Point
) -> tuple[float, float, int]:
    """(durée en s, distance en m, prix en F) d'une course, sans rien enregistrer."""
    duree, distance = await flotte.itineraire.trajet(point_enlevement, point_livraison, "moto")
    if distance < DISTANCE_MIN_M:
        raise ErreurMetier(422, "L'enlèvement et la livraison sont au même endroit.")
    reglages = await commandes.lire_reglages(session, flotte.dispatcher.reglages_forces)
    prix = calculer_prix(distance, reglages["tarif_fixe_xof"], reglages["tarif_km_xof"])
    return duree, distance, prix


async def creer_commande(
    session: AsyncSession,
    flotte: Flotte,
    client: Utilisateur,
    *,
    adresse_enlevement: str,
    point_enlevement: Point,
    adresse_livraison: str,
    point_livraison: Point,
    taille: TailleColis,
    description: str | None,
    consignes: str | None,
    destinataire_nom: str | None,
    destinataire_telephone: str | None,
    mode_paiement: ModePaiement,
) -> tuple[Commande, str]:
    """Calcule le prix, enregistre la commande, la valide (paiement en espèces : validée d'office).
    Renvoie la commande et son code de remise, à donner au destinataire (affiché une seule fois)."""
    if destinataire_telephone:
        try:
            destinataire_telephone = securite.normaliser_telephone(destinataire_telephone)
        except ValueError as erreur:
            raise ErreurMetier(422, f"Téléphone du destinataire : {erreur}") from erreur

    duree, distance, prix = await estimer(session, flotte, point_enlevement, point_livraison)

    commande = Commande(
        client_id=client.id,
        adresse_enlevement=adresse_enlevement,
        point_enlevement=_wkt(point_enlevement),
        adresse_livraison=adresse_livraison,
        point_livraison=_wkt(point_livraison),
        destinataire_nom=destinataire_nom,
        destinataire_telephone=destinataire_telephone,
        taille_colis=taille,
        description_colis=description,
        consignes=consignes,
        priorite=Priorite.NORMALE,
        prix=prix,
        distance_m=round(distance),
        duree_estimee_s=round(duree),
        mode_paiement=mode_paiement,
        etat=EtatCommande.CREEE,
    )
    session.add(commande)
    await session.flush()
    code = securite.generer_code_remise()
    commande.code_remise_hash = securite.hacher_code(str(commande.id), code)
    await session.commit()
    commande = await commandes.changer_etat(
        session,
        commande.id,
        EtatCommande.VALIDEE,
        f"client:{client.id}",
        {"paiement": mode_paiement.value},
    )
    return commande, code


async def charger_commande_visible(
    session: AsyncSession, commande_id: uuid.UUID, utilisateur: Utilisateur
) -> Commande:
    """Le client voit ses commandes ; l'administrateur et le répartiteur les voient toutes.
    Une commande d'autrui est présentée comme introuvable (on ne révèle pas son existence)."""
    commande = await session.get(Commande, commande_id)
    superviseur = utilisateur.role in (Role.ADMINISTRATEUR, Role.REPARTITEUR)
    if commande is None or not (superviseur or commande.client_id == utilisateur.id):
        raise ErreurMetier(404, "Commande introuvable.")
    return commande


async def detail_commande(session: AsyncSession, flotte: Flotte | None, commande: Commande) -> dict:
    coordonnees = await commandes.charger(session, commande.id)
    livreur = None
    if commande.livreur_id is not None and commande.etat in ETATS_AVEC_LIVREUR:
        compte = await session.get(Utilisateur, commande.livreur_id)
        dossier = await session.get(Livreur, commande.livreur_id)
        position = None
        entree = flotte.annuaire.entrees.get(str(commande.livreur_id)) if flotte else None
        if entree is not None and commande.etat in ETAT_ACTIFS:
            position = {
                "longitude": entree.position[0],
                "latitude": entree.position[1],
                "age_s": flotte.annuaire.age_position_s(str(commande.livreur_id)),
            }
        livreur = {
            "nom": compte.nom,
            "telephone": compte.telephone,
            "type_vehicule": dossier.type_vehicule,
            "note": float(dossier.note) if dossier.note is not None else None,
            "position": position,
        }
    return {
        "id": commande.id,
        "numero": commande.numero,
        "etat": commande.etat,
        "enlevement": {
            "adresse": commande.adresse_enlevement,
            "longitude": coordonnees.enlevement[0],
            "latitude": coordonnees.enlevement[1],
        },
        "livraison": {
            "adresse": commande.adresse_livraison,
            "longitude": coordonnees.livraison[0],
            "latitude": coordonnees.livraison[1],
        },
        "taille_colis": commande.taille_colis,
        "description_colis": commande.description_colis,
        "consignes": commande.consignes,
        "destinataire_nom": commande.destinataire_nom,
        "destinataire_telephone": commande.destinataire_telephone,
        "prix": commande.prix,
        "distance_m": commande.distance_m,
        "duree_estimee_s": commande.duree_estimee_s,
        "mode_paiement": commande.mode_paiement,
        "priorite": commande.priorite,
        "cree_le": commande.cree_le,
        "attribuee_le": commande.attribuee_le,
        "enlevee_le": commande.enlevee_le,
        "livree_le": commande.livree_le,
        "annulee_le": commande.annulee_le,
        "livreur": livreur,
    }


async def lister_commandes(
    session: AsyncSession,
    *,
    client_id: uuid.UUID | None = None,
    etat: EtatCommande | None = None,
    limite: int = 20,
    decalage: int = 0,
) -> list[Commande]:
    requete = select(Commande).order_by(Commande.cree_le.desc(), Commande.numero.desc())
    if client_id is not None:
        requete = requete.where(Commande.client_id == client_id)
    if etat is not None:
        requete = requete.where(Commande.etat == etat)
    return list(await session.scalars(requete.limit(limite).offset(decalage)))


async def annuler_commande(
    session: AsyncSession, flotte: Flotte, utilisateur: Utilisateur, commande_id: uuid.UUID
) -> Commande:
    commande = await charger_commande_visible(session, commande_id, utilisateur)
    try:
        commande = await commandes.changer_etat(
            session,
            commande.id,
            EtatCommande.ANNULEE,
            f"{utilisateur.role.value}:{utilisateur.id}",
            {"motif": "annulation"},
        )
    except TransitionInterdite as erreur:
        raise ErreurMetier(
            409, "Cette commande ne peut plus être annulée (colis déjà enlevé)."
        ) from erreur
    await flotte.annuler(commande.id)
    return commande


# --------------------------------------------------------------------------- côté livreur
async def mes_courses(session: AsyncSession, flotte: Flotte, utilisateur_id: uuid.UUID) -> dict:
    """Propositions à confirmer (en mémoire, limitées dans le temps) et courses en cours (base)."""
    maintenant = time.time()
    propositions = []
    for proposition in flotte.propositions_de(utilisateur_id):
        commande = await session.get(Commande, uuid.UUID(proposition.commande_id))
        propositions.append(
            {
                "commande_id": commande.id,
                "numero": commande.numero,
                "adresse_enlevement": commande.adresse_enlevement,
                "adresse_livraison": commande.adresse_livraison,
                "enlevement": {
                    "longitude": proposition.enlevement[0],
                    "latitude": proposition.enlevement[1],
                },
                "livraison": {
                    "longitude": proposition.livraison[0],
                    "latitude": proposition.livraison[1],
                },
                "prix": commande.prix,
                "expire_dans_s": max(0.0, round(proposition.expire_le - maintenant, 1)),
            }
        )
    en_cours = []
    for course in await commandes.courses_du_livreur(session, utilisateur_id):
        commande = await session.get(Commande, uuid.UUID(course["commande_id"]))
        en_cours.append(
            {
                "commande_id": commande.id,
                "numero": commande.numero,
                "etat": commande.etat,
                "enlevement": {
                    "adresse": commande.adresse_enlevement,
                    "longitude": course["enlevement"][0],
                    "latitude": course["enlevement"][1],
                },
                "livraison": {
                    "adresse": commande.adresse_livraison,
                    "longitude": course["livraison"][0],
                    "latitude": course["livraison"][1],
                },
                "destinataire_nom": commande.destinataire_nom,
                "destinataire_telephone": commande.destinataire_telephone,
                "consignes": commande.consignes,
                "prix": commande.prix,
                "mode_paiement": commande.mode_paiement,
            }
        )
    return {"propositions": propositions, "en_cours": en_cours}


async def _verifier_code_remise(
    session: AsyncSession, commande: Commande, code: str | None
) -> None:
    if not code:
        raise ErreurMetier(400, "Le code de remise est requis pour confirmer la livraison.")
    erreurs = await session.scalar(
        select(func.count())
        .select_from(Evenement)
        .where(Evenement.commande_id == commande.id, Evenement.type == "code_remise_invalide")
    )
    if erreurs >= CODES_ERRONES_MAX:
        raise ErreurMetier(429, "Trop de codes erronés : contactez le support.")
    attendu = commande.code_remise_hash or ""
    if not securite.codes_identiques(attendu, securite.hacher_code(str(commande.id), code)):
        await commandes.journaliser(
            session, commande.id, "code_remise_invalide", f"livreur:{commande.livreur_id}"
        )
        raise ErreurMetier(400, "Code de remise incorrect.")


async def signaler_etape(
    session: AsyncSession,
    flotte: Flotte,
    utilisateur_id: uuid.UUID,
    commande_id: uuid.UUID,
    etape: str,
    code: str | None,
    motif: str | None,
) -> None:
    commande = await session.get(Commande, commande_id)
    if commande is None or commande.livreur_id != utilisateur_id:
        raise ErreurMetier(404, "Course introuvable.")
    if commande.etat not in ETAPES_POSSIBLES[etape]:
        raise ErreurMetier(409, f"Étape impossible : la commande est « {commande.etat.value} ».")
    if etape == "livree":
        await _verifier_code_remise(session, commande, code)
    try:
        await flotte.signaler(utilisateur_id, str(commande.id), etape, motif)
    except LivreurHorsLigne as erreur:
        raise ErreurMetier(409, "Vous êtes hors ligne : passez en ligne d'abord.") from erreur
    except ValueError as erreur:
        raise ErreurMetier(409, "Course inconnue de votre session : repassez en ligne.") from erreur


# --------------------------------------------------------------------------- supervision
ETATS_TERMINES = (EtatCommande.LIVREE, EtatCommande.CLOTUREE, EtatCommande.ANNULEE)


async def alertes_ouvertes(session: AsyncSession, limite: int = 50) -> list[dict]:
    """Commandes signalées au répartiteur et pas encore résolues (une alerte par commande)."""
    lignes = await session.execute(
        select(Evenement, Commande)
        .join(Commande, Evenement.commande_id == Commande.id)
        .where(Evenement.type == "alerte_repartiteur", Commande.etat.not_in(ETATS_TERMINES))
        .order_by(Evenement.id.desc())
        .limit(limite * 4)
    )
    vues: dict[uuid.UUID, dict] = {}
    for evenement, commande in lignes:
        if commande.id not in vues and len(vues) < limite:
            vues[commande.id] = {
                "commande_id": commande.id,
                "numero": commande.numero,
                "etat": commande.etat,
                "raison": (evenement.detail or {}).get("raison"),
                "cree_le": evenement.horodatage,
            }
    return list(vues.values())


async def relancer_commande(
    session: AsyncSession, flotte: Flotte, utilisateur: Utilisateur, commande_id: uuid.UUID
) -> Commande:
    """Le répartiteur relance la recherche d'un livreur pour une commande restée sans livreur."""
    commande = await session.get(Commande, commande_id)
    if commande is None:
        raise ErreurMetier(404, "Commande introuvable.")
    if commande.etat != EtatCommande.EN_RECHERCHE:
        raise ErreurMetier(409, f"Relance impossible : la commande est « {commande.etat.value} ».")
    if str(commande.id) in flotte.dispatcher.conversations:
        raise ErreurMetier(409, "Une recherche est déjà en cours pour cette commande.")
    await commandes.journaliser(
        session, commande.id, "relance_manuelle", f"{utilisateur.role.value}:{utilisateur.id}"
    )
    flotte.dispatcher.exclusions.pop(str(commande.id), None)  # on peut re-solliciter tout le monde
    await flotte.soumettre(commande.id)
    return commande
