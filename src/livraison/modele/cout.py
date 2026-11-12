"""Calcul du coût d'une offre et choix de la meilleure offre.

La version « grille » reprend la formule du TP JADE et sert de test de non-régression.
La version « itinéraire réel » (durées fournies par le moteur d'itinéraires) viendra au lot 2.
"""

from dataclasses import dataclass

PENALITE_CHARGE = 3


@dataclass(frozen=True)
class Offre:
    livreur: str
    cout: float


def cout_grille(position: tuple[int, int], destination: tuple[int, int], charge: int) -> int:
    """Formule du TP : distance de Manhattan + 3 x charge."""
    (x, y), (xd, yd) = position, destination
    return abs(xd - x) + abs(yd - y) + PENALITE_CHARGE * charge


def meilleure_offre(offres: list[Offre]) -> Offre | None:
    """Offre de coût minimal ; en cas d'égalité, la première reçue l'emporte."""
    return min(offres, key=lambda o: o.cout, default=None)
