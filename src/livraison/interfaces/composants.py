"""Éléments d'interface communs aux trois espaces (client, livreur, supervision)."""

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from typing import Any

import flet as ft

from livraison.interfaces import formats
from livraison.interfaces.api_client import ApiClient, ErreurApi
from livraison.interfaces.lieux import AUTRE, LIEUX

COULEURS_ETAT = {
    "livree": (ft.Colors.GREEN_100, ft.Colors.GREEN_700),
    "cloturee": (ft.Colors.GREEN_100, ft.Colors.GREEN_700),
    "annulee": (ft.Colors.GREY_300, ft.Colors.GREY_700),
    "echec_livraison": (ft.Colors.RED_100, ft.Colors.RED_700),
    "litige": (ft.Colors.RED_100, ft.Colors.RED_700),
    "en_recherche": (ft.Colors.ORANGE_100, ft.Colors.ORANGE_700),
    "validee": (ft.Colors.ORANGE_100, ft.Colors.ORANGE_700),
    "attribuee": (ft.Colors.BLUE_100, ft.Colors.BLUE_700),
    "enlevee": (ft.Colors.BLUE_100, ft.Colors.BLUE_700),
    "en_livraison": (ft.Colors.BLUE_100, ft.Colors.BLUE_700),
    "valide": (ft.Colors.GREEN_100, ft.Colors.GREEN_700),
    "en_attente": (ft.Colors.ORANGE_100, ft.Colors.ORANGE_700),
    "refuse": (ft.Colors.RED_100, ft.Colors.RED_700),
}


def titre(texte: str) -> ft.Text:
    return ft.Text(texte, size=20, weight=ft.FontWeight.BOLD)


def secondaire(texte: str) -> ft.Text:
    return ft.Text(texte, size=13, color=ft.Colors.GREY_700)


def puce(libelle: str, cle: str) -> ft.Container:
    """Pastille colorée (état d'une commande, statut d'un dossier)."""
    fond, texte = COULEURS_ETAT.get(cle, (ft.Colors.GREY_300, ft.Colors.GREY_700))
    return ft.Container(
        content=ft.Text(libelle, size=12, weight=ft.FontWeight.BOLD, color=texte),
        bgcolor=fond,
        padding=ft.Padding.symmetric(horizontal=10, vertical=4),
        border_radius=ft.BorderRadius.all(12),
    )


def carte(*contenu: ft.Control) -> ft.Card:
    return ft.Card(
        content=ft.Container(
            content=ft.Column(list(contenu), spacing=6, tight=True), padding=ft.Padding.all(14)
        )
    )


def textes(controle: Any) -> list[str]:
    """Tous les textes affichés sous un contrôle (utile aux tests et à la vérification)."""
    trouves: list[str] = []
    if isinstance(controle, ft.Text) and controle.value:
        trouves.append(str(controle.value))
    for nom in (
        "controls",
        "content",
        "title",
        "subtitle",
        "leading",
        "trailing",
        "actions",
        "label",
    ):
        enfant = getattr(controle, nom, None)
        for element in enfant if isinstance(enfant, list) else [enfant]:
            if isinstance(element, str):
                trouves.append(element)
            elif element is not None and not isinstance(element, int | float | bool):
                trouves.extend(textes(element))
    return trouves


class ChampLieu:
    """Choix d'un lieu : une commune de la liste + une précision, ou des coordonnées libres."""

    def __init__(self, libelle: str, maj: Callable[[], None]):
        self._maj = maj
        options = [ft.DropdownOption(key=nom, text=nom) for nom in LIEUX]
        options.append(ft.DropdownOption(key=AUTRE, text="Autre lieu (coordonnées)…"))
        self.liste = ft.Dropdown(
            label=libelle, options=options, on_select=self._choisi, expand=True
        )
        self.detail = ft.TextField(label="Précision : rue, repère, bâtiment (facultatif)")
        self.longitude = ft.TextField(label="Longitude (ex. -4.0267)", visible=False)
        self.latitude = ft.TextField(label="Latitude (ex. 5.3200)", visible=False)
        self.controle = ft.Column(
            [self.liste, self.detail, self.longitude, self.latitude], spacing=8
        )

    def _choisi(self, _=None) -> None:
        libre = self.liste.value == AUTRE
        self.longitude.visible = self.latitude.visible = libre
        self._maj()

    def lieu(self) -> dict:
        """{"adresse", "longitude", "latitude"} ; lève ValueError avec un message affichable."""
        nom = self.liste.value
        precision = (self.detail.value or "").strip()
        libelle = (self.liste.label or "Lieu").lower()
        if not nom:
            raise ValueError(f"Choisissez le lieu ({libelle}).")
        if nom == AUTRE:
            try:
                lon = float((self.longitude.value or "").replace(",", "."))
                lat = float((self.latitude.value or "").replace(",", "."))
            except ValueError:
                raise ValueError(
                    "Saisissez une longitude et une latitude valides (ex. -4.0267 et 5.3200)."
                ) from None
            if not (-180 <= lon <= 180 and -90 <= lat <= 90):
                raise ValueError("Coordonnées hors limites.")
            return {
                "adresse": precision or f"{lat:.5f}, {lon:.5f}",
                "longitude": lon,
                "latitude": lat,
            }
        lon, lat = LIEUX[nom]
        return {
            "adresse": f"{precision}, {nom}" if precision else f"{nom}, Abidjan",
            "longitude": lon,
            "latitude": lat,
        }

    def vider(self) -> None:
        self.liste.value = None
        self.detail.value = self.longitude.value = self.latitude.value = ""
        self.longitude.visible = self.latitude.visible = False


class Espace:
    """Base d'un espace (un écran complet par rôle) : messages, appels à l'API, actualisation."""

    def __init__(self, page: ft.Page, api: ApiClient):
        self.page = page
        self.api = api
        self.actif = False
        self._taches: list[Any] = []
        self.bandeau = ft.Text("", color=ft.Colors.RED_700, size=12, visible=False)

    # ------------------------------------------------------------------ affichage
    def maj(self) -> None:
        with contextlib.suppress(Exception):  # la page peut avoir disparu (onglet fermé)
            self.page.update()

    def message(self, texte: str, erreur: bool = False) -> None:
        self.page.show_dialog(
            ft.SnackBar(
                ft.Text(texte), bgcolor=ft.Colors.RED_700 if erreur else ft.Colors.GREEN_700
            )
        )

    def dialogue(
        self, titre_dialogue: str, contenu: ft.Control, *actions: ft.Control
    ) -> ft.AlertDialog:
        dialogue = ft.AlertDialog(
            modal=True, title=ft.Text(titre_dialogue), content=contenu, actions=list(actions)
        )
        self.page.show_dialog(dialogue)
        return dialogue

    def fermer_dialogue(self) -> None:
        with contextlib.suppress(Exception):
            self.page.pop_dialog()

    def action(self, fonction: Callable[..., Awaitable[Any]], *arguments: Any):
        """Gestionnaire d'événement asynchrone qui appelle `fonction(*arguments)`."""

        async def gestionnaire(_=None):
            await fonction(*arguments)

        return gestionnaire

    # ------------------------------------------------------------------ appels à l'API
    async def appeler(self, appel: Awaitable[Any]) -> tuple[bool, Any]:
        """Exécute un appel d'API ; en cas d'erreur, affiche le message et renvoie (False, None)."""
        try:
            return True, await appel
        except ErreurApi as erreur:
            self.message(erreur.detail, erreur=True)
            return False, None

    # ------------------------------------------------------------------ actualisation périodique
    def lancer(
        self, fonction: Callable[[], Awaitable[None]], intervalle_s: float, immediat: bool = True
    ) -> None:
        async def boucle():
            if not immediat:
                await asyncio.sleep(intervalle_s)
            while self.actif:
                try:
                    await fonction()
                    self.bandeau.visible = False
                except ErreurApi as erreur:
                    self.bandeau.value = f"Connexion perdue : {erreur.detail}"
                    self.bandeau.visible = True
                    self.maj()
                except asyncio.CancelledError:
                    raise
                except Exception as erreur:  # noqa: BLE001 - l'actualisation ne doit jamais s'arrêter
                    self.bandeau.value = f"Erreur inattendue : {erreur}"
                    self.bandeau.visible = True
                    self.maj()
                await asyncio.sleep(intervalle_s)

        self._taches.append(self.page.run_task(boucle))

    def arreter(self) -> None:
        self.actif = False
        for tache in self._taches:
            with contextlib.suppress(Exception):
                tache.cancel()
        self._taches.clear()

    # ------------------------------------------------------------------ à définir par chaque espace
    def build(self) -> ft.Control:
        raise NotImplementedError

    def installer_navigation(self) -> None:
        """Barre de navigation du bas (facultative)."""

    async def demarrer(self) -> None:
        raise NotImplementedError


def libelle_etat_puce(etat: str) -> ft.Container:
    return puce(formats.libelle_etat(etat), etat)
