"""Agent Annuaire (« pages jaunes ») : connaît les livreurs en ligne et leur dernière position,
et renvoie au dispatcher ceux qui sont proches d'un point."""

import time
from dataclasses import dataclass

from spade.agent import Agent
from spade.behaviour import CyclicBehaviour

from livraison.agents.protocole import (
    CANCEL,
    INFORM_IF,
    INFORM_REF,
    QUERY_IF,
    QUERY_REF,
    SUBSCRIBE,
    decoder,
    encoder,
)
from livraison.modele.geo import Point, distance_m

ORDRE_TAILLES = {"petit": 0, "moyen": 1, "grand": 2}


@dataclass
class Entree:
    livreur_id: str
    jid: str
    vehicule: str
    taille_max: str
    position: Point
    mis_a_jour: float


class AnnuaireAgent(Agent):
    def __init__(self, jid, mot_de_passe, *, horloge=time.monotonic, **options):
        super().__init__(jid, mot_de_passe, **options)
        self.horloge = horloge
        self.entrees: dict[str, Entree] = {}

    def age_position_s(self, livreur_id: str) -> float | None:
        """Secondes écoulées depuis la dernière position reçue ; None si le livreur est absent."""
        entree = self.entrees.get(livreur_id)
        return None if entree is None else round(self.horloge() - entree.mis_a_jour, 2)

    def chercher(self, point: Point, rayon_m: float, taille: str, limite: int) -> list[dict]:
        """Livreurs en ligne dans le rayon, compatibles avec la taille du colis, du plus proche
        au plus éloigné."""
        trouves = []
        for e in self.entrees.values():
            if ORDRE_TAILLES[e.taille_max] < ORDRE_TAILLES[taille]:
                continue
            d = distance_m(e.position, point)
            if d <= rayon_m:
                trouves.append({"livreur_id": e.livreur_id, "jid": e.jid, "distance_m": round(d)})
        trouves.sort(key=lambda t: (t["distance_m"], t["livreur_id"]))
        return trouves[:limite]

    class Gerer(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=1)
            if msg is None:
                return
            annuaire = self.agent
            perf = msg.get_metadata("performative")
            corps = decoder(msg.body)
            jid = str(msg.sender.bare)
            if perf == SUBSCRIBE:
                annuaire.entrees[corps["livreur_id"]] = Entree(
                    livreur_id=corps["livreur_id"],
                    jid=jid,
                    vehicule=corps["vehicule"],
                    taille_max=corps["taille_max"],
                    position=tuple(corps["position"]),
                    mis_a_jour=annuaire.horloge(),
                )
            elif perf == CANCEL:
                annuaire.entrees.pop(corps["livreur_id"], None)
            elif perf == QUERY_IF:
                reponse = msg.make_reply()
                reponse.set_metadata("performative", INFORM_IF)
                reponse.body = encoder(
                    ages={i: annuaire.age_position_s(i) for i in corps["livreur_ids"]}
                )
                await self.send(reponse)
            elif perf == QUERY_REF:
                candidats = annuaire.chercher(
                    tuple(corps["point"]), corps["rayon_m"], corps["taille"], corps["limite"]
                )
                reponse = msg.make_reply()
                reponse.set_metadata("performative", INFORM_REF)
                reponse.body = encoder(candidats=candidats)
                await self.send(reponse)

    async def setup(self):
        self.add_behaviour(self.Gerer())
