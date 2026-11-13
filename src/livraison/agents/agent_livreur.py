"""Agent livreur du lot 2 : positions GPS réelles, refus motivés, coût réel, réservation de
capacité, confirmation du livreur humain, suivi des étapes.

(La version « grille » du TP reste dans `livreur.py` : elle sert au test de non-régression.)
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from spade.agent import Agent
from spade.behaviour import CyclicBehaviour, OneShotBehaviour
from spade.message import Message
from spade.template import Template

from livraison.agents.protocole import (
    ACCEPT,
    CANCEL,
    CFP,
    FAILURE,
    INFORM,
    PROPOSE,
    REFUSE,
    REJECT,
    SUBSCRIBE,
    decoder,
    encoder,
)
from livraison.modele.cout import cout_offre
from livraison.modele.geo import Point, distance_m
from livraison.services.itineraire import Itineraire, ItineraireDroiteLigne

ORDRE_TAILLES = {"petit": 0, "moyen": 1, "grand": 2}
DUREE_RESERVATION_MAX_S = 120  # une réservation jamais confirmée ni rejetée finit par expirer

# Le « livreur humain » : reçoit la course dans son application et répond oui, non, ou rien.
# Renvoie True (accepte), False (décline). Un dépassement du délai compte comme « sans réponse ».
Confirmateur = Callable[[dict], Awaitable[bool]]


async def confirmer_automatiquement(course: dict) -> bool:
    return True


@dataclass
class Course:
    commande_id: str
    enlevement: Point
    livraison: Point
    etat: str = "attribuee"  # attribuee -> enlevee -> en_livraison


class LivreurAgent(Agent):
    def __init__(
        self,
        jid,
        mot_de_passe,
        *,
        livreur_id: str,
        annuaire_jid: str,
        dispatcher_jid: str,
        position: Point,
        vehicule: str = "moto",
        capacite: int = 3,
        taille_max: str = "moyen",
        note: float = 0.0,
        itineraire: Itineraire | None = None,
        confirmateur: Confirmateur = confirmer_automatiquement,
        horloge: Callable[[], float] = time.monotonic,
        **options,
    ):
        super().__init__(jid, mot_de_passe, **options)
        self.livreur_id = livreur_id
        self.annuaire_jid = annuaire_jid
        self.dispatcher_jid = dispatcher_jid
        self.position = tuple(position)
        self.vehicule = vehicule
        self.capacite = capacite
        self.taille_max = taille_max
        self.note = note
        self.itineraire = itineraire or ItineraireDroiteLigne()
        self.confirmateur = confirmateur
        self.horloge = horloge
        self.position_le = horloge()
        self.en_ligne = False
        self.courses: dict[str, Course] = {}
        self.reservations: dict[str, float] = {}  # commande -> instant de la réservation
        self._proposees: dict[str, Course] = {}

    # ------------------------------------------------------------------ état
    @property
    def charge(self) -> int:
        return len(self.courses)

    def prochain_arret(self) -> Point | None:
        for course in self.courses.values():
            return course.enlevement if course.etat == "attribuee" else course.livraison
        return None

    def _purger_reservations(self) -> None:
        limite = self.horloge() - DUREE_RESERVATION_MAX_S
        for cid in [c for c, t in self.reservations.items() if t < limite]:
            self.reservations.pop(cid)
            self._proposees.pop(cid, None)

    def motif_de_refus(self, enlevement: Point, taille: str, rayon_m: float, age_max_s: float):
        """Raison pour laquelle l'agent ne peut pas proposer, ou None s'il le peut."""
        if not self.en_ligne:
            return "hors_ligne"
        if self.charge + len(self.reservations) >= self.capacite:
            return "sature"
        if self.horloge() - self.position_le > age_max_s:
            return "position_trop_ancienne"
        if distance_m(self.position, enlevement) > rayon_m:
            return "hors_zone"
        if ORDRE_TAILLES[taille] > ORDRE_TAILLES[self.taille_max]:
            return "colis_trop_grand"
        return None

    async def calculer_offre(self, enlevement: Point, penalite: float) -> tuple[float, float]:
        """(coût, durée jusqu'à l'enlèvement en secondes)."""
        vers = await self.itineraire.duree_s(self.position, enlevement, self.vehicule)
        detour = 0.0
        suivant = self.prochain_arret()
        if suivant is not None:  # temps ajouté aux courses déjà acceptées
            via = vers + await self.itineraire.duree_s(enlevement, suivant, self.vehicule)
            direct = await self.itineraire.duree_s(self.position, suivant, self.vehicule)
            detour = max(0.0, via - direct)
        return cout_offre(vers, detour, self.charge, penalite), vers

    # ------------------------------------------------------------------ envoi hors comportement
    async def _envoyer(self, destinataire: str, performative: str, thread: str | None, **corps):
        msg = Message(to=destinataire)
        msg.set_metadata("performative", performative)
        if thread:
            msg.thread = thread
        msg.body = encoder(**corps)

        class Envoi(OneShotBehaviour):
            async def run(self):
                await self.send(msg)

        envoi = Envoi()
        self.add_behaviour(envoi)
        await envoi.join()

    async def _publier(self) -> None:
        await self._envoyer(
            self.annuaire_jid,
            SUBSCRIBE,
            None,
            livreur_id=self.livreur_id,
            vehicule=self.vehicule,
            taille_max=self.taille_max,
            position=list(self.position),
        )

    # ------------------------------------------------------------------ actions du livreur
    async def passer_en_ligne(self) -> None:
        self.en_ligne = True
        await self._publier()

    async def passer_hors_ligne(self) -> None:
        self.en_ligne = False
        await self._envoyer(self.annuaire_jid, CANCEL, None, livreur_id=self.livreur_id)

    async def mettre_a_jour_position(self, point: Point) -> None:
        self.position = tuple(point)
        self.position_le = self.horloge()
        if self.en_ligne:
            await self._publier()

    async def signaler(self, commande_id: str, etape: str, motif: str | None = None) -> None:
        """Le livreur annonce une étape : enlevee, en_livraison, livree, ou echec (incident)."""
        course = self.courses.get(commande_id)
        if course is None:
            raise ValueError(f"Aucune course {commande_id} en cours")
        if etape == "enlevee":
            course.etat = "enlevee"
            await self.mettre_a_jour_position(course.enlevement)
        elif etape == "en_livraison":
            course.etat = "en_livraison"
        elif etape == "livree":
            self.courses.pop(commande_id)
            await self.mettre_a_jour_position(course.livraison)
        elif etape == "echec":
            self.courses.pop(commande_id)
        else:
            raise ValueError(f"Étape inconnue : {etape}")
        performative = FAILURE if etape == "echec" else INFORM
        await self._envoyer(
            self.dispatcher_jid,
            performative,
            commande_id,
            etape=etape,
            livreur_id=self.livreur_id,
            motif=motif,
        )

    # ------------------------------------------------------------------ comportements
    class RepondreAuxAppels(CyclicBehaviour):
        """CFP -> « propose » (avec le coût) ou « refuse » (avec la raison)."""

        async def run(self):
            msg = await self.receive(timeout=10)
            if msg is None:
                return
            livreur = self.agent
            demande = decoder(msg.body)
            cid = msg.thread
            livreur._purger_reservations()
            livreur.reservations.pop(cid, None)  # un nouvel appel remplace l'ancienne réservation
            livreur._proposees.pop(cid, None)
            enlevement = tuple(demande["enlevement"])
            motif = livreur.motif_de_refus(
                enlevement, demande["taille"], demande["rayon_m"], demande["age_max_position_s"]
            )
            reponse = msg.make_reply()
            if motif:
                reponse.set_metadata("performative", REFUSE)
                reponse.body = encoder(
                    livreur_id=livreur.livreur_id, tour=demande["tour"], raison=motif
                )
            else:
                cout, eta = await livreur.calculer_offre(enlevement, demande["penalite_charge"])
                # Réservation : tant que l'offre n'est ni retenue ni rejetée, la place est prise,
                # pour ne pas s'engager deux fois au-delà de la capacité (appels simultanés).
                livreur.reservations[cid] = livreur.horloge()
                livreur._proposees[cid] = Course(cid, enlevement, tuple(demande["livraison"]))
                reponse.set_metadata("performative", PROPOSE)
                reponse.body = encoder(
                    livreur_id=livreur.livreur_id,
                    tour=demande["tour"],
                    cout=cout,
                    eta_s=eta,
                    note=livreur.note,
                )
            await self.send(reponse)

    class RecevoirAcceptation(CyclicBehaviour):
        """Offre retenue -> demande au livreur humain de confirmer, dans le délai imparti."""

        async def run(self):
            msg = await self.receive(timeout=10)
            if msg is None:
                return
            livreur = self.agent
            cid = msg.thread
            delai = decoder(msg.body)["delai_confirmation_s"]
            course = livreur._proposees.pop(cid, None)
            reponse = msg.make_reply()
            if course is None:
                livreur.reservations.pop(cid, None)
                reponse.set_metadata("performative", FAILURE)
                reponse.body = encoder(livreur_id=livreur.livreur_id, raison="proposition_inconnue")
                await self.send(reponse)
                return
            try:
                accepte = await asyncio.wait_for(
                    livreur.confirmateur(
                        {
                            "commande_id": cid,
                            "enlevement": course.enlevement,
                            "livraison": course.livraison,
                        }
                    ),
                    timeout=delai,
                )
                raison = None if accepte else "decline"
            except TimeoutError:
                accepte, raison = False, "sans_reponse"
            except Exception:  # noqa: BLE001 - l'application du livreur peut échouer de mille façons
                accepte, raison = False, "erreur_confirmation"
            livreur.reservations.pop(cid, None)
            if accepte:
                livreur.courses[cid] = course
                reponse.set_metadata("performative", INFORM)
                reponse.body = encoder(livreur_id=livreur.livreur_id, statut="confirme")
            else:
                reponse.set_metadata("performative", FAILURE)
                reponse.body = encoder(livreur_id=livreur.livreur_id, raison=raison)
            await self.send(reponse)

    class RecevoirRejet(CyclicBehaviour):
        """Offre non retenue -> la place réservée est libérée."""

        async def run(self):
            msg = await self.receive(timeout=10)
            if msg is not None:
                self.agent.reservations.pop(msg.thread, None)
                self.agent._proposees.pop(msg.thread, None)

    class RecevoirAnnulation(CyclicBehaviour):
        """Le dispatcher retire une course (livreur injoignable, commande annulée...)."""

        async def run(self):
            msg = await self.receive(timeout=10)
            if msg is not None:
                livreur = self.agent
                livreur.courses.pop(msg.thread, None)
                livreur.reservations.pop(msg.thread, None)
                livreur._proposees.pop(msg.thread, None)

    async def setup(self):
        for comportement, performative in (
            (self.RepondreAuxAppels(), CFP),
            (self.RecevoirAcceptation(), ACCEPT),
            (self.RecevoirRejet(), REJECT),
            (self.RecevoirAnnulation(), CANCEL),
        ):
            modele = Template()
            modele.set_metadata("performative", performative)
            self.add_behaviour(comportement, modele)
