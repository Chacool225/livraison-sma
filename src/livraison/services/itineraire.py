"""Durées de trajet. Les agents ne dépendent que de l'interface `Itineraire`.

Deux implémentations, combinables :

- `ItineraireDroiteLigne` : distance à vol d'oiseau, majorée, divisée par une vitesse moyenne selon
  le véhicule. Aucune dépendance : sert d'approximation et de solution de secours.
- `ItineraireOSRM` : durée de trajet réelle sur le réseau routier, calculée par le moteur OSRM.
- `ItineraireAvecRepli` : OSRM d'abord ; si le moteur est indisponible, la ligne droite, de sorte
  que le service continue de fonctionner (en précision réduite) au lieu de tomber en panne.
"""

import logging
import time
from collections import OrderedDict
from typing import Protocol

import httpx

from livraison.modele.geo import Point, distance_m

journal = logging.getLogger("livraison.itineraire")

VITESSES_KMH = {"velo": 15.0, "moto": 30.0, "voiture": 25.0}  # moyennes urbaines, à ajuster
VITESSE_REFERENCE_KMH = VITESSES_KMH["voiture"]  # OSRM est interrogé avec le profil voiture
FACTEUR_SINUOSITE = 1.3  # une route est plus longue que la ligne droite
FACTEUR_VEHICULE = {v: VITESSE_REFERENCE_KMH / kmh for v, kmh in VITESSES_KMH.items()}


class ErreurItineraire(Exception):
    """Le moteur d'itinéraires n'a pas pu répondre (injoignable, erreur, aucun chemin)."""


class Itineraire(Protocol):
    async def duree_s(self, depart: Point, arrivee: Point, vehicule: str) -> float: ...


class ItineraireDroiteLigne:
    async def duree_s(self, depart: Point, arrivee: Point, vehicule: str) -> float:
        vitesse_ms = VITESSES_KMH.get(vehicule, VITESSES_KMH["moto"]) / 3.6
        return distance_m(depart, arrivee) * FACTEUR_SINUOSITE / vitesse_ms


class ItineraireOSRM:
    """Durée réelle d'après OSRM (service `route`).

    OSRM ne propose ici que le profil voiture : la durée obtenue est corrigée selon la vitesse
    moyenne du véhicule par rapport à la voiture (une moto va plus vite, un vélo moins vite).
    Les durées OSRM sont celles d'une circulation fluide ; le trafic n'est pas modélisé.
    Les résultats sont mis en cache : le réseau routier ne change pas d'une minute à l'autre.
    """

    def __init__(
        self,
        url: str,
        *,
        delai_s: float = 2.0,
        taille_cache: int = 20_000,
        client: httpx.AsyncClient | None = None,
    ):
        self.url = url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=delai_s)
        self._cache: OrderedDict[tuple, float] = OrderedDict()
        self._taille_cache = taille_cache

    async def duree_s(self, depart: Point, arrivee: Point, vehicule: str) -> float:
        cle = (round(depart[0], 5), round(depart[1], 5), round(arrivee[0], 5), round(arrivee[1], 5))
        if cle in self._cache:
            self._cache.move_to_end(cle)
            duree_voiture = self._cache[cle]
        else:
            duree_voiture = await self._interroger(depart, arrivee)
            self._cache[cle] = duree_voiture
            if len(self._cache) > self._taille_cache:
                self._cache.popitem(last=False)
        return duree_voiture * FACTEUR_VEHICULE.get(vehicule, FACTEUR_VEHICULE["moto"])

    async def _interroger(self, depart: Point, arrivee: Point) -> float:
        # OSRM attend « longitude,latitude », points séparés par « ; ».
        trajet = f"{depart[0]:.6f},{depart[1]:.6f};{arrivee[0]:.6f},{arrivee[1]:.6f}"
        try:
            reponse = await self._client.get(
                f"{self.url}/route/v1/driving/{trajet}", params={"overview": "false"}
            )
            reponse.raise_for_status()
            donnees = reponse.json()
        except (httpx.HTTPError, ValueError) as erreur:
            raise ErreurItineraire(f"OSRM injoignable ou en erreur : {erreur}") from erreur
        if donnees.get("code") != "Ok" or not donnees.get("routes"):
            raise ErreurItineraire(f"OSRM sans itinéraire : {donnees.get('code')}")
        return float(donnees["routes"][0]["duration"])

    async def fermer(self) -> None:
        await self._client.aclose()


class ItineraireAvecRepli:
    """Essaie le moteur principal ; en cas d'échec, utilise la solution de secours."""

    def __init__(self, principal: Itineraire, secours: Itineraire, silence_journal_s: float = 60):
        self.principal = principal
        self.secours = secours
        self.nb_replis = 0
        self._silence = silence_journal_s
        self._dernier_avertissement = float("-inf")

    async def duree_s(self, depart: Point, arrivee: Point, vehicule: str) -> float:
        try:
            return await self.principal.duree_s(depart, arrivee, vehicule)
        except ErreurItineraire as erreur:
            self.nb_replis += 1
            maintenant = time.monotonic()
            if maintenant - self._dernier_avertissement > self._silence:
                journal.warning("Repli sur la ligne droite : %s", erreur)
                self._dernier_avertissement = maintenant
            return await self.secours.duree_s(depart, arrivee, vehicule)


def creer_itineraire(mode: str, osrm_url: str) -> Itineraire:
    """« droite_ligne » (par défaut, sans service externe) ou « osrm » (avec repli automatique)."""
    if mode == "droite_ligne":
        return ItineraireDroiteLigne()
    if mode == "osrm":
        return ItineraireAvecRepli(ItineraireOSRM(osrm_url), ItineraireDroiteLigne())
    raise ValueError(f"ITINERAIRE inconnu : {mode!r} (attendu : droite_ligne ou osrm)")
