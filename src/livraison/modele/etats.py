"""Cycle de vie d'une commande (cahier des charges, § 3.4) : transitions autorisées."""

from livraison.db.modeles import EtatCommande as E

TRANSITIONS: dict[E, set[E]] = {
    E.CREEE: {E.VALIDEE, E.ANNULEE},
    E.VALIDEE: {E.EN_RECHERCHE, E.ANNULEE},
    E.EN_RECHERCHE: {E.ATTRIBUEE, E.ANNULEE},
    # Avant l'enlèvement, un incident renvoie la commande en recherche (réattribution).
    E.ATTRIBUEE: {E.ENLEVEE, E.EN_RECHERCHE, E.ANNULEE},
    # Colis en main : plus de réattribution automatique, on passe par le répartiteur.
    E.ENLEVEE: {E.EN_LIVRAISON, E.LIVREE, E.ECHEC_LIVRAISON},
    E.EN_LIVRAISON: {E.LIVREE, E.ECHEC_LIVRAISON},
    E.LIVREE: {E.CLOTUREE, E.LITIGE},
    E.CLOTUREE: {E.LITIGE},
    E.ECHEC_LIVRAISON: {E.EN_RECHERCHE, E.ANNULEE, E.LITIGE},
    E.ANNULEE: set(),
    E.LITIGE: {E.CLOTUREE},
}


class TransitionInterdite(Exception):
    pass


def verifier_transition(actuel: E, suivant: E) -> None:
    if suivant not in TRANSITIONS[actuel]:
        raise TransitionInterdite(f"Passage interdit : {actuel.value} -> {suivant.value}")
