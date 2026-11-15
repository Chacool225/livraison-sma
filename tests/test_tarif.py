import pytest

from livraison.modele.tarif import calculer_prix


@pytest.mark.parametrize(
    ("distance_m", "attendu"),
    [
        (0, 500),  # la part fixe seule
        (1000, 650),  # 500 + 150
        (1010, 700),  # 651,5 -> arrondi par excès à 700
        (5000, 1250),  # 500 + 750
        (8300, 1750),  # 500 + 1245 = 1745 -> 1750
    ],
)
def test_prix_avec_les_tarifs_de_depart(distance_m, attendu):
    assert calculer_prix(distance_m, tarif_fixe=500, tarif_km=150) == attendu


def test_le_prix_ne_diminue_jamais_quand_la_distance_augmente():
    prix = [calculer_prix(d, 500, 150) for d in range(0, 20_000, 137)]
    assert prix == sorted(prix)


def test_arrondi_personnalise_et_distance_invalide():
    assert calculer_prix(1000, 500, 150, arrondi=100) == 700
    with pytest.raises(ValueError):
        calculer_prix(-1, 500, 150)
