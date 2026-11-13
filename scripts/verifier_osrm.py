"""Vérifie le moteur d'itinéraires réel (OSRM) et le compare à l'approximation en ligne droite.

Usage : python scripts/verifier_osrm.py
Prérequis : scripts/preparer_osrm.ps1 exécuté, puis `docker compose --profile itineraires up -d`.
"""

import asyncio
import sys

from livraison.config import parametres
from livraison.services.itineraire import (
    ErreurItineraire,
    ItineraireDroiteLigne,
    ItineraireOSRM,
)

# Quelques trajets d'Abidjan (longitude, latitude).
TRAJETS = {
    "Plateau -> Cocody": ((-4.0197, 5.3236), (-3.9870, 5.3480)),
    "Plateau -> Marcory": ((-4.0197, 5.3236), (-3.9780, 5.3000)),
    "Yopougon -> Plateau": ((-4.0900, 5.3400), (-4.0197, 5.3236)),
    "Abobo -> Adjamé": ((-4.0200, 5.4200), (-4.0230, 5.3560)),
}


async def main() -> int:
    osrm = ItineraireOSRM(parametres.osrm_url)
    approx = ItineraireDroiteLigne()
    print(f"Moteur : {parametres.osrm_url}\n")
    print(f"{'Trajet':<24}{'OSRM (min)':>12}{'Ligne droite (min)':>22}{'Rapport':>10}")
    try:
        for nom, (a, b) in TRAJETS.items():
            reel = await osrm.duree_s(a, b, "voiture") / 60
            estime = await approx.duree_s(a, b, "voiture") / 60
            print(f"{nom:<24}{reel:>12.1f}{estime:>22.1f}{reel / estime:>10.2f}")
            if not 0.3 < reel / estime < 3:
                print("[KO] Écart anormal avec l'approximation : carte ou profil à vérifier.")
                return 1
    except ErreurItineraire as erreur:
        print(f"[KO] {erreur}")
        print("Le moteur est-il lancé ? docker compose --profile itineraires up -d")
        return 1
    finally:
        await osrm.fermer()
    print("\n[OK] OSRM répond avec des durées cohérentes.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
