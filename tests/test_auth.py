from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from livraison.db.modeles import (
    CodeVerification,
    Evenement,
    Role,
    StatutCompte,
    Utilisateur,
)

TEL = "07 00 00 00 01"
TEL_E164 = "+2250700000001"


async def connecter(client, telephone=TEL, role="client", nom=None):
    """Parcours complet : demande de code puis vérification. Renvoie (jeton, utilisateur)."""
    r = await client.post("/auth/demander-code", json={"telephone": telephone})
    assert r.status_code == 200, r.text
    r = await client.post(
        "/auth/verifier-code",
        json={"telephone": telephone, "code": r.json()["code_dev"], "role": role, "nom": nom},
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"], r.json()["utilisateur"]


def entete(jeton):
    return {"Authorization": f"Bearer {jeton}"}


async def test_inscription_et_connexion(client):
    jeton, utilisateur = await connecter(client, nom="Awa")
    assert utilisateur["telephone"] == TEL_E164 and utilisateur["role"] == "client"

    moi = await client.get("/moi", headers=entete(jeton))
    assert moi.status_code == 200 and moi.json()["nom"] == "Awa"

    # deuxième connexion : même compte, le rôle demandé est ignoré
    _, encore = await connecter(client, role="livreur")
    assert encore["id"] == utilisateur["id"] and encore["role"] == "client"


async def test_le_code_n_est_pas_stocke_en_clair(client, session):
    r = await client.post("/auth/demander-code", json={"telephone": TEL})
    enregistrement = await session.scalar(select(CodeVerification))
    assert r.json()["code_dev"] not in enregistrement.code_hash


async def test_pas_de_code_dans_la_reponse_hors_dev(client, monkeypatch):
    from livraison.config import parametres

    monkeypatch.setattr(parametres, "environnement", "production")
    r = await client.post("/auth/demander-code", json={"telephone": TEL})
    assert r.status_code == 200 and r.json()["code_dev"] is None


async def test_telephone_invalide(client):
    r = await client.post("/auth/demander-code", json={"telephone": "abc"})
    assert r.status_code == 422


async def test_code_faux_refuse_puis_blocage_apres_5_essais(client):
    r = await client.post("/auth/demander-code", json={"telephone": TEL})
    bon = r.json()["code_dev"]
    faux = "000000" if bon != "000000" else "111111"
    for _ in range(5):
        r = await client.post("/auth/verifier-code", json={"telephone": TEL, "code": faux})
        assert r.status_code == 400
    r = await client.post("/auth/verifier-code", json={"telephone": TEL, "code": bon})
    assert r.status_code == 429  # même le bon code est refusé : il faut en redemander un


async def test_code_a_usage_unique(client):
    r = await client.post("/auth/demander-code", json={"telephone": TEL})
    code = r.json()["code_dev"]
    assert (
        await client.post("/auth/verifier-code", json={"telephone": TEL, "code": code})
    ).status_code == 200
    assert (
        await client.post("/auth/verifier-code", json={"telephone": TEL, "code": code})
    ).status_code == 400


async def test_code_expire(client, session):
    r = await client.post("/auth/demander-code", json={"telephone": TEL})
    await session.execute(
        update(CodeVerification).values(expire_le=datetime.now(UTC) - timedelta(seconds=1))
    )
    await session.commit()
    r = await client.post(
        "/auth/verifier-code", json={"telephone": TEL, "code": r.json()["code_dev"]}
    )
    assert r.status_code == 400


async def test_limite_de_demandes_de_code(client):
    for _ in range(5):
        assert (
            await client.post("/auth/demander-code", json={"telephone": TEL})
        ).status_code == 200
    assert (await client.post("/auth/demander-code", json={"telephone": TEL})).status_code == 429


async def test_acces_sans_jeton_ou_avec_faux_jeton(client):
    assert (await client.get("/moi")).status_code == 401
    assert (await client.get("/moi", headers=entete("n.importe.quoi"))).status_code == 401


async def test_on_ne_peut_pas_s_inscrire_administrateur(client):
    r = await client.post("/auth/demander-code", json={"telephone": TEL})
    r = await client.post(
        "/auth/verifier-code",
        json={"telephone": TEL, "code": r.json()["code_dev"], "role": "administrateur"},
    )
    assert r.status_code == 422


async def test_compte_suspendu(client, session):
    jeton, _ = await connecter(client)
    await session.execute(update(Utilisateur).values(statut=StatutCompte.SUSPENDU))
    await session.commit()
    assert (await client.get("/moi", headers=entete(jeton))).status_code == 403
    r = await client.post("/auth/demander-code", json={"telephone": TEL})
    r = await client.post(
        "/auth/verifier-code", json={"telephone": TEL, "code": r.json()["code_dev"]}
    )
    assert r.status_code == 403


async def test_dossier_livreur_et_validation_par_l_administrateur(client, session):
    jeton_livreur, livreur = await connecter(client, "07 00 00 00 10", role="livreur", nom="Moussa")
    jeton_client, _ = await connecter(client, "07 00 00 00 11")

    dossier = {
        "type_vehicule": "moto",
        "capacite_courses": 2,
        "pieces": [{"type": "permis", "reference": "P-123"}],
    }
    # un client ne peut pas déposer de dossier livreur
    assert (
        await client.put("/livreurs/moi/dossier", json=dossier, headers=entete(jeton_client))
    ).status_code == 403

    r = await client.put("/livreurs/moi/dossier", json=dossier, headers=entete(jeton_livreur))
    assert r.status_code == 200 and r.json()["statut_validation"] == "en_attente"

    # le compte administrateur est donné hors inscription (ici directement en base)
    session.add(Utilisateur(telephone="+2250700000099", role=Role.ADMINISTRATEUR, nom="Admin"))
    await session.commit()
    jeton_admin, _ = await connecter(client, "07 00 00 00 99")

    # ni le livreur ni le client n'accèdent à l'administration
    assert (await client.get("/admin/livreurs", headers=entete(jeton_livreur))).status_code == 403
    assert (await client.get("/admin/livreurs", headers=entete(jeton_client))).status_code == 403

    en_attente = await client.get("/admin/livreurs", headers=entete(jeton_admin))
    assert [d["utilisateur_id"] for d in en_attente.json()] == [livreur["id"]]

    r = await client.post(
        f"/admin/livreurs/{livreur['id']}/validation",
        json={"decision": "valide"},
        headers=entete(jeton_admin),
    )
    assert r.status_code == 200 and r.json()["statut_validation"] == "valide"
    mon = await client.get("/livreurs/moi/dossier", headers=entete(jeton_livreur))
    assert mon.json()["statut_validation"] == "valide"

    journal = await session.scalar(select(Evenement).where(Evenement.type == "livreur_valide"))
    assert journal is not None and journal.detail["livreur_id"] == livreur["id"]

    # modifier son dossier remet la validation en attente
    dossier["type_vehicule"] = "voiture"
    r = await client.put("/livreurs/moi/dossier", json=dossier, headers=entete(jeton_livreur))
    assert r.json()["statut_validation"] == "en_attente"


async def test_dossier_invalide(client):
    jeton, _ = await connecter(client, role="livreur")
    r = await client.put(
        "/livreurs/moi/dossier",
        json={"type_vehicule": "helicoptere"},
        headers=entete(jeton),
    )
    assert r.status_code == 422
