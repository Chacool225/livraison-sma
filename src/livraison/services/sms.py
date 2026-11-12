"""Envoi de SMS. Pour l'instant, mode « console » : le message est écrit dans les journaux.

Brancher un vrai prestataire (opérateur ou agrégateur) revient à remplacer le corps de
`envoyer_sms`, sans toucher au reste de l'application.
"""

import logging

journal = logging.getLogger("livraison.sms")


async def envoyer_sms(telephone: str, message: str) -> None:
    journal.info("SMS (simulé) vers %s : %s", telephone, message)
