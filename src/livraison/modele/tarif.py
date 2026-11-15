"""Prix d'une course : part fixe + part au kilomètre, arrondi par excès (francs CFA)."""

import math

ARRONDI_XOF = 50  # on facture par tranches de 50 F : plus simple à payer en espèces


def calculer_prix(
    distance_m: float, tarif_fixe: int, tarif_km: int, arrondi: int = ARRONDI_XOF
) -> int:
    """Prix = fixe + tarif au km x distance, arrondi au multiple supérieur de `arrondi`."""
    if distance_m < 0:
        raise ValueError("distance négative")
    brut = tarif_fixe + tarif_km * distance_m / 1000
    return int(math.ceil(brut / arrondi) * arrondi)
