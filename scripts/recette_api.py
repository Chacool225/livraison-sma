"""Recette de l'API : déroule le parcours complet contre un serveur en marche et vérifie chaque
code de réponse. Le serveur doit tourner en mode « dev » (le code SMS est alors renvoyé).

Prérequis :
    1. uvicorn livraison.api.main:app          (dans un terminal)
    2. python scripts\\creer_admin.py "07 00 00 00 00" "Admin"   (une seule fois)
Usage :
    python scripts\\recette_api.py [--url http://127.0.0.1:8000] [--admin "07 00 00 00 00"]
"""

import argparse
import random
import sys

import httpx

verifications: list[tuple[bool, str]] = []


def verifier(condition: bool, libelle: str, detail: str = "") -> bool:
    verifications.append((condition, libelle))
    print(
        f"  [{'OK' if condition else 'KO'}] {libelle}"
        + (f"  -> {detail}" if not condition and detail else "")
    )
    return condition


def telephone_aleatoire() -> str:
    return f"07{random.randint(10_000_000, 99_999_999)}"


def entete(jeton: str) -> dict:
    return {"Authorization": f"Bearer {jeton}"}


class Recette:
    def __init__(self, url: str):
        self.http = httpx.Client(base_url=url, timeout=10)

    def demander_code(self, telephone: str) -> httpx.Response:
        return self.http.post("/auth/demander-code", json={"telephone": telephone})

    def connecter(
        self, telephone: str, role: str = "client", nom: str | None = None
    ) -> tuple[str, dict]:
        code = self.demander_code(telephone).json()["code_dev"]
        reponse = self.http.post(
            "/auth/verifier-code",
            json={"telephone": telephone, "code": code, "role": role, "nom": nom},
        )
        reponse.raise_for_status()
        donnees = reponse.json()
        return donnees["access_token"], donnees["utilisateur"]


def main() -> int:
    analyseur = argparse.ArgumentParser()
    analyseur.add_argument("--url", default="http://127.0.0.1:8000")
    analyseur.add_argument(
        "--admin", default="07 00 00 00 00", help="numéro créé avec creer_admin.py"
    )
    args = analyseur.parse_args()
    r = Recette(args.url)

    print("\n1. Serveur")
    try:
        reponse = r.http.get("/sante")
    except httpx.HTTPError as erreur:
        print(f"  [KO] Serveur injoignable ({erreur}). Lancer : uvicorn livraison.api.main:app")
        return 1
    verifier(reponse.status_code == 200 and reponse.json()["etat"] == "ok", "GET /sante répond ok")

    print("\n2. Inscription et connexion")
    tel_client, tel_livreur = telephone_aleatoire(), telephone_aleatoire()
    jeton_client, client = r.connecter(tel_client, "client", "Client Recette")
    verifier(client["role"] == "client", "Un nouveau numéro devient un client")
    moi = r.http.get("/moi", headers=entete(jeton_client))
    verifier(
        moi.status_code == 200 and moi.json()["nom"] == "Client Recette", "GET /moi avec le jeton"
    )
    _, encore = r.connecter(tel_client, "livreur")
    verifier(
        encore["id"] == client["id"] and encore["role"] == "client",
        "Reconnexion : même compte, rôle inchangé",
    )

    print("\n3. Dossier livreur")
    jeton_livreur, livreur = r.connecter(tel_livreur, "livreur", "Livreur Recette")
    verifier(livreur["role"] == "livreur", "Inscription avec le rôle livreur")
    avant = r.http.get("/livreurs/moi/dossier", headers=entete(jeton_livreur))
    verifier(avant.status_code == 404, "Pas de dossier avant dépôt (404)")
    dossier = {
        "type_vehicule": "moto",
        "capacite_courses": 2,
        "pieces": [{"type": "permis", "reference": "P-123"}],
    }
    depot = r.http.put("/livreurs/moi/dossier", json=dossier, headers=entete(jeton_livreur))
    verifier(
        depot.status_code == 200 and depot.json()["statut_validation"] == "en_attente",
        "Dépôt du dossier : en_attente",
    )
    refus_client = r.http.put("/livreurs/moi/dossier", json=dossier, headers=entete(jeton_client))
    verifier(
        refus_client.status_code == 403, "Un client ne peut pas déposer de dossier livreur (403)"
    )
    invalide = r.http.put(
        "/livreurs/moi/dossier",
        json={"type_vehicule": "helicoptere"},
        headers=entete(jeton_livreur),
    )
    verifier(invalide.status_code == 422, "Véhicule invalide refusé (422)")

    print("\n4. Validation par l'administrateur")
    try:
        jeton_admin, admin = r.connecter(args.admin)
    except (KeyError, httpx.HTTPError):
        print(
            "  [KO] Connexion de l'administrateur impossible : a-t-il été créé avec creer_admin.py ?"
        )
        return 1
    verifier(admin["role"] == "administrateur", "Le compte créé par le script est administrateur")
    attente = r.http.get("/admin/livreurs", headers=entete(jeton_admin))
    verifier(
        livreur["id"] in [d["utilisateur_id"] for d in attente.json()],
        "Le dossier apparaît dans la liste en attente",
    )
    decision = r.http.post(
        f"/admin/livreurs/{livreur['id']}/validation",
        json={"decision": "valide"},
        headers=entete(jeton_admin),
    )
    verifier(
        decision.status_code == 200 and decision.json()["statut_validation"] == "valide",
        "Validation du dossier",
    )
    vu = r.http.get("/livreurs/moi/dossier", headers=entete(jeton_livreur))
    verifier(vu.json()["statut_validation"] == "valide", "Le livreur voit son dossier validé")
    dossier["type_vehicule"] = "voiture"
    modif = r.http.put("/livreurs/moi/dossier", json=dossier, headers=entete(jeton_livreur))
    verifier(
        modif.json()["statut_validation"] == "en_attente",
        "Modifier le dossier remet la validation en attente",
    )

    print("\n5. Droits d'accès")
    verifier(
        r.http.get("/admin/livreurs", headers=entete(jeton_client)).status_code == 403,
        "Client sur /admin/livreurs : 403",
    )
    verifier(
        r.http.get("/admin/livreurs", headers=entete(jeton_livreur)).status_code == 403,
        "Livreur sur /admin/livreurs : 403",
    )
    verifier(r.http.get("/moi").status_code == 401, "Sans jeton : 401")
    verifier(
        r.http.get("/moi", headers=entete("faux.jeton.ici")).status_code == 401,
        "Jeton falsifié : 401",
    )
    tel = telephone_aleatoire()
    code = r.demander_code(tel).json()["code_dev"]
    pirate = r.http.post(
        "/auth/verifier-code", json={"telephone": tel, "code": code, "role": "administrateur"}
    )
    verifier(pirate.status_code == 422, "S'inscrire administrateur est refusé (422)")

    print("\n6. Codes de vérification")
    verifier(r.demander_code("abc").status_code == 422, "Numéro invalide refusé (422)")
    tel = telephone_aleatoire()
    bon = r.demander_code(tel).json()["code_dev"]
    faux = "000000" if bon != "000000" else "111111"
    statuts = [
        r.http.post("/auth/verifier-code", json={"telephone": tel, "code": faux}).status_code
        for _ in range(5)
    ]
    verifier(statuts == [400] * 5, "5 mauvais codes : 400 à chaque fois", str(statuts))
    bloque = r.http.post("/auth/verifier-code", json={"telephone": tel, "code": bon})
    verifier(bloque.status_code == 429, "Après 5 échecs, même le bon code est refusé (429)")
    tel = telephone_aleatoire()
    code = r.demander_code(tel).json()["code_dev"]
    premier = r.http.post("/auth/verifier-code", json={"telephone": tel, "code": code})
    second = r.http.post("/auth/verifier-code", json={"telephone": tel, "code": code})
    verifier(
        premier.status_code == 200 and second.status_code == 400,
        "Un code ne sert qu'une fois (200 puis 400)",
    )
    tel = telephone_aleatoire()
    statuts = [r.demander_code(tel).status_code for _ in range(6)]
    verifier(statuts == [200] * 5 + [429], "6e demande de code en 10 minutes : 429", str(statuts))

    ok = sum(1 for reussi, _ in verifications if reussi)
    print(f"\n{ok}/{len(verifications)} vérifications réussies.")
    if ok == len(verifications):
        print("\nPour le test de redémarrage de PostgreSQL, garde ce jeton client :")
        print(jeton_client)
        print("\n  docker compose restart postgres     (attendre « healthy »)")
        print(
            '  Invoke-RestMethod http://127.0.0.1:8000/moi -Headers @{Authorization="Bearer <jeton>"}'
        )
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
