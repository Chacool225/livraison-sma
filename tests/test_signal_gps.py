"""Perte du signal GPS d'un livreur ayant une course en cours (F-34)."""

import asyncio
import contextlib

from livraison.db.modeles import EtatCommande as E
from systeme import ENLEVEMENT, LIVRAISON, A, B

REGLAGES = {"perte_signal_s": 1.5, "controle_gps_intervalle_s": 0.3}


@contextlib.asynccontextmanager
async def garder_signal(agent, point, periode=0.3):
    """Le livreur envoie sa position régulièrement, comme son application le ferait."""

    async def boucle():
        while True:
            await agent.mettre_a_jour_position(point)
            await asyncio.sleep(periode)

    tache = asyncio.create_task(boucle())
    try:
        yield
    finally:
        tache.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await tache


async def attendre(condition, timeout=10):
    async with asyncio.timeout(timeout):
        while not condition():
            await asyncio.sleep(0.1)


async def test_signal_perdu_avant_enlevement_reattribue_la_commande(creer_systeme):
    s = await creer_systeme(**REGLAGES)
    a = await s.livreur("a", A)  # le plus proche, mais il va se taire
    b = await s.livreur("b", B)
    await s.attendre_annuaire(2)

    async with garder_signal(b, B):
        cid = await s.commande(ENLEVEMENT, LIVRAISON)
        await s.soumettre(cid)
        (premier,) = await s.resultats(1)
        assert premier.livreur_id == s.id("a")

        (second,) = await s.resultats(1, timeout=20)  # après ~1,5 s de silence de a

    assert second.etat == "attribuee" and second.livreur_id == s.id("b")
    commande = await s.lire(cid)
    assert commande.etat == E.ATTRIBUEE and str(commande.livreur_id) == s.id("b")
    types = await s.evenements(cid)
    assert "perte_signal_gps" in types and "reattribution" in types
    await attendre(lambda: not a.courses)  # a est prévenu : la course ne lui appartient plus


async def test_signal_perdu_apres_enlevement_alerte_sans_reattribuer(creer_systeme):
    s = await creer_systeme(**REGLAGES)
    a = await s.livreur("a", A)
    await s.livreur("b", B)
    await s.attendre_annuaire(2)
    cid = await s.commande(ENLEVEMENT, LIVRAISON)
    await s.soumettre(cid)
    await s.resultats(1)
    await a.signaler(str(cid), "enlevee")
    await s.attendre_etat(cid, E.ENLEVEE)

    async with asyncio.timeout(15):
        while "alerte_repartiteur" not in await s.evenements(cid):
            await asyncio.sleep(0.2)
    await asyncio.sleep(1.5)  # plusieurs contrôles de plus : l'alerte ne doit pas se répéter

    types = await s.evenements(cid)
    assert types.count("alerte_repartiteur") == 1 and types.count("perte_signal_gps") == 1
    assert (await s.lire(cid)).etat == E.ENLEVEE  # le colis est chez a : pas de réattribution
    assert s.dispatcher.sortie.empty()


async def test_signal_maintenu_aucune_intervention(creer_systeme):
    s = await creer_systeme(**REGLAGES)
    a = await s.livreur("a", A)
    await s.attendre_annuaire(1)
    async with garder_signal(a, A):
        cid = await s.commande(ENLEVEMENT, LIVRAISON)
        await s.soumettre(cid)
        await s.resultats(1)
        await asyncio.sleep(3.5)  # plus de deux fois le délai de tolérance

    assert (await s.lire(cid)).etat == E.ATTRIBUEE and a.charge == 1
    assert "perte_signal_gps" not in await s.evenements(cid)


async def test_l_annuaire_donne_l_age_des_positions(creer_systeme):
    s = await creer_systeme()
    a = await s.livreur("a", A)
    await s.attendre_annuaire(1)
    await asyncio.sleep(0.5)
    assert 0.4 < s.annuaire.age_position_s(s.id("a")) < 2
    await a.mettre_a_jour_position(A)
    await asyncio.sleep(0.2)
    assert s.annuaire.age_position_s(s.id("a")) < 0.5
    assert s.annuaire.age_position_s("inconnu") is None
