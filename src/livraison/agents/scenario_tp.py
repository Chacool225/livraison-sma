"""Rejoue le scénario du TP JADE (6 colis, 3 livreurs) avec les vrais agents SPADE.

Prérequis : `spade run` dans un autre terminal.
Lancement : python -m livraison.agents.scenario_tp
"""

import asyncio

from livraison.agents.dispatcher import DispatcherAgent
from livraison.agents.livreur import LivreurAgent
from livraison.config import parametres

POSITIONS = {"l1": (1, 1), "l2": (8, 2), "l3": (5, 7)}
COLIS = [(0, 3), (8, 4), (0, 5), (5, 8), (9, 3), (2, 2)]
ATTENDU = ["l1", "l2", "l1", "l3", "l2", "l1"]


async def main() -> bool:
    mdp, port = parametres.xmpp_mot_de_passe_agents, parametres.xmpp_port
    livreurs = {
        nom: LivreurAgent(parametres.jid(nom), mdp, pos, port=port)
        for nom, pos in POSITIONS.items()
    }
    dispatcher = DispatcherAgent(parametres.jid("dispatcher"), mdp, list(livreurs), port=port)

    agents = [*livreurs.values(), dispatcher]
    for agent in agents:  # les livreurs d'abord : ils doivent écouter avant le premier appel
        await agent.start(auto_register=True)
    try:
        for i, destination in enumerate(COLIS, start=1):
            await dispatcher.file_commandes.put((f"colis-{i}", destination))

        obtenus = []
        for _ in COLIS:
            r = await asyncio.wait_for(dispatcher.sortie.get(), timeout=30)
            offres = " ".join(f"{o.livreur.upper()}={o.cout}" for o in r.offres)
            print(f"{r.commande_id} {r.destination}: {offres} -> {r.gagnant} livré={r.livree}")
            obtenus.append(r.gagnant)

        ok = obtenus == ATTENDU
        print("OK : même attribution que le TP." if ok else f"ÉCART : obtenu {obtenus}")
        return ok
    finally:
        for agent in agents:
            await agent.stop()


if __name__ == "__main__":
    import spade

    resultat = []

    async def lancer():
        resultat.append(await main())

    spade.run(lancer())
    raise SystemExit(0 if resultat and resultat[0] else 1)
