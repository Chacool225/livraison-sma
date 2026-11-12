"""Agent livreur : répond aux appels d'offres avec son coût, exécute les livraisons gagnées."""

from spade.agent import Agent
from spade.behaviour import CyclicBehaviour
from spade.template import Template

from livraison.agents.protocole import (
    ACCEPT,
    CFP,
    FAILURE,
    INFORM,
    PROPOSE,
    REFUSE,
    REJECT,
    decoder,
    encoder,
)
from livraison.modele.cout import cout_grille


class LivreurAgent(Agent):
    def __init__(self, jid, mot_de_passe, position, charge_max=3, **options):
        super().__init__(jid, mot_de_passe, **options)
        self.position = tuple(position)
        self.charge = 0  # colis en cours (pénalise le coût de l'offre)
        self.charge_max = charge_max  # au-delà, le livreur refuse
        self.livraisons: list[tuple[int, int]] = []
        self._propositions: dict[str, tuple[int, int]] = {}  # commande -> destination proposée

    class RepondreAuxAppels(CyclicBehaviour):
        """CFP reçu -> calcule le coût et répond « propose » ou « refuse »."""

        async def run(self):
            msg = await self.receive(timeout=10)
            if msg is None:
                return
            livreur = self.agent
            destination = tuple(decoder(msg.body)["destination"])
            reponse = msg.make_reply()  # conserve le fil (thread) de la commande
            if livreur.charge >= livreur.charge_max:
                reponse.set_metadata("performative", REFUSE)
                reponse.body = encoder(raison="charge maximale atteinte")
            else:
                cout = cout_grille(livreur.position, destination, livreur.charge)
                livreur._propositions[msg.thread] = destination
                reponse.set_metadata("performative", PROPOSE)
                reponse.body = encoder(cout=cout)
            await self.send(reponse)

    class RecevoirAcceptation(CyclicBehaviour):
        """Offre retenue -> effectue la livraison puis informe le dispatcher."""

        async def run(self):
            msg = await self.receive(timeout=10)
            if msg is None:
                return
            livreur = self.agent
            destination = livreur._propositions.pop(msg.thread, None)
            reponse = msg.make_reply()
            if destination is None:
                reponse.set_metadata("performative", FAILURE)
                reponse.body = encoder(raison="proposition inconnue")
            else:
                # Version TP : la livraison est instantanée, le livreur se retrouve à destination.
                # (Le lot suivant ajoutera la durée réelle du trajet et la charge.)
                livreur.position = destination
                livreur.livraisons.append(destination)
                reponse.set_metadata("performative", INFORM)
                reponse.body = encoder(statut="livre")
            await self.send(reponse)

    class RecevoirRejet(CyclicBehaviour):
        """Offre non retenue -> on oublie la proposition."""

        async def run(self):
            msg = await self.receive(timeout=10)
            if msg is not None:
                self.agent._propositions.pop(msg.thread, None)

    async def setup(self):
        for comportement, performative in (
            (self.RepondreAuxAppels(), CFP),
            (self.RecevoirAcceptation(), ACCEPT),
            (self.RecevoirRejet(), REJECT),
        ):
            modele = Template()
            modele.set_metadata("performative", performative)
            self.add_behaviour(comportement, modele)
