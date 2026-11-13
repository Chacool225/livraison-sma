"""Agent dispatcher du lot 2 : appels d'offres simultanés, confirmation du livreur, relances,
réattribution après incident. Tout est tracé dans la base (états, offres, événements).

Fonctionnement d'une attribution (une « conversation » par commande, plusieurs en parallèle) :

    1. interroger l'Annuaire : livreurs en ligne dans le rayon
    2. appel d'offres (cfp) ; collecte des propositions et des refus
    3. classement : coût, puis meilleure note, puis identifiant (résultat reproductible)
    4. rejet des perdants, acceptation du meilleur, attente de la confirmation du livreur
    5. refus, silence ou aucune offre : on exclut le livreur / on élargit le rayon, et on recommence ;
       au bout du nombre maximal de tentatives, la commande est signalée au répartiteur.
"""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass

from spade.agent import Agent
from spade.behaviour import CyclicBehaviour
from spade.message import Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from livraison.agents.protocole import (
    ACCEPT,
    CANCEL,
    CFP,
    FAILURE,
    INFORM,
    INFORM_IF,
    INFORM_REF,
    PROPOSE,
    QUERY_IF,
    QUERY_REF,
    REFUSE,
    REJECT,
    decoder,
    encoder,
)
from livraison.db.modeles import EtatCommande, ResultatOffre
from livraison.services import commandes

journal = logging.getLogger("livraison.dispatcher")

ETAPES = {
    "enlevee": EtatCommande.ENLEVEE,
    "en_livraison": EtatCommande.EN_LIVRAISON,
    "livree": EtatCommande.LIVREE,
}
MARGE_CONFIRMATION_S = 3  # le dispatcher attend un peu plus longtemps que le livreur


@dataclass
class Resultat:
    commande_id: str
    etat: str  # "attribuee" | "non_attribuee" | "ignoree" | "erreur"
    livreur_id: str | None = None
    tentatives: int = 0


class DispatcherAgent(Agent):
    def __init__(
        self,
        jid,
        mot_de_passe,
        *,
        annuaire_jid: str,
        fabrique_sessions: async_sessionmaker[AsyncSession],
        reglages: dict | None = None,
        **options,
    ):
        super().__init__(jid, mot_de_passe, **options)
        self.annuaire_jid = annuaire_jid
        self.fabrique = fabrique_sessions
        self.reglages_forces = reglages or {}
        self.file_commandes: asyncio.Queue[uuid.UUID] = asyncio.Queue()
        self.sortie: asyncio.Queue[Resultat] = asyncio.Queue()
        self.conversations: dict[str, asyncio.Queue[Message]] = {}
        self.exclusions: dict[str, set[str]] = {}  # commande -> livreurs déjà essayés
        self.attributions: dict[str, str] = {}  # commande -> adresse du livreur qui l'a acceptée
        self._alertes_gps: set[str] = set()  # courses déjà signalées au répartiteur
        self._taches: set[asyncio.Task] = set()
        self._postier: DispatcherAgent.Routeur | None = None

    async def soumettre(self, commande_id: uuid.UUID) -> None:
        await self.file_commandes.put(commande_id)

    # ------------------------------------------------------------------ messages
    async def _envoyer(self, destinataire: str, performative: str, thread: str, **corps) -> None:
        msg = Message(to=destinataire)
        msg.set_metadata("performative", performative)
        msg.thread = thread
        msg.body = encoder(**corps)
        await self._postier.send(msg)

    async def _prochain(self, file: asyncio.Queue, echeance: float) -> Message | None:
        reste = echeance - time.monotonic()
        if reste <= 0:
            return None
        try:
            return await asyncio.wait_for(file.get(), timeout=reste)
        except TimeoutError:
            return None

    # ------------------------------------------------------------------ attribution
    async def attribuer(self, commande_id: uuid.UUID) -> Resultat:
        cid = str(commande_id)
        self.conversations[cid] = asyncio.Queue()
        try:
            resultat = await self._cycle(commande_id, cid)
        except Exception as erreur:  # noqa: BLE001 - une commande en erreur n'arrête pas les autres
            journal.exception("Attribution de %s en erreur", cid)
            async with self.fabrique() as session:
                await commandes.journaliser(
                    session,
                    commande_id,
                    "erreur_attribution",
                    str(self.jid),
                    {"erreur": repr(erreur)},
                )
            resultat = Resultat(cid, "erreur")
        finally:
            self.conversations.pop(cid, None)
        await self.sortie.put(resultat)
        return resultat

    async def _cycle(self, commande_id: uuid.UUID, cid: str) -> Resultat:
        auteur = str(self.jid)
        async with self.fabrique() as session:
            reglages = await commandes.lire_reglages(session, self.reglages_forces)
            commande = await commandes.charger(session, commande_id)
            if commande is None or commande.etat not in (
                EtatCommande.VALIDEE,
                EtatCommande.EN_RECHERCHE,
            ):
                return Resultat(cid, "ignoree")
            await commandes.marquer_en_recherche(session, commande_id, auteur)
            base = await commandes.derniere_tentative(session, commande_id)

        exclus = self.exclusions.setdefault(cid, set())
        rayon = reglages["rayon_recherche_initial_m"]
        tentatives_max = reglages["tentatives_attribution_max"]

        for essai in range(1, tentatives_max + 1):
            tentative = base + essai  # numéro de tour unique, qui continue après une réattribution
            async with self.fabrique() as session:
                await commandes.noter_rayon(session, commande_id, rayon, tentative)

            candidats = [
                c
                for c in await self._interroger_annuaire(cid, commande, rayon, reglages)
                if c["livreur_id"] not in exclus
            ]
            if not candidats:
                await self._tracer(
                    commande_id, "aucun_candidat", {"rayon_m": rayon, "tentative": tentative}
                )
                rayon += reglages["rayon_pas_elargissement_m"]
                await asyncio.sleep(reglages["delai_relance_s"])
                continue

            offres, refus = await self._appel_d_offres(
                cid, commande, candidats, rayon, tentative, reglages
            )
            async with self.fabrique() as session:
                await commandes.enregistrer_offres(session, commande_id, tentative, offres, refus)
            if not offres:
                await self._tracer(
                    commande_id, "aucune_offre", {"rayon_m": rayon, "tentative": tentative}
                )
                rayon += reglages["rayon_pas_elargissement_m"]
                await asyncio.sleep(reglages["delai_relance_s"])
                continue

            classement = sorted(offres, key=lambda o: (o["cout"], -o["note"], o["livreur_id"]))
            gagnant, perdants = classement[0], classement[1:]
            jids = {c["livreur_id"]: c["jid"] for c in candidats}
            for perdant in perdants:
                await self._envoyer(jids[perdant["livreur_id"]], REJECT, cid)
                async with self.fabrique() as session:
                    await commandes.resoudre_offre(
                        session,
                        commande_id,
                        perdant["livreur_id"],
                        tentative,
                        ResultatOffre.REJETEE,
                    )

            delai = reglages["delai_confirmation_s"]
            await self._envoyer(
                jids[gagnant["livreur_id"]], ACCEPT, cid, delai_confirmation_s=delai
            )
            reponse = await self._attendre_confirmation(
                cid, gagnant["livreur_id"], delai + MARGE_CONFIRMATION_S
            )
            async with self.fabrique() as session:
                if reponse == "confirme":
                    await commandes.attribuer_a(
                        session, commande_id, gagnant["livreur_id"], tentative, auteur
                    )
                    self.attributions[cid] = jids[gagnant["livreur_id"]]
                    return Resultat(cid, "attribuee", gagnant["livreur_id"], essai)
                resultat_offre = (
                    ResultatOffre.DECLINEE if reponse == "decline" else ResultatOffre.EXPIREE
                )
                await commandes.resoudre_offre(
                    session, commande_id, gagnant["livreur_id"], tentative, resultat_offre, reponse
                )
                await commandes.journaliser(
                    session,
                    commande_id,
                    "offre_non_confirmee",
                    auteur,
                    {"livreur_id": gagnant["livreur_id"], "raison": reponse},
                )
            exclus.add(gagnant["livreur_id"])  # on ne le sollicite plus pour cette commande

        await self._tracer(commande_id, "alerte_repartiteur", {"raison": "attribution_impossible"})
        return Resultat(cid, "non_attribuee", None, tentatives_max)

    async def _tracer(self, commande_id: uuid.UUID, type_: str, detail: dict) -> None:
        async with self.fabrique() as session:
            await commandes.journaliser(session, commande_id, type_, str(self.jid), detail)

    async def _interroger_annuaire(self, cid, commande, rayon, reglages) -> list[dict]:
        await self._envoyer(
            self.annuaire_jid,
            QUERY_REF,
            cid,
            point=list(commande.enlevement),
            rayon_m=rayon,
            taille=commande.taille.value,
            limite=reglages["candidats_max"],
        )
        file = self.conversations[cid]
        echeance = time.monotonic() + 5
        while (msg := await self._prochain(file, echeance)) is not None:
            if msg.get_metadata("performative") == INFORM_REF:
                return decoder(msg.body)["candidats"]
        return []

    async def _appel_d_offres(self, cid, commande, candidats, rayon, tentative, reglages):
        for c in candidats:
            await self._envoyer(
                c["jid"],
                CFP,
                cid,
                tour=tentative,
                enlevement=list(commande.enlevement),
                livraison=list(commande.livraison),
                taille=commande.taille.value,
                rayon_m=rayon,
                penalite_charge=reglages["penalite_charge"],
                age_max_position_s=reglages["age_max_position_s"],
            )
        attendus = {c["livreur_id"] for c in candidats}
        offres, refus = [], []
        file = self.conversations[cid]
        echeance = time.monotonic() + reglages["delai_offres_s"]
        while len(offres) + len(refus) < len(attendus):
            msg = await self._prochain(file, echeance)
            if msg is None:
                break
            corps = decoder(msg.body)
            if corps.get("tour") != tentative or corps.get("livreur_id") not in attendus:
                continue  # réponse tardive d'un tour précédent, ou d'un inconnu
            perf = msg.get_metadata("performative")
            if perf == PROPOSE:
                offres.append(corps)
            elif perf == REFUSE:
                refus.append(corps)
        return offres, refus

    async def _attendre_confirmation(self, cid: str, livreur_id: str, delai_s: float) -> str:
        """« confirme », « decline », « sans_reponse »..."""
        file = self.conversations[cid]
        echeance = time.monotonic() + delai_s
        while (msg := await self._prochain(file, echeance)) is not None:
            corps = decoder(msg.body)
            if corps.get("livreur_id") != livreur_id:
                continue
            perf = msg.get_metadata("performative")
            if perf == INFORM and corps.get("statut") == "confirme":
                return "confirme"
            if perf == FAILURE:
                return corps.get("raison", "echec")
        return "sans_reponse"

    # ------------------------------------------------------------------ suivi après attribution
    async def traiter_suivi(self, msg: Message) -> None:
        """Message sans conversation ouverte : avancement ou incident signalé par un livreur."""
        try:
            commande_id = uuid.UUID(msg.thread or "")
        except ValueError:
            return
        perf = msg.get_metadata("performative")
        corps = decoder(msg.body)
        etape, livreur_id = corps.get("etape"), corps.get("livreur_id")
        auteur = f"livreur:{livreur_id}"
        async with self.fabrique() as session:
            if perf == INFORM and etape in ETAPES:
                await commandes.changer_etat(session, commande_id, ETAPES[etape], auteur)
            elif perf == FAILURE and etape == "echec":
                await self._gerer_incident(session, commande_id, livreur_id, corps.get("motif"))

    async def _gerer_incident(
        self, session, commande_id: uuid.UUID, livreur_id: str, motif: str | None
    ):
        commande = await commandes.charger(session, commande_id)
        await self._retirer_course(str(commande_id))
        if commande.etat == EtatCommande.ATTRIBUEE:
            # Pas encore enlevée : on cherche un autre livreur.
            self.exclusions.setdefault(str(commande_id), set()).add(livreur_id)
            await commandes.liberer(
                session, commande_id, livreur_id, motif or "incident", str(self.jid)
            )
            self._lancer(commande_id)
        else:
            # Colis en main : pas de réattribution automatique, le répartiteur décide.
            await commandes.changer_etat(
                session,
                commande_id,
                EtatCommande.ECHEC_LIVRAISON,
                f"livreur:{livreur_id}",
                {"motif": motif},
            )
            await commandes.journaliser(
                session,
                commande_id,
                "alerte_repartiteur",
                str(self.jid),
                {"raison": "echec_apres_enlevement"},
            )

    async def _retirer_course(self, cid: str) -> None:
        """Prévient le livreur concerné que la course ne lui appartient plus (s'il est encore là)."""
        jid = self.attributions.pop(cid, None)
        if jid is not None:
            await self._envoyer(jid, CANCEL, cid)

    # ------------------------------------------------------------------ perte du signal GPS
    async def _interroger_ages(self, livreur_ids: set[str]) -> dict[str, float | None]:
        """Âge de la dernière position de chaque livreur (None : absent de l'annuaire)."""
        file = self.conversations["controle-gps"] = asyncio.Queue()
        try:
            await self._envoyer(
                self.annuaire_jid, QUERY_IF, "controle-gps", livreur_ids=sorted(livreur_ids)
            )
            echeance = time.monotonic() + 5
            while (msg := await self._prochain(file, echeance)) is not None:
                if msg.get_metadata("performative") == INFORM_IF:
                    return decoder(msg.body)["ages"]
            return {}
        finally:
            self.conversations.pop("controle-gps", None)

    async def controler_signaux(self) -> None:
        """Vérifie que les livreurs ayant une course en cours donnent encore signe de vie.

        - Course pas encore enlevée : réattribution à un autre livreur.
        - Colis déjà en main : on ne peut pas réattribuer, le répartiteur est alerté (une seule fois).
        """
        async with self.fabrique() as session:
            reglages = await commandes.lire_reglages(session, self.reglages_forces)
            actives = await commandes.courses_actives(session)
        if not actives:
            return
        ages = await self._interroger_ages({str(livreur) for _, _, livreur in actives})
        if not ages:
            return  # l'annuaire n'a pas répondu : on ne juge personne sur un silence du système
        limite = reglages["perte_signal_s"]
        for commande_id, etat, livreur_uuid in actives:
            cid, livreur_id = str(commande_id), str(livreur_uuid)
            age = ages.get(livreur_id)
            if age is not None and age <= limite:
                self._alertes_gps.discard(cid)
                continue
            detail = {"livreur_id": livreur_id, "age_position_s": age, "limite_s": limite}
            async with self.fabrique() as session:
                if etat == EtatCommande.ATTRIBUEE:
                    await commandes.journaliser(
                        session, commande_id, "perte_signal_gps", str(self.jid), detail
                    )
                    self._alertes_gps.discard(cid)
                    await self._gerer_incident(session, commande_id, livreur_id, "perte_signal_gps")
                elif cid not in self._alertes_gps:
                    self._alertes_gps.add(cid)
                    await commandes.journaliser(
                        session, commande_id, "perte_signal_gps", str(self.jid), detail
                    )
                    await commandes.journaliser(
                        session,
                        commande_id,
                        "alerte_repartiteur",
                        str(self.jid),
                        {"raison": "signal_perdu_apres_enlevement", **detail},
                    )

    def _lancer(self, commande_id: uuid.UUID) -> None:
        tache = asyncio.create_task(self.attribuer(commande_id))
        self._taches.add(tache)
        tache.add_done_callback(self._taches.discard)

    # ------------------------------------------------------------------ comportements
    class Routeur(CyclicBehaviour):
        """Reçoit tous les messages et les aiguille vers la conversation de la commande."""

        async def run(self):
            msg = await self.receive(timeout=1)
            if msg is None:
                return
            file = self.agent.conversations.get(msg.thread)
            if file is not None:
                file.put_nowait(msg)
            else:
                try:
                    await self.agent.traiter_suivi(msg)
                except Exception:  # noqa: BLE001 - un message illisible ne doit pas tuer le routeur
                    journal.exception("Message de suivi non traité : %s", msg)

    class Ordonnanceur(CyclicBehaviour):
        """Démarre une conversation d'attribution par commande reçue, sans attendre les autres."""

        async def run(self):
            try:
                commande_id = await asyncio.wait_for(self.agent.file_commandes.get(), timeout=1)
            except TimeoutError:
                return
            self.agent._lancer(commande_id)

    class Surveillant(CyclicBehaviour):
        """Contrôle périodique des signaux GPS des courses en cours."""

        async def run(self):
            async with self.agent.fabrique() as session:
                reglages = await commandes.lire_reglages(session, self.agent.reglages_forces)
            await asyncio.sleep(reglages["controle_gps_intervalle_s"])
            try:
                await self.agent.controler_signaux()
            except Exception:  # noqa: BLE001 - la surveillance ne doit jamais s'arrêter
                journal.exception("Contrôle des signaux GPS en erreur")

    async def setup(self):
        self._postier = self.Routeur()
        self.add_behaviour(self._postier)
        self.add_behaviour(self.Ordonnanceur())
        self.add_behaviour(self.Surveillant())
