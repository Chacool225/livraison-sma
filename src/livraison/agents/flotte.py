"""La flotte : fait vivre les agents dans le serveur et relie l'API (HTTP) à eux.

- L'Annuaire et le Dispatcher démarrent avec le serveur.
- Un livreur qui se met « en ligne » reçoit son propre agent ; « hors ligne », l'agent disparaît.
- Quand un agent livreur reçoit une course retenue, la proposition attend ici la réponse du livreur
  humain, donnée par un appel d'API (`repondre`), dans le délai de confirmation.
"""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from livraison.agents.agent_dispatcher import DispatcherAgent
from livraison.agents.agent_livreur import Course, LivreurAgent
from livraison.agents.annuaire import AnnuaireAgent
from livraison.config import parametres
from livraison.db.modeles import EtatCommande, Livreur, Position
from livraison.modele.geo import Point
from livraison.services import commandes
from livraison.services.itineraire import Itineraire, ItineraireDroiteLigne

journal = logging.getLogger("livraison.flotte")

ETAT_VERS_ETAPE = {
    EtatCommande.ATTRIBUEE: "attribuee",
    EtatCommande.ENLEVEE: "enlevee",
    EtatCommande.EN_LIVRAISON: "en_livraison",
}


class LivreurHorsLigne(Exception):
    pass


class CourseEnCours(Exception):
    """Le livreur a des courses ou des propositions en cours : il ne peut pas se déconnecter."""


@dataclass
class Proposition:
    commande_id: str
    enlevement: Point
    livraison: Point
    expire_le: float  # horloge murale (time.time)
    futur: asyncio.Future


class Flotte:
    def __init__(
        self,
        fabrique: async_sessionmaker[AsyncSession],
        *,
        reglages: dict | None = None,
        itineraire: Itineraire | None = None,
        suffixe: str = "",
    ):
        self.fabrique = fabrique
        self._suffixe = suffixe
        self.itineraire = itineraire or ItineraireDroiteLigne()
        port, mdp = parametres.xmpp_port, parametres.xmpp_mot_de_passe_agents
        self._port, self._mdp = port, mdp
        self.annuaire = AnnuaireAgent(self._jid("annuaire"), mdp, port=port)
        self.dispatcher = DispatcherAgent(
            self._jid("dispatcher"),
            mdp,
            annuaire_jid=self._jid("annuaire"),
            fabrique_sessions=fabrique,
            reglages=reglages,
            port=port,
        )
        self.livreurs: dict[str, LivreurAgent] = {}
        self.propositions: dict[tuple[str, str], Proposition] = {}

    def _jid(self, nom: str) -> str:
        return parametres.jid(f"{nom}-{self._suffixe}" if self._suffixe else nom)

    # ------------------------------------------------------------------ cycle de vie
    async def demarrer(self) -> None:
        await self.annuaire.start(auto_register=True)
        await self.dispatcher.start(auto_register=True)
        async with self.fabrique() as session:
            # Les agents des livreurs ont disparu avec l'ancien serveur : personne n'est en ligne.
            await session.execute(update(Livreur).values(en_ligne=False))
            await session.commit()
            a_reprendre = await commandes.a_reprendre(session)
        for commande_id in a_reprendre:  # recherches interrompues par le redémarrage
            await self.dispatcher.soumettre(commande_id)
        if a_reprendre:
            journal.info("%d commande(s) reprise(s) après redémarrage", len(a_reprendre))

    async def arreter(self) -> None:
        for agent in (*self.livreurs.values(), self.dispatcher, self.annuaire):
            await agent.stop()
        self.livreurs.clear()
        fermer = getattr(self.itineraire, "fermer", None)
        if fermer is not None:
            await fermer()

    # ------------------------------------------------------------------ livreurs
    def _confirmateur(self, livreur_id: str):
        async def confirmer(course: dict) -> bool:
            cid = course["commande_id"]
            proposition = Proposition(
                commande_id=cid,
                enlevement=course["enlevement"],
                livraison=course["livraison"],
                expire_le=time.time() + course["delai_confirmation_s"],
                futur=asyncio.get_running_loop().create_future(),
            )
            self.propositions[(livreur_id, cid)] = proposition
            try:
                return await proposition.futur  # l'agent coupe l'attente au bout du délai
            finally:
                self.propositions.pop((livreur_id, cid), None)

        return confirmer

    async def mettre_en_ligne(self, livreur: Livreur, position: Point) -> None:
        """Crée l'agent du livreur (s'il n'existe pas), l'inscrit à l'annuaire, restaure ses
        courses en cours. Peut être rappelée sans danger."""
        livreur_id = str(livreur.utilisateur_id)
        agent = self.livreurs.get(livreur_id)
        if agent is None:
            agent = LivreurAgent(
                self._jid(f"livreur-{livreur.utilisateur_id.hex}"),
                self._mdp,
                livreur_id=livreur_id,
                annuaire_jid=self._jid("annuaire"),
                dispatcher_jid=self._jid("dispatcher"),
                position=position,
                vehicule=livreur.type_vehicule.value,
                capacite=livreur.capacite_courses,
                taille_max=livreur.taille_colis_max.value,
                note=float(livreur.note) if livreur.note is not None else 0.0,
                itineraire=self.itineraire,
                confirmateur=self._confirmateur(livreur_id),
                port=self._port,
            )
            await agent.start(auto_register=True)
            self.livreurs[livreur_id] = agent
            await self._restaurer_courses(agent, livreur.utilisateur_id)
        await agent.mettre_a_jour_position(position)
        if not agent.en_ligne:
            await agent.passer_en_ligne()
        async with self.fabrique() as session:
            await session.execute(
                update(Livreur)
                .where(Livreur.utilisateur_id == livreur.utilisateur_id)
                .values(en_ligne=True)
            )
            await session.commit()

    async def _restaurer_courses(self, agent: LivreurAgent, utilisateur_id: uuid.UUID) -> None:
        """Un livreur qui se reconnecte (ou après un redémarrage du serveur) retrouve ses courses."""
        async with self.fabrique() as session:
            courses = await commandes.courses_du_livreur(session, utilisateur_id)
        for c in courses:
            agent.courses[c["commande_id"]] = Course(
                c["commande_id"], c["enlevement"], c["livraison"], ETAT_VERS_ETAPE[c["etat"]]
            )
            self.dispatcher.attributions[c["commande_id"]] = str(agent.jid)

    async def mettre_hors_ligne(self, utilisateur_id: uuid.UUID) -> None:
        livreur_id = str(utilisateur_id)
        agent = self.livreurs.get(livreur_id)
        if agent is None:
            return
        if agent.charge or any(cle[0] == livreur_id for cle in self.propositions):
            raise CourseEnCours
        await agent.passer_hors_ligne()
        await agent.stop()
        self.livreurs.pop(livreur_id, None)
        async with self.fabrique() as session:
            await session.execute(
                update(Livreur)
                .where(Livreur.utilisateur_id == utilisateur_id)
                .values(en_ligne=False)
            )
            await session.commit()

    async def enregistrer_position(
        self, utilisateur_id: uuid.UUID, point: Point, precision_m: float | None
    ) -> None:
        agent = self.livreurs.get(str(utilisateur_id))
        if agent is None:
            raise LivreurHorsLigne
        await agent.mettre_a_jour_position(point)
        async with self.fabrique() as session:
            from geoalchemy2.elements import WKTElement

            session.add(
                Position(
                    livreur_id=utilisateur_id,
                    point=WKTElement(f"POINT({point[0]} {point[1]})", srid=4326),
                    precision_m=precision_m,
                )
            )
            await session.commit()

    async def signaler(
        self, utilisateur_id: uuid.UUID, commande_id: str, etape: str, motif: str | None
    ):
        agent = self.livreurs.get(str(utilisateur_id))
        if agent is None:
            raise LivreurHorsLigne
        await agent.signaler(commande_id, etape, motif)

    # ------------------------------------------------------------------ propositions
    def propositions_de(self, utilisateur_id: uuid.UUID) -> list[Proposition]:
        livreur_id = str(utilisateur_id)
        propositions = [p for (lid, _), p in self.propositions.items() if lid == livreur_id]
        return sorted(propositions, key=lambda p: p.expire_le)

    def repondre(self, utilisateur_id: uuid.UUID, commande_id: str, accepte: bool) -> bool:
        """Réponse du livreur humain. Faux si la proposition n'existe plus (expirée, annulée)."""
        proposition = self.propositions.get((str(utilisateur_id), commande_id))
        if proposition is None or proposition.futur.done():
            return False
        proposition.futur.set_result(accepte)
        return True

    # ------------------------------------------------------------------ commandes
    async def soumettre(self, commande_id: uuid.UUID) -> None:
        await self.dispatcher.soumettre(commande_id)

    async def annuler(self, commande_id: uuid.UUID) -> None:
        """Annulation par le client : retire la proposition en cours et prévient le livreur."""
        cid = str(commande_id)
        for (_, c), proposition in list(self.propositions.items()):
            if c == cid and not proposition.futur.done():
                proposition.futur.set_result(False)
        await self.dispatcher.annuler(commande_id)

    def livreurs_en_ligne(self) -> list[dict]:
        return [
            {
                "livreur_id": e.livreur_id,
                "position": e.position,
                "age_position_s": self.annuaire.age_position_s(e.livreur_id),
                "vehicule": e.vehicule,
            }
            for e in self.annuaire.entrees.values()
        ]
