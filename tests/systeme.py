"""Banc d'essai des agents : un annuaire, un dispatcher et des livreurs réels (SPADE + XMPP),
branchés sur la vraie base de test. Aide à écrire des scénarios lisibles."""

import asyncio
import itertools
import uuid

from geoalchemy2.elements import WKTElement
from sqlalchemy import select

from livraison.agents.agent_dispatcher import DispatcherAgent, Resultat
from livraison.agents.agent_livreur import LivreurAgent, confirmer_automatiquement
from livraison.agents.annuaire import AnnuaireAgent
from livraison.config import parametres
from livraison.db.modeles import (
    Commande,
    EtatCommande,
    Evenement,
    Livreur,
    ModePaiement,
    Offre,
    Role,
    StatutValidation,
    TailleColis,
    TypeVehicule,
    Utilisateur,
)

_numeros = itertools.count(1)
ENLEVEMENT = (-4.0267, 5.3200)  # Plateau
LIVRAISON = (-3.9870, 5.3600)  # Cocody
A = (-4.0250, 5.3210)  # ~0,2 km de l'enlèvement
B = (-4.0100, 5.3300)  # ~2 km
C = (-3.9800, 5.3700)  # ~7,6 km : hors du rayon initial de 3 km
REGLAGES_RAPIDES = {"delai_offres_s": 1.0, "delai_confirmation_s": 2.0, "delai_relance_s": 0.3}


def _wkt(point) -> WKTElement:
    return WKTElement(f"POINT({point[0]} {point[1]})", srid=4326)


class Systeme:
    def __init__(self, fabrique, reglages: dict | None = None):
        self.fabrique = fabrique
        self.suffixe = uuid.uuid4().hex[:6]
        port, mdp = parametres.xmpp_port, parametres.xmpp_mot_de_passe_agents
        self._port, self._mdp = port, mdp
        self.annuaire = AnnuaireAgent(self._jid("annuaire"), mdp, port=port)
        self.dispatcher = DispatcherAgent(
            self._jid("dispatcher"),
            mdp,
            annuaire_jid=self._jid("annuaire"),
            fabrique_sessions=fabrique,
            reglages={**REGLAGES_RAPIDES, **(reglages or {})},
            port=port,
        )
        self.livreurs: dict[str, LivreurAgent] = {}
        self.client_id: uuid.UUID | None = None

    def _jid(self, nom: str) -> str:
        return parametres.jid(f"{nom}-{self.suffixe}")

    async def demarrer(self) -> None:
        await self.annuaire.start(auto_register=True)
        await self.dispatcher.start(auto_register=True)
        async with self.fabrique() as session:
            client = Utilisateur(telephone=f"+22501{next(_numeros):08d}", role=Role.CLIENT)
            session.add(client)
            await session.commit()
            self.client_id = client.id

    async def arreter(self) -> None:
        for agent in (*self.livreurs.values(), self.dispatcher, self.annuaire):
            await agent.stop()

    # ------------------------------------------------------------------ construction
    async def livreur(
        self,
        nom,
        position,
        *,
        capacite=3,
        taille="moyen",
        note=4.0,
        vehicule="moto",
        confirmateur=confirmer_automatiquement,
        en_ligne=True,
    ) -> LivreurAgent:
        async with self.fabrique() as session:
            utilisateur = Utilisateur(telephone=f"+22507{next(_numeros):08d}", role=Role.LIVREUR)
            session.add(utilisateur)
            await session.flush()
            session.add(
                Livreur(
                    utilisateur_id=utilisateur.id,
                    type_vehicule=TypeVehicule(vehicule),
                    capacite_courses=capacite,
                    taille_colis_max=TailleColis(taille),
                    statut_validation=StatutValidation.VALIDE,
                )
            )
            await session.commit()
            livreur_id = str(utilisateur.id)
        agent = LivreurAgent(
            self._jid(nom),
            self._mdp,
            livreur_id=livreur_id,
            annuaire_jid=self._jid("annuaire"),
            dispatcher_jid=self._jid("dispatcher"),
            position=position,
            vehicule=vehicule,
            capacite=capacite,
            taille_max=taille,
            note=note,
            confirmateur=confirmateur,
            port=self._port,
        )
        await agent.start(auto_register=True)
        self.livreurs[nom] = agent
        if en_ligne:
            await agent.passer_en_ligne()
        return agent

    def id(self, nom: str) -> str:
        return self.livreurs[nom].livreur_id

    async def attendre_annuaire(self, n: int, timeout=10) -> None:
        async with asyncio.timeout(timeout):
            while len(self.annuaire.entrees) != n:
                await asyncio.sleep(0.05)

    async def commande(self, enlevement, livraison, taille="petit") -> uuid.UUID:
        async with self.fabrique() as session:
            commande = Commande(
                client_id=self.client_id,
                adresse_enlevement="A",
                point_enlevement=_wkt(enlevement),
                adresse_livraison="B",
                point_livraison=_wkt(livraison),
                taille_colis=TailleColis(taille),
                prix=1500,
                mode_paiement=ModePaiement.ESPECES,
                etat=EtatCommande.VALIDEE,
            )
            session.add(commande)
            await session.commit()
            return commande.id

    async def soumettre(self, *commandes_ids) -> None:
        for cid in commandes_ids:
            await self.dispatcher.soumettre(cid)

    async def resultats(self, n: int, timeout=30) -> list[Resultat]:
        async with asyncio.timeout(timeout):
            return [await self.dispatcher.sortie.get() for _ in range(n)]

    # ------------------------------------------------------------------ lecture de la base
    async def lire(self, cid) -> Commande:
        async with self.fabrique() as session:
            return await session.get(Commande, cid)

    async def offres(self, cid) -> list[Offre]:
        async with self.fabrique() as session:
            return list(
                await session.scalars(
                    select(Offre).where(Offre.commande_id == cid).order_by(Offre.id)
                )
            )

    async def evenements(self, cid) -> list[str]:
        async with self.fabrique() as session:
            lignes = await session.scalars(
                select(Evenement.type).where(Evenement.commande_id == cid).order_by(Evenement.id)
            )
            return list(lignes)

    async def attendre_etat(self, cid, etat: EtatCommande, timeout=10) -> Commande:
        async with asyncio.timeout(timeout):
            while (commande := await self.lire(cid)).etat != etat:
                await asyncio.sleep(0.1)
            return commande
