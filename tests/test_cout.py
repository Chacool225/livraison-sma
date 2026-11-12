"""Non-régression : le scénario de base du TP JADE (six colis, trois livreurs)."""

from livraison.modele.cout import Offre, cout_grille, meilleure_offre

ATTENDU = [
    ((0, 3), (3, 9, 9), "L1"),
    ((8, 4), (9, 2, 6), "L2"),
    ((0, 5), (2, 9, 7), "L1"),
    ((5, 8), (8, 7, 1), "L3"),
    ((9, 3), (11, 2, 9), "L2"),
    ((2, 2), (5, 8, 9), "L1"),
]


def test_scenario_de_base_du_tp():
    positions = {"L1": (1, 1), "L2": (8, 2), "L3": (5, 7)}
    for destination, couts, gagnant in ATTENDU:
        offres = [Offre(nom, cout_grille(pos, destination, 0)) for nom, pos in positions.items()]
        assert tuple(o.cout for o in offres) == couts
        choisie = meilleure_offre(offres)
        assert choisie.livreur == gagnant
        positions[gagnant] = destination  # le livreur se trouve désormais à la destination


def test_la_charge_penalise():
    assert cout_grille((0, 0), (1, 1), 2) == 8


def test_aucune_offre():
    assert meilleure_offre([]) is None
