"""Lieux d'Abidjan proposés dans les formulaires (centres approximatifs des communes).

Il n'y a pas de service de recherche d'adresses : on choisit une commune, on précise l'adresse en
texte libre, ou on saisit des coordonnées pour un autre endroit. Coordonnées en (longitude, latitude).
"""

AUTRE = "autre"

LIEUX: dict[str, tuple[float, float]] = {
    "Plateau": (-4.0197, 5.3236),
    "Adjamé": (-4.0230, 5.3560),
    "Attécoubé": (-4.0400, 5.3350),
    "Yopougon": (-4.0900, 5.3400),
    "Abobo": (-4.0200, 5.4200),
    "Cocody": (-3.9870, 5.3480),
    "Angré": (-3.9850, 5.3900),
    "Riviera": (-3.9500, 5.3600),
    "Bingerville": (-3.8900, 5.3550),
    "Treichville": (-4.0050, 5.2950),
    "Marcory": (-3.9780, 5.3000),
    "Koumassi": (-3.9500, 5.2950),
    "Port-Bouët": (-3.9300, 5.2500),
}


def coordonnees(nom: str) -> tuple[float, float]:
    return LIEUX[nom]
