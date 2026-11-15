"""L'API reliée aux agents : parcours client -> livreur de bout en bout, refus, annulations,
droits d'accès, redémarrage. Exigent PostgreSQL et le serveur XMPP (sinon ignorés)."""

import asyncio
import uuid

from geoalchemy2.elements import WKTElement
from sqlalchemy import select, update

from livraison.db.modeles import (
    Commande,
    EtatCommande,
    Evenement,
    Livreur,
    ModePaiement,
    Role,
    TailleColis,
    Utilisateur,
)
from test_auth import connecter, entete

ENLEVEMENT = {"adresse": "Plateau, Abidjan", "longitude": -4.0267, "latitude": 5.32}
LIVRAISON = {"adresse": "Cocody, Abidjan", "longitude": -3.987, "latitude": 5.36}
LIVRAISON_PROCHE = {"adresse": "Marcory, Abidjan", "longitude": -4.0, "latitude": 5.33}
COMMANDE = {
    "enlevement": ENLEVEMENT,
    "livraison": LIVRAISON,
    "taille_colis": "petit",
    "destinataire_nom": "Awa",
    "destinataire_telephone": "07 11 22 33 44",
    "consignes": "Sonner deux fois",
}
PRES = {"longitude": -4.025, "latitude": 5.321}  # à ~200 m de l'enlèvement
LOIN = {"longitude": -4.01, "latitude": 5.33}  # à ~2 km


async def attendre(fonction, timeout=15):
    """Appelle `fonction` jusqu'à ce qu'elle renvoie une valeur vraie."""
    async with asyncio.timeout(timeout):
        while True:
            valeur = await fonction()
            if valeur:
                return valeur
            await asyncio.sleep(0.15)


class Scenario:
    """Petits gestes réutilisés par les tests, pour qu'ils restent lisibles."""

    def __init__(self, api):
        self.api = api
        self.http = api.client

    async def livreur(self, telephone, nom="Moussa", *, valide=True, capacite=2, en_ligne=PRES):
        jeton, compte = await connecter(self.http, telephone, "livreur", nom)
        dossier = {"type_vehicule": "moto", "capacite_courses": capacite}
        await self.http.put("/livreurs/moi/dossier", json=dossier, headers=entete(jeton))
        if valide:
            async with self.api.fabrique() as session:
                await session.execute(
                    update(Livreur)
                    .where(Livreur.utilisateur_id == uuid.UUID(compte["id"]))
                    .values(statut_validation="valide")
                )
                await session.commit()
        if en_ligne:
            r = await self.http.post("/livreurs/moi/en-ligne", json=en_ligne, headers=entete(jeton))
            assert r.status_code == 200, r.text
        return jeton, compte

    async def client(self, telephone="07 00 00 10 00"):
        return await connecter(self.http, telephone, "client", "Awa Client")

    async def commander(self, jeton, **changements):
        r = await self.http.post(
            "/commandes", json={**COMMANDE, **changements}, headers=entete(jeton)
        )
        assert r.status_code == 201, r.text
        return r.json()

    async def etat(self, jeton, commande_id):
        r = await self.http.get(f"/commandes/{commande_id}", headers=entete(jeton))
        return r.json()["etat"]

    async def attendre_etat(self, jeton, commande_id, etat, timeout=15):
        async def condition():
            return await self.etat(jeton, commande_id) == etat

        await attendre(condition, timeout)

    async def proposition(self, jeton_livreur, timeout=15):
        async def lire():
            r = await self.http.get("/livreurs/moi/courses", headers=entete(jeton_livreur))
            return (r.json()["propositions"] or [None])[0]

        return await attendre(lire, timeout)

    async def repondre(self, jeton_livreur, commande_id, accepte):
        return await self.http.post(
            f"/livreurs/moi/courses/{commande_id}/reponse",
            json={"accepte": accepte},
            headers=entete(jeton_livreur),
        )

    async def etape(self, jeton_livreur, commande_id, etape, code=None):
        return await self.http.post(
            f"/livreurs/moi/courses/{commande_id}/etape",
            json={"etape": etape, "code": code},
            headers=entete(jeton_livreur),
        )

    async def evenements(self, commande_id):
        async with self.api.fabrique() as session:
            lignes = await session.scalars(
                select(Evenement.type)
                .where(Evenement.commande_id == uuid.UUID(commande_id))
                .order_by(Evenement.id)
            )
            return list(lignes)

    async def administrateur(self, telephone="07 00 00 99 99"):
        async with self.api.fabrique() as session:
            session.add(
                Utilisateur(
                    telephone="+22507" + telephone.replace(" ", "")[2:], role=Role.ADMINISTRATEUR
                )
            )
            await session.commit()
        return (await connecter(self.http, telephone))[0]


async def test_parcours_complet_du_client_au_livreur(creer_api):
    api = await creer_api()
    s = Scenario(api)
    jeton_client, _ = await s.client()
    jeton_livreur, livreur = await s.livreur("07 00 00 20 00")

    commande = await s.commander(jeton_client)
    cid = commande["id"]
    assert commande["etat"] in ("validee", "en_recherche")
    assert commande["prix"] >= 500 and commande["prix"] % 50 == 0
    assert commande["distance_m"] > 5000 and commande["duree_estimee_s"] > 0
    assert len(commande["code_remise"]) == 4 and commande["code_remise"].isdigit()
    assert commande["destinataire_telephone"] == "+2250711223344"

    # Le livreur reçoit la proposition, avec un compte à rebours.
    proposition = await s.proposition(jeton_livreur)
    assert proposition["commande_id"] == cid and proposition["prix"] == commande["prix"]
    assert proposition["adresse_enlevement"] == "Plateau, Abidjan"
    assert 0 < proposition["expire_dans_s"] <= 6

    assert (await s.repondre(jeton_livreur, cid, True)).status_code == 200
    await s.attendre_etat(jeton_client, cid, "attribuee")

    detail = (await api.client.get(f"/commandes/{cid}", headers=entete(jeton_client))).json()
    assert detail["livreur"]["nom"] == "Moussa" and detail["livreur"]["type_vehicule"] == "moto"
    assert detail["livreur"]["position"]["longitude"] == PRES["longitude"]
    assert "code_remise" not in detail  # le code n'est montré qu'à la création

    courses = (await api.client.get("/livreurs/moi/courses", headers=entete(jeton_livreur))).json()
    assert [c["commande_id"] for c in courses["en_cours"]] == [cid]
    assert courses["propositions"] == []

    # Le livreur se déplace : le client suit sa position.
    nouvelle = {"longitude": -4.026, "latitude": 5.3205, "precision_m": 8}
    r = await api.client.put("/livreurs/moi/position", json=nouvelle, headers=entete(jeton_livreur))
    assert r.status_code == 200
    detail = (await api.client.get(f"/commandes/{cid}", headers=entete(jeton_client))).json()
    assert detail["livreur"]["position"]["longitude"] == -4.026
    async with api.fabrique() as session:
        from livraison.db.modeles import Position

        assert await session.scalar(
            select(Position.id).where(Position.livreur_id == uuid.UUID(livreur["id"]))
        )

    # Étapes : l'ordre est imposé, la livraison exige le code du destinataire.
    assert (await s.etape(jeton_livreur, cid, "livree", commande["code_remise"])).status_code == 409
    assert (await s.etape(jeton_livreur, cid, "enlevee")).status_code == 202
    await s.attendre_etat(jeton_client, cid, "enlevee")

    faux = "0000" if commande["code_remise"] != "0000" else "1111"
    assert (await s.etape(jeton_livreur, cid, "livree")).status_code == 400  # code manquant
    assert (await s.etape(jeton_livreur, cid, "livree", faux)).status_code == 400  # code faux
    assert (await s.etape(jeton_livreur, cid, "livree", commande["code_remise"])).status_code == 202
    await s.attendre_etat(jeton_client, cid, "livree")

    final = (await api.client.get(f"/commandes/{cid}", headers=entete(jeton_client))).json()
    assert final["livree_le"] and final["enlevee_le"] and final["attribuee_le"]
    types = await s.evenements(cid)
    assert types.count("code_remise_invalide") == 1
    assert [t for t in types if t.startswith("etat_")] == [
        "etat_validee",
        "etat_en_recherche",
        "etat_attribuee",
        "etat_enlevee",
        "etat_livree",
    ]

    # Course terminée : le livreur peut se déconnecter, son agent disparaît.
    r = await api.client.post("/livreurs/moi/hors-ligne", headers=entete(jeton_livreur))
    assert r.status_code == 200 and api.flotte.livreurs == {}
    async with api.fabrique() as session:
        assert not (await session.get(Livreur, uuid.UUID(livreur["id"]))).en_ligne


async def test_le_livreur_decline_la_course_va_au_suivant(creer_api):
    api = await creer_api()
    s = Scenario(api)
    jeton_client, _ = await s.client()
    jeton_a, _ = await s.livreur("07 00 00 20 01", "Ali", en_ligne=PRES)
    jeton_b, _ = await s.livreur("07 00 00 20 02", "Boubou", en_ligne=LOIN)

    cid = (await s.commander(jeton_client))["id"]
    await s.proposition(jeton_a)  # le plus proche est sollicité en premier
    assert (await s.repondre(jeton_a, cid, False)).status_code == 200
    await s.proposition(jeton_b)
    assert (await s.repondre(jeton_b, cid, True)).status_code == 200

    await s.attendre_etat(jeton_client, cid, "attribuee")
    detail = (await api.client.get(f"/commandes/{cid}", headers=entete(jeton_client))).json()
    assert detail["livreur"]["nom"] == "Boubou"
    assert (await s.repondre(jeton_a, cid, True)).status_code == 404  # plus de proposition pour Ali


async def test_aucun_livreur_en_ligne_alerte_le_repartiteur(creer_api):
    api = await creer_api(tentatives_attribution_max=2, delai_relance_s=0.2)
    s = Scenario(api)
    jeton_client, _ = await s.client()
    cid = (await s.commander(jeton_client))["id"]

    async def alerte():
        return "alerte_repartiteur" in await s.evenements(cid)

    await attendre(alerte)
    assert await s.etat(jeton_client, cid) == "en_recherche"


async def test_annulation_pendant_la_proposition(creer_api):
    api = await creer_api()
    s = Scenario(api)
    jeton_client, _ = await s.client()
    jeton_livreur, _ = await s.livreur("07 00 00 20 03")
    cid = (await s.commander(jeton_client))["id"]
    await s.proposition(jeton_livreur)

    r = await api.client.post(f"/commandes/{cid}/annulation", headers=entete(jeton_client))
    assert r.status_code == 200 and r.json()["etat"] == "annulee"

    courses = (await api.client.get("/livreurs/moi/courses", headers=entete(jeton_livreur))).json()
    assert courses["propositions"] == []  # la proposition a disparu de l'écran du livreur
    assert (await s.repondre(jeton_livreur, cid, True)).status_code == 404
    await asyncio.sleep(2.5)  # la recherche s'est arrêtée : rien n'est attribué
    assert await s.etat(jeton_client, cid) == "annulee"
    assert next(iter(api.flotte.livreurs.values())).charge == 0


async def test_annulation_apres_attribution_previent_le_livreur(creer_api):
    api = await creer_api()
    s = Scenario(api)
    jeton_client, _ = await s.client()
    jeton_livreur, _ = await s.livreur("07 00 00 20 04")
    commande = await s.commander(jeton_client)
    cid = commande["id"]
    await s.proposition(jeton_livreur)
    await s.repondre(jeton_livreur, cid, True)
    await s.attendre_etat(jeton_client, cid, "attribuee")

    r = await api.client.post(f"/commandes/{cid}/annulation", headers=entete(jeton_client))
    assert r.status_code == 200

    async def course_retiree():
        c = (await api.client.get("/livreurs/moi/courses", headers=entete(jeton_livreur))).json()
        return not c["en_cours"]

    await attendre(course_retiree)
    assert next(iter(api.flotte.livreurs.values())).charge == 0  # sa capacité est libérée

    # Un colis déjà enlevé ne s'annule plus.
    cid2 = (await s.commander(jeton_client))["id"]
    await s.proposition(jeton_livreur)
    await s.repondre(jeton_livreur, cid2, True)
    await s.attendre_etat(jeton_client, cid2, "attribuee")
    await s.etape(jeton_livreur, cid2, "enlevee")
    await s.attendre_etat(jeton_client, cid2, "enlevee")
    r = await api.client.post(f"/commandes/{cid2}/annulation", headers=entete(jeton_client))
    assert r.status_code == 409


async def test_droits_d_acces_et_validations(creer_api):
    api = await creer_api()
    s = Scenario(api)
    http = api.client
    jeton_client, _ = await s.client("07 00 00 10 01")
    autre_client, _ = await s.client("07 00 00 10 02")
    jeton_livreur, _ = await s.livreur("07 00 00 20 05")
    non_valide, _ = await s.livreur("07 00 00 20 06", valide=False, en_ligne=None)
    jeton_admin = await s.administrateur()

    # qui peut faire quoi
    r = await http.post("/livreurs/moi/en-ligne", json=PRES, headers=entete(non_valide))
    assert r.status_code == 403  # dossier non validé
    assert (
        await http.post("/livreurs/moi/en-ligne", json=PRES, headers=entete(jeton_client))
    ).status_code == 403
    assert (
        await http.post("/commandes", json=COMMANDE, headers=entete(jeton_livreur))
    ).status_code == 403
    assert (await http.post("/commandes", json=COMMANDE)).status_code == 401

    cid = (await s.commander(jeton_client))["id"]
    assert (await http.get(f"/commandes/{cid}", headers=entete(autre_client))).status_code == 404
    assert (await http.get(f"/commandes/{cid}", headers=entete(jeton_admin))).status_code == 200
    assert (
        await http.post(f"/commandes/{cid}/annulation", headers=entete(autre_client))
    ).status_code == 404
    mes = (await http.get("/commandes", headers=entete(jeton_client))).json()
    assert [c["id"] for c in mes] == [cid]
    assert (await http.get("/commandes", headers=entete(autre_client))).json() == []

    # supervision
    assert (await http.get("/admin/commandes", headers=entete(jeton_client))).status_code == 403
    toutes = (await http.get("/admin/commandes", headers=entete(jeton_admin))).json()
    assert cid in [c["id"] for c in toutes]
    agents = (await http.get("/admin/agents", headers=entete(jeton_admin))).json()
    assert len(agents) == 1 and agents[0]["vehicule"] == "moto"

    # commandes invalides
    meme_lieu = {"livraison": ENLEVEMENT}
    assert (
        await http.post("/commandes", json={**COMMANDE, **meme_lieu}, headers=entete(jeton_client))
    ).status_code == 422
    hors_bornes = {"livraison": {**LIVRAISON, "latitude": 95}}
    assert (
        await http.post(
            "/commandes", json={**COMMANDE, **hors_bornes}, headers=entete(jeton_client)
        )
    ).status_code == 422
    mauvais_tel = {"destinataire_telephone": "abc"}
    assert (
        await http.post(
            "/commandes", json={**COMMANDE, **mauvais_tel}, headers=entete(jeton_client)
        )
    ).status_code == 422
    paiement = {"mode_paiement": "carte"}
    assert (
        await http.post("/commandes", json={**COMMANDE, **paiement}, headers=entete(jeton_client))
    ).status_code == 422

    # un livreur ne touche pas à la course d'un autre, ni hors ligne
    await s.proposition(jeton_livreur)
    await s.repondre(jeton_livreur, cid, True)
    await s.attendre_etat(jeton_client, cid, "attribuee")
    autre_livreur, _ = await s.livreur("07 00 00 20 07", "Autre", en_ligne=LOIN)
    assert (await s.etape(autre_livreur, cid, "enlevee")).status_code == 404
    r = await http.post("/livreurs/moi/hors-ligne", headers=entete(jeton_livreur))
    assert r.status_code == 409  # course en cours
    r = await http.put("/livreurs/moi/position", json=PRES, headers=entete(non_valide))
    assert r.status_code == 403
    await http.post("/livreurs/moi/hors-ligne", headers=entete(autre_livreur))
    assert (
        await http.put("/livreurs/moi/position", json=LOIN, headers=entete(autre_livreur))
    ).status_code == 409


async def test_le_prix_augmente_avec_la_distance(creer_api):
    api = await creer_api()
    s = Scenario(api)
    jeton_client, _ = await s.client()
    proche = await s.commander(jeton_client, livraison=LIVRAISON_PROCHE)
    loin = await s.commander(jeton_client)
    assert 0 < proche["distance_m"] < loin["distance_m"]
    assert proche["prix"] < loin["prix"]
    assert loin["prix"] % 50 == 0 and proche["prix"] % 50 == 0


async def test_sans_agents_les_commandes_sont_refusees_mais_le_reste_marche(client):
    from livraison.api.main import app

    app.state.flotte = None
    jeton, _ = await connecter(client, "07 00 00 10 03")
    assert (
        await client.post("/commandes", json=COMMANDE, headers=entete(jeton))
    ).status_code == 503
    assert (await client.get("/moi", headers=entete(jeton))).status_code == 200
    assert (await client.get("/sante")).json() == {"etat": "ok", "agents": False}


async def test_redemarrage_reprise_des_recherches_et_courses(creer_api):
    api = await creer_api()
    s = Scenario(api)
    jeton_client, _ = await s.client()
    jeton_livreur, _ = await s.livreur("07 00 00 20 08")
    commande = await s.commander(jeton_client)
    cid = commande["id"]
    await s.proposition(jeton_livreur)
    await s.repondre(jeton_livreur, cid, True)
    await s.attendre_etat(jeton_client, cid, "attribuee")

    # Commande créée pendant que le serveur est arrêté : sa recherche reprendra au démarrage.
    await api.flotte.arreter()
    async with api.fabrique() as session:
        client_id = await session.scalar(
            select(Utilisateur.id).where(Utilisateur.role == Role.CLIENT)
        )
        orpheline = Commande(
            client_id=client_id,
            adresse_enlevement="A",
            point_enlevement=WKTElement("POINT(-4.0267 5.32)", srid=4326),
            adresse_livraison="B",
            point_livraison=WKTElement("POINT(-3.987 5.36)", srid=4326),
            taille_colis=TailleColis.PETIT,
            prix=1500,
            mode_paiement=ModePaiement.ESPECES,
            etat=EtatCommande.VALIDEE,
        )
        session.add(orpheline)
        await session.commit()
        orpheline_id = str(orpheline.id)

    # Nouveau serveur : le livreur se reconnecte, retrouve sa course et la mène à terme.
    api = await creer_api(tentatives_attribution_max=20, delai_relance_s=0.3)
    r = await api.client.post("/livreurs/moi/en-ligne", json=PRES, headers=entete(jeton_livreur))
    assert r.status_code == 200
    courses = (await api.client.get("/livreurs/moi/courses", headers=entete(jeton_livreur))).json()
    assert cid in [c["commande_id"] for c in courses["en_cours"]]
    assert (
        next(iter(api.flotte.livreurs.values())).charge == 1
    )  # sa capacité tient compte de la course

    assert (await s.etape(jeton_livreur, cid, "enlevee")).status_code == 202
    await s.attendre_etat(jeton_client, cid, "enlevee")
    assert (await s.etape(jeton_livreur, cid, "livree", commande["code_remise"])).status_code == 202
    await s.attendre_etat(jeton_client, cid, "livree")

    # La commande orpheline a été reprise : le livreur (libre) reçoit la proposition.
    proposition = await s.proposition(jeton_livreur)
    assert proposition["commande_id"] == orpheline_id
