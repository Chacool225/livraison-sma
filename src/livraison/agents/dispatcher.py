"""Agent dispatcher : lance l'appel d'offres pour chaque commande et attribue au meilleur coût.

Les commandes arrivent dans `file_commandes` sous la forme (identifiant, (x, y)) ;
les résultats ressortent dans `sortie`. L'API (lot suivant) n'aura qu'à alimenter cette file.
"""

import asyncio
from dataclasses import dataclass

from spade.agent import Agent
from spade.behaviour import CyclicBehaviour
from spade.message import Message

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
from livraison.config import parametres
from livraison.modele.cout import Offre, meilleure_offre


@dataclass
class Resultat:
    commande_id: str
    destination: tuple[int, int]
    offres: list[Offre]
    gagnant: str | None
    livree: bool


class DispatcherAgent(Agent):
    def __init__(
        self,
        jid,
        mot_de_passe,
        livreurs: list[str],
        delai_offres=3.0,
        delai_livraison=5.0,
        **options,
    ):
        super().__init__(jid, mot_de_passe, **options)
        self.livreurs = livreurs  # noms locaux : "l1", "l2"...
        self.delai_offres = delai_offres  # temps laissé aux livreurs pour répondre
        self.delai_livraison = delai_livraison
        self.file_commandes: asyncio.Queue = asyncio.Queue()
        self.sortie: asyncio.Queue = asyncio.Queue()

    class Orchestrer(CyclicBehaviour):
        """Traite les commandes une par une avec le protocole Contract Net."""

        async def run(self):
            try:
                cid, destination = await asyncio.wait_for(
                    self.agent.file_commandes.get(), timeout=1
                )
            except TimeoutError:
                return
            resultat = await self.attribuer(cid, tuple(destination))
            await self.agent.sortie.put(resultat)

        async def _envoyer(self, nom, performative, cid, **corps):
            msg = Message(to=parametres.jid(nom))
            msg.set_metadata("performative", performative)
            msg.thread = cid
            msg.body = encoder(**corps)
            await self.send(msg)

        async def attribuer(self, cid, destination) -> Resultat:
            agent = self.agent
            boucle = asyncio.get_running_loop()

            # 1. Appel d'offres à tous les livreurs
            for nom in agent.livreurs:
                await self._envoyer(nom, CFP, cid, destination=list(destination))

            # 2. Collecte des réponses, jusqu'à la dernière ou à l'échéance
            offres, refus = [], 0
            echeance = boucle.time() + agent.delai_offres
            while len(offres) + refus < len(agent.livreurs):
                reste = echeance - boucle.time()
                if reste <= 0:
                    break
                msg = await self.receive(timeout=reste)
                if msg is None:
                    break
                if msg.thread != cid:
                    continue  # réponse tardive d'une commande précédente
                performative = msg.get_metadata("performative")
                if performative == PROPOSE:
                    offres.append(Offre(msg.sender.local, decoder(msg.body)["cout"]))
                elif performative == REFUSE:
                    refus += 1

            if not offres:
                return Resultat(cid, destination, [], None, False)

            # 3. Choix : coût minimal ; égalité -> ordre alphabétique (résultat reproductible)
            offres.sort(key=lambda o: o.livreur)
            gagnante = meilleure_offre(offres)

            # 4. Acceptation du gagnant, rejet des autres
            for offre in offres:
                performative = ACCEPT if offre is gagnante else REJECT
                await self._envoyer(offre.livreur, performative, cid)

            # 5. Attente de la confirmation de livraison
            livree = False
            echeance = boucle.time() + agent.delai_livraison
            while True:
                reste = echeance - boucle.time()
                if reste <= 0:
                    break
                msg = await self.receive(timeout=reste)
                if msg is None:
                    break
                if msg.thread != cid:
                    continue
                performative = msg.get_metadata("performative")
                if performative == INFORM:
                    livree = True
                    break
                if performative == FAILURE:
                    break
            return Resultat(cid, destination, offres, gagnante.livreur, livree)

    async def setup(self):
        self.add_behaviour(self.Orchestrer())
