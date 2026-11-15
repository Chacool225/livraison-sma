"""Estimation du prix, dossiers avec noms, alertes et relance (supervision)."""

from test_api_courses import ENLEVEMENT, LIVRAISON, PRES, Scenario, attendre
from test_auth import entete


async def test_estimation_identique_au_prix_de_la_commande(creer_api):
    api = await creer_api()
    s = Scenario(api)
    jeton_client, _ = await s.client()
    corps = {"enlevement": ENLEVEMENT, "livraison": LIVRAISON}

    r = await api.client.post("/commandes/estimation", json=corps, headers=entete(jeton_client))
    assert r.status_code == 200
    estimation = r.json()
    commande = await s.commander(jeton_client)
    assert estimation == {
        "prix": commande["prix"],
        "distance_m": commande["distance_m"],
        "duree_estimee_s": commande["duree_estimee_s"],
    }
    async with api.fabrique() as session:  # l'estimation n'a rien enregistré
        from sqlalchemy import func, select

        from livraison.db.modeles import Commande

        assert await session.scalar(select(func.count()).select_from(Commande)) == 1


async def test_estimation_droits_et_erreurs(creer_api):
    api = await creer_api()
    s = Scenario(api)
    http = api.client
    jeton_client, _ = await s.client()
    jeton_livreur, _ = await s.livreur("07 00 00 21 00", en_ligne=None)
    corps = {"enlevement": ENLEVEMENT, "livraison": LIVRAISON}
    assert (
        await http.post("/commandes/estimation", json=corps, headers=entete(jeton_livreur))
    ).status_code == 403
    assert (await http.post("/commandes/estimation", json=corps)).status_code == 401
    meme = {"enlevement": ENLEVEMENT, "livraison": ENLEVEMENT}
    assert (
        await http.post("/commandes/estimation", json=meme, headers=entete(jeton_client))
    ).status_code == 422


async def test_dossiers_a_valider_avec_nom_et_telephone(creer_api):
    api = await creer_api()
    s = Scenario(api)
    await s.livreur("07 00 00 21 01", "Moussa Test", valide=False, en_ligne=None)
    jeton_admin = await s.administrateur()
    dossiers = (await api.client.get("/admin/livreurs", headers=entete(jeton_admin))).json()
    assert [(d["nom"], d["telephone"]) for d in dossiers] == [("Moussa Test", "+2250700002101")]
    assert dossiers[0]["type_vehicule"] == "moto"


async def test_agents_en_ligne_avec_noms(creer_api):
    api = await creer_api()
    s = Scenario(api)
    await s.livreur("07 00 00 21 02", "Aminata")
    jeton_admin = await s.administrateur()
    agents = (await api.client.get("/admin/agents", headers=entete(jeton_admin))).json()
    assert [a["nom"] for a in agents] == ["Aminata"] and agents[0]["telephone"] == "+2250700002102"


async def test_alerte_puis_relance_par_le_repartiteur(creer_api):
    api = await creer_api(tentatives_attribution_max=2, delai_relance_s=0.2)
    s = Scenario(api)
    http = api.client
    jeton_client, _ = await s.client()
    jeton_admin = await s.administrateur()
    cid = (await s.commander(jeton_client))["id"]

    async def alerte_visible():
        return (await http.get("/admin/alertes", headers=entete(jeton_admin))).json()

    alertes = await attendre(alerte_visible)
    assert alertes[0]["commande_id"] == cid and alertes[0]["raison"] == "attribution_impossible"
    assert alertes[0]["etat"] == "en_recherche"
    assert (await http.get("/admin/alertes", headers=entete(jeton_client))).status_code == 403

    # Un livreur se met en ligne : le répartiteur relance, la course lui est proposée.
    jeton_livreur, _ = await s.livreur("07 00 00 21 03", "Disponible", en_ligne=PRES)
    assert (
        await http.post(f"/admin/commandes/{cid}/relance", headers=entete(jeton_client))
    ).status_code == 403
    r = await http.post(f"/admin/commandes/{cid}/relance", headers=entete(jeton_admin))
    assert r.status_code == 200
    await s.proposition(jeton_livreur)
    await s.repondre(jeton_livreur, cid, True)
    await s.attendre_etat(jeton_client, cid, "attribuee")

    # Résolue : l'alerte n'est plus ouverte une fois la commande terminée ou annulée.
    await http.post(f"/commandes/{cid}/annulation", headers=entete(jeton_client))
    assert (await http.get("/admin/alertes", headers=entete(jeton_admin))).json() == []


async def test_relance_refusee_hors_recherche(creer_api):
    api = await creer_api()
    s = Scenario(api)
    http = api.client
    jeton_client, _ = await s.client()
    jeton_livreur, _ = await s.livreur("07 00 00 21 04")
    jeton_admin = await s.administrateur()
    cid = (await s.commander(jeton_client))["id"]
    await s.proposition(jeton_livreur)
    await s.repondre(jeton_livreur, cid, True)
    await s.attendre_etat(jeton_client, cid, "attribuee")

    r = await http.post(f"/admin/commandes/{cid}/relance", headers=entete(jeton_admin))
    assert r.status_code == 409  # déjà attribuée
    inconnu = "00000000-0000-0000-0000-000000000000"
    assert (
        await http.post(f"/admin/commandes/{inconnu}/relance", headers=entete(jeton_admin))
    ).status_code == 404
