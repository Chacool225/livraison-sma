"""Durées de trajet. Les agents ne dépendent que de l'interface `Itineraire`.

`ItineraireDroiteLigne` (distance à vol d'oiseau, majorée, divisée par une vitesse moyenne selon
le véhicule) est une approximation qui ne demande aucun service. Le moteur routier réel (OSRM) sera
une autre implémentation de la même interface.
"""

from typing import Protocol

from livraison.modele.geo import Point, distance_m

VITESSES_KMH = {"velo": 15.0, "moto": 30.0, "voiture": 25.0}  # moyennes urbaines, à ajuster
FACTEUR_SINUOSITE = 1.3  # une route est plus longue que la ligne droite


class Itineraire(Protocol):
    async def duree_s(self, depart: Point, arrivee: Point, vehicule: str) -> float: ...


class ItineraireDroiteLigne:
    async def duree_s(self, depart: Point, arrivee: Point, vehicule: str) -> float:
        vitesse_ms = VITESSES_KMH.get(vehicule, VITESSES_KMH["moto"]) / 3.6
        return distance_m(depart, arrivee) * FACTEUR_SINUOSITE / vitesse_ms
