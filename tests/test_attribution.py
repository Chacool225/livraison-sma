"""Scénarios du lot 2 avec de vrais agents : exigent PostgreSQL (docker compose up -d) et le
serveur XMPP (spade run --memory) ; sinon ils sont ignorés."""

import asyncio
import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from livraison.db.modeles import EtatCommande as E
from livraison.db.modeles import ResultatOffre as R
from livraison.modele.geo import distance_m
from systeme import Systeme

ENLEVEMENT = (-4.0267, 5.3200)  # Plateau
LIVRAISON = (-3.9870, 5.3600)  # Cocody
A = (-4.0250, 5.3210)  # ~0,2 km de l'enlèvement
B = (-4.0100, 5.3300)  # ~2 km
C = (-3.9800, 5.3700)  # ~7,6 km : hors du rayon initial de 3 km


@pytest.fixture
async def creer_systeme(moteur, xmpp):
    fabrique = async_sessionmaker(moteur, expire_on_commit=False)
    crees: list[Systeme] = []

    async def creer(**reglages) -> Systeme:
        systeme = Systeme(fabrique, reglages)
        await systeme.demarrer()
        crees.append(systeme)
        return systeme

    yield creer
    for systeme in crees:
        await systeme.arreter()


async def test_attribution_au_livreur_le_plus_proche(creer_systeme):
    s = await creer_systeme()
    await s.livreur("a", A)
    await s.livreur("b", B)
    await s.livreur("c", C)
    await s.attendre_annuaire(3)

    cid = await s.commande(ENLEVEMENT, LIVRAISON)
    await s.soumettre(cid)
    (resultat,) = await s.resultats(1)

    assert resultat.etat == "attribuee" and resultat.livreur_id == s.id("a")
    commande = await s.lire(cid)
    assert commande.etat == E.ATTRIBUEE
    assert commande.livreur_id == uuid.UUID(s.id("a")) and commande.attribuee_le is not None

    par_livreur = {str(o.livreur_id): o.resultat for o in await s.offres(cid)}
    assert par_livreur == {s.id("a"): R.RETENUE, s.id("b"): R.REJETEE}  # C est hors du rayon
    types = await s.evenements(cid)
    assert types.index("etat_en_recherche") < types.index("etat_attribuee")


async def test_a_cout_egal_la_meilleure_note_gagne(creer_systeme):
    s = await creer_systeme()
    await s.livreur("a", A, note=3.0)
    await s.livreur("b", A, note=4.5)
    await s.attendre_annuaire(2)
    cid = await s.commande(ENLEVEMENT, LIVRAISON)
    await s.soumettre(cid)
    (resultat,) = await s.resultats(1)
    assert resultat.livreur_id == s.id("b")


async def test_deux_commandes_simultanees_sans_double_attribution(creer_systeme):
    """Chaque livreur n'a de place que pour une course : la réservation de capacité empêche
    de s'engager deux fois, et la commande restée sans offre est relancée."""
    s = await creer_systeme()
    await s.livreur("a", A, capacite=1)
    await s.livreur("b", B, capacite=1)
    await s.attendre_annuaire(2)

    c1 = await s.commande(ENLEVEMENT, LIVRAISON)
    c2 = await s.commande(ENLEVEMENT, LIVRAISON)
    await s.soumettre(c1, c2)
    resultats = await s.resultats(2)

    assert all(r.etat == "attribuee" for r in resultats)
    assert {r.livreur_id for r in resultats} == {s.id("a"), s.id("b")}
    assert {(await s.lire(c)).livreur_id for c in (c1, c2)} == {
        uuid.UUID(s.id("a")),
        uuid.UUID(s.id("b")),
    }
    assert s.livreurs["a"].charge == 1 and s.livreurs["b"].charge == 1


async def test_livreur_sature_puis_alerte_du_repartiteur(creer_systeme):
    s = await creer_systeme(tentatives_attribution_max=2, delai_relance_s=0.2)
    await s.livreur("a", A, capacite=1)
    await s.attendre_annuaire(1)

    c1 = await s.commande(ENLEVEMENT, LIVRAISON)
    await s.soumettre(c1)
    await s.resultats(1)
    c2 = await s.commande(ENLEVEMENT, LIVRAISON)
    await s.soumettre(c2)
    (resultat,) = await s.resultats(1)

    assert resultat.etat == "non_attribuee"
    assert (await s.lire(c2)).etat == E.EN_RECHERCHE
    assert [(o.resultat, o.motif) for o in await s.offres(c2)] == [(R.REFUSEE, "sature")] * 2
    assert "alerte_repartiteur" in await s.evenements(c2)


async def test_rayon_elargi_quand_personne_n_est_dans_la_zone(creer_systeme):
    s = await creer_systeme(
        rayon_recherche_initial_m=3000,
        rayon_pas_elargissement_m=2500,
        tentatives_attribution_max=4,
        delai_relance_s=0.1,
    )
    await s.livreur("c", C)
    await s.attendre_annuaire(1)
    assert 7000 < distance_m(ENLEVEMENT, C) < 8000

    cid = await s.commande(ENLEVEMENT, LIVRAISON)
    await s.soumettre(cid)
    (resultat,) = await s.resultats(1)

    assert resultat.etat == "attribuee" and resultat.tentatives == 3  # 3 km, 5,5 km, puis 8 km
    commande = await s.lire(cid)
    assert commande.rayon_recherche_m == 8000 and commande.tentatives_attribution == 3
    assert (await s.evenements(cid)).count("aucun_candidat") == 2


async def test_le_livreur_decline_la_course(creer_systeme):
    async def refuser(course):
        return False

    s = await creer_systeme()
    await s.livreur("a", A, confirmateur=refuser)
    await s.livreur("b", B)
    await s.attendre_annuaire(2)
    cid = await s.commande(ENLEVEMENT, LIVRAISON)
    await s.soumettre(cid)
    (resultat,) = await s.resultats(1)

    assert resultat.livreur_id == s.id("b") and resultat.tentatives == 2
    offres = [(str(o.livreur_id), o.tentative, o.resultat) for o in await s.offres(cid)]
    assert (s.id("a"), 1, R.DECLINEE) in offres
    assert (s.id("b"), 2, R.RETENUE) in offres
    assert s.livreurs["a"].charge == 0 and not s.livreurs["a"].reservations


async def test_le_livreur_ne_repond_pas_dans_le_delai(creer_systeme):
    async def silence(course):
        await asyncio.sleep(30)
        return True

    s = await creer_systeme(delai_confirmation_s=0.5)
    await s.livreur("a", A, confirmateur=silence)
    await s.livreur("b", B)
    await s.attendre_annuaire(2)
    cid = await s.commande(ENLEVEMENT, LIVRAISON)
    await s.soumettre(cid)
    (resultat,) = await s.resultats(1)

    assert resultat.livreur_id == s.id("b")
    assert (s.id("a"), R.EXPIREE) in [(str(o.livreur_id), o.resultat) for o in await s.offres(cid)]


async def test_position_trop_ancienne_refusee(creer_systeme):
    s = await creer_systeme(age_max_position_s=0.5)
    await s.livreur("a", A)
    b = await s.livreur("b", B)
    await s.attendre_annuaire(2)
    await asyncio.sleep(0.8)
    await b.mettre_a_jour_position(B)  # seul b a une position fraîche

    cid = await s.commande(ENLEVEMENT, LIVRAISON)
    await s.soumettre(cid)
    (resultat,) = await s.resultats(1)

    assert resultat.livreur_id == s.id("b")
    assert (R.REFUSEE, "position_trop_ancienne") in [
        (o.resultat, o.motif) for o in await s.offres(cid)
    ]


async def test_livreur_hors_ligne_absent_de_l_annuaire(creer_systeme):
    s = await creer_systeme()
    a = await s.livreur("a", A)
    await s.livreur("b", B)
    await s.attendre_annuaire(2)
    await a.passer_hors_ligne()
    await s.attendre_annuaire(1)

    cid = await s.commande(ENLEVEMENT, LIVRAISON)
    await s.soumettre(cid)
    (resultat,) = await s.resultats(1)
    assert resultat.livreur_id == s.id("b")


async def test_panne_avant_enlevement_reattribue_la_commande(creer_systeme):
    s = await creer_systeme()
    a = await s.livreur("a", A)
    await s.livreur("b", B)
    await s.attendre_annuaire(2)
    cid = await s.commande(ENLEVEMENT, LIVRAISON)
    await s.soumettre(cid)
    (premier,) = await s.resultats(1)
    assert premier.livreur_id == s.id("a")

    await a.signaler(str(cid), "echec", "panne de moto")
    (second,) = await s.resultats(1)

    assert second.etat == "attribuee" and second.livreur_id == s.id("b")
    commande = await s.lire(cid)
    assert commande.etat == E.ATTRIBUEE and commande.livreur_id == uuid.UUID(s.id("b"))
    assert "reattribution" in await s.evenements(cid)
    assert a.charge == 0


async def test_cycle_de_vie_jusqu_a_la_livraison(creer_systeme):
    s = await creer_systeme()
    a = await s.livreur("a", A)
    await s.attendre_annuaire(1)
    cid = await s.commande(ENLEVEMENT, LIVRAISON)
    await s.soumettre(cid)
    await s.resultats(1)

    await a.signaler(str(cid), "enlevee")
    commande = await s.attendre_etat(cid, E.ENLEVEE)
    assert commande.enlevee_le is not None and a.position == ENLEVEMENT

    await a.signaler(str(cid), "en_livraison")
    await s.attendre_etat(cid, E.EN_LIVRAISON)
    await a.signaler(str(cid), "livree")
    commande = await s.attendre_etat(cid, E.LIVREE)
    assert commande.livree_le is not None and a.charge == 0 and a.position == LIVRAISON


async def test_echec_apres_enlevement_alerte_sans_reattribuer(creer_systeme):
    s = await creer_systeme()
    a = await s.livreur("a", A)
    await s.livreur("b", B)
    await s.attendre_annuaire(2)
    cid = await s.commande(ENLEVEMENT, LIVRAISON)
    await s.soumettre(cid)
    await s.resultats(1)
    await a.signaler(str(cid), "enlevee")
    await s.attendre_etat(cid, E.ENLEVEE)

    await a.signaler(str(cid), "echec", "client injoignable")
    commande = await s.attendre_etat(cid, E.ECHEC_LIVRAISON)

    assert commande.livreur_id == uuid.UUID(s.id("a"))  # le colis reste chez lui
    assert "alerte_repartiteur" in await s.evenements(cid)
    assert s.dispatcher.sortie.empty()  # aucune nouvelle attribution automatique
