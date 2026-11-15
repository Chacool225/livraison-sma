"""Démonstration du parcours complet : un client commande, un livreur reçoit la course, l'accepte,
enlève le colis et le livre avec le code du destinataire.

Prérequis (trois terminaux) :
    1. spade run --memory                             (serveur XMPP des agents)
    2. uvicorn livraison.api.main:app                 (l'API démarre les agents)
    3. python scripts\\creer_admin.py "07 00 00 00 00" "Admin"   (une seule fois)
Usage :
    python scripts\\demo_parcours.py [--url http://127.0.0.1:8000] [--admin "07 00 00 00 00"]
"""

import argparse
import random
import sys
import time

import httpx

PLATEAU = {"adresse": "Plateau, Abidjan", "longitude": -4.0267, "latitude": 5.32}
COCODY = {"adresse": "Cocody, Abidjan", "longitude": -3.987, "latitude": 5.36}
PRES_DU_PLATEAU = {"longitude": -4.025, "latitude": 5.321}


def etape(texte: str) -> None:
    print(f"\n>> {texte}")


def attendre(fonction, libelle: str, timeout: float = 30):
    debut = time.time()
    while time.time() - debut < timeout:
        valeur = fonction()
        if valeur:
            return valeur
        time.sleep(0.3)
    raise SystemExit(f"[KO] Délai dépassé : {libelle}")


def main() -> int:
    analyseur = argparse.ArgumentParser()
    analyseur.add_argument("--url", default="http://127.0.0.1:8000")
    analyseur.add_argument("--admin", default="07 00 00 00 00")
    args = analyseur.parse_args()
    http = httpx.Client(base_url=args.url, timeout=15)

    def connecter(telephone: str, role: str = "client", nom: str | None = None) -> dict:
        code = http.post("/auth/demander-code", json={"telephone": telephone}).json()["code_dev"]
        r = http.post(
            "/auth/verifier-code",
            json={"telephone": telephone, "code": code, "role": role, "nom": nom},
        )
        r.raise_for_status()
        return {
            "jeton": {"Authorization": f"Bearer {r.json()['access_token']}"},
            "compte": r.json()["utilisateur"],
        }

    try:
        sante = http.get("/sante").json()
    except httpx.HTTPError as erreur:
        print(f"[KO] Serveur injoignable ({erreur}). Lancer : uvicorn livraison.api.main:app")
        return 1
    if not sante["agents"]:
        print(
            "[KO] Les agents ne tournent pas : lancer d'abord `spade run --memory`, puis redémarrer l'API."
        )
        return 1

    etape("1. Un livreur s'inscrit et dépose son dossier ; l'administrateur le valide")
    livreur = connecter(f"07{random.randint(10_000_000, 99_999_999)}", "livreur", "Moussa Livreur")
    http.put(
        "/livreurs/moi/dossier",
        json={"type_vehicule": "moto", "capacite_courses": 2},
        headers=livreur["jeton"],
    ).raise_for_status()
    admin = connecter(args.admin)
    http.post(
        f"/admin/livreurs/{livreur['compte']['id']}/validation",
        json={"decision": "valide"},
        headers=admin["jeton"],
    ).raise_for_status()
    print("   dossier validé")

    etape("2. Le livreur se met en ligne, près du Plateau")
    http.post(
        "/livreurs/moi/en-ligne", json=PRES_DU_PLATEAU, headers=livreur["jeton"]
    ).raise_for_status()
    agents = http.get("/admin/agents", headers=admin["jeton"]).json()
    print(f"   {len(agents)} livreur(s) en ligne dans l'annuaire des agents")

    etape("3. Un client commande une livraison Plateau -> Cocody")
    client = connecter(f"07{random.randint(10_000_000, 99_999_999)}", "client", "Awa Client")
    r = http.post(
        "/commandes",
        json={
            "enlevement": PLATEAU,
            "livraison": COCODY,
            "taille_colis": "petit",
            "destinataire_nom": "Koffi",
            "destinataire_telephone": "07 11 22 33 44",
        },
        headers=client["jeton"],
    )
    r.raise_for_status()
    commande = r.json()
    print(
        f"   commande n°{commande['numero']} : {commande['prix']} F ({commande['distance_m'] / 1000:.1f} km)"
    )
    print(f"   code de remise à donner au destinataire : {commande['code_remise']}")
    cid = commande["id"]

    etape("4. Les agents cherchent un livreur : il reçoit la proposition")
    proposition = attendre(
        lambda: (
            http.get("/livreurs/moi/courses", headers=livreur["jeton"]).json()["propositions"]
            or [None]
        )[0],
        "aucune proposition reçue par le livreur",
    )
    print(
        f"   proposition : {proposition['adresse_enlevement']} -> {proposition['adresse_livraison']}, "
        f"{proposition['prix']} F, à confirmer sous {proposition['expire_dans_s']:.0f} s"
    )

    etape("5. Le livreur accepte")
    http.post(
        f"/livreurs/moi/courses/{cid}/reponse", json={"accepte": True}, headers=livreur["jeton"]
    ).raise_for_status()

    def detail():
        return http.get(f"/commandes/{cid}", headers=client["jeton"]).json()

    attendre(lambda: detail()["etat"] == "attribuee", "la commande n'a pas été attribuée")
    d = detail()
    print(
        f"   le client voit : état « {d['etat']} », livreur {d['livreur']['nom']} ({d['livreur']['type_vehicule']})"
    )

    etape("6. Le livreur se déplace, enlève le colis puis part livrer")
    http.put(
        "/livreurs/moi/position",
        json={"longitude": -4.0267, "latitude": 5.32, "precision_m": 8},
        headers=livreur["jeton"],
    ).raise_for_status()
    for nom, code in (("enlevee", None), ("en_livraison", None)):
        http.post(
            f"/livreurs/moi/courses/{cid}/etape",
            json={"etape": nom, "code": code},
            headers=livreur["jeton"],
        ).raise_for_status()
        attendre(lambda nom=nom: detail()["etat"] == nom, f"état {nom} non atteint")
        print(f"   état : {nom}")

    etape("7. Livraison : le destinataire donne son code")
    http.post(
        f"/livreurs/moi/courses/{cid}/etape",
        json={"etape": "livree", "code": commande["code_remise"]},
        headers=livreur["jeton"],
    ).raise_for_status()
    attendre(lambda: detail()["etat"] == "livree", "livraison non enregistrée")
    print(f"   état : livree ({detail()['livree_le']})")

    print("\n[OK] Parcours complet réussi : commande -> attribution -> enlèvement -> livraison.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
