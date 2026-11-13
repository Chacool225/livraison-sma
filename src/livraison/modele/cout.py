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


def cout_offre(
    duree_vers_enlevement_s: float, detour_s: float, charge: int, penalite: float
) -> float:
    """Coût d'une offre (cahier des charges, § 3.2), exprimé en minutes équivalentes :

        durée(position -> enlèvement) + durée du détour + pénalité x charge

    Le détour est le temps ajouté aux courses déjà acceptées ; la charge est le nombre de
    courses en cours. Plus le coût est bas, meilleure est l'offre.
    """
    return round((duree_vers_enlevement_s + detour_s) / 60 + penalite * charge, 2)
