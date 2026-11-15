"""Mise en forme des données pour l'affichage (en français)."""

from datetime import datetime

LIBELLES_ETAT = {
    "creee": "Créée",
    "validee": "Validée",
    "en_recherche": "Recherche d'un livreur",
    "attribuee": "Livreur en route vers l'enlèvement",
    "enlevee": "Colis enlevé",
    "en_livraison": "En cours de livraison",
    "livree": "Livrée",
    "cloturee": "Clôturée",
    "annulee": "Annulée",
    "echec_livraison": "Échec de livraison",
    "litige": "Litige",
}

# Avancement d'une commande, pour la barre de progression du client.
AVANCEMENT = {
    "creee": 0.05,
    "validee": 0.1,
    "en_recherche": 0.2,
    "attribuee": 0.45,
    "enlevee": 0.65,
    "en_livraison": 0.85,
    "livree": 1.0,
    "cloturee": 1.0,
}

ETATS_ANNULABLES = ("validee", "en_recherche", "attribuee")
ETATS_ACTIFS = ("validee", "en_recherche", "attribuee", "enlevee", "en_livraison")


def libelle_etat(etat: str) -> str:
    return LIBELLES_ETAT.get(etat, etat)


def avancement(etat: str) -> float:
    return AVANCEMENT.get(etat, 0.0)


def prix(montant: int | None) -> str:
    return "-" if montant is None else f"{montant:,}".replace(",", " ") + " F"


def distance(metres: float | None) -> str:
    return "-" if metres is None else f"{metres / 1000:.1f} km".replace(".", ",")


def duree(secondes: float | None) -> str:
    if secondes is None:
        return "-"
    minutes = max(1, round(secondes / 60))
    return f"{minutes} min" if minutes < 60 else f"{minutes // 60} h {minutes % 60:02d}"


def il_y_a(secondes: float | None) -> str:
    if secondes is None:
        return "position inconnue"
    return "à l'instant" if secondes < 5 else f"il y a {round(secondes)} s"


def heure(horodatage: str | None) -> str:
    if not horodatage:
        return "-"
    return datetime.fromisoformat(horodatage).astimezone().strftime("%d/%m %H:%M")
