"""Vocabulaire commun du protocole Contract Net (équivalent des performatives ACL de JADE).

Déroulement d'une commande (le fil `thread` du message = identifiant de la commande) :

    Dispatcher --cfp-------------> tous les livreurs      « qui peut livrer vers X ? »
    Livreur    --propose/refuse--> Dispatcher             « mon coût est N » / « je ne peux pas »
    Dispatcher --accept-proposal-> gagnant                « c'est toi »
    Dispatcher --reject-proposal-> les autres             « pas retenu »
    Gagnant    --inform/failure--> Dispatcher             « livré » / « échec »
"""

import json

CFP = "cfp"
PROPOSE = "propose"
REFUSE = "refuse"
ACCEPT = "accept-proposal"
REJECT = "reject-proposal"
INFORM = "inform"
FAILURE = "failure"


def encoder(**champs) -> str:
    """Corps d'un message : un petit objet JSON."""
    return json.dumps(champs)


def decoder(corps: str | None) -> dict:
    return json.loads(corps) if corps else {}


# Dialogue avec l'Annuaire (pages jaunes des livreurs en ligne)
SUBSCRIBE = "subscribe"  # un livreur se déclare (ou met à jour sa position)
CANCEL = "cancel"  # un livreur se retire de l'annuaire
QUERY_REF = "query-ref"  # le dispatcher demande les livreurs proches
INFORM_REF = "inform-ref"  # réponse de l'annuaire
