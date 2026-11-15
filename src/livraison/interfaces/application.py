"""Application Flet : écran de connexion puis l'espace correspondant au rôle de l'utilisateur."""

import contextlib

import flet as ft

from livraison.interfaces.api_client import ApiClient
from livraison.interfaces.composants import Espace, secondaire, titre
from livraison.interfaces.espace_client import EspaceClient
from livraison.interfaces.espace_livreur import EspaceLivreur
from livraison.interfaces.espace_supervision import EspaceSupervision

ESPACES = {
    "client": EspaceClient,
    "livreur": EspaceLivreur,
    "administrateur": EspaceSupervision,
    "repartiteur": EspaceSupervision,
}
LIBELLES_ROLE = {
    "client": "Client",
    "livreur": "Livreur",
    "administrateur": "Administrateur",
    "repartiteur": "Répartiteur",
}


class Application:
    def __init__(self, page: ft.Page, api: ApiClient):
        self.page = page
        self.api = api
        self.espace: Espace | None = None

        self.champ_telephone = ft.TextField(
            label="Votre numéro de téléphone",
            hint_text="07 00 00 00 00",
            keyboard_type=ft.KeyboardType.PHONE,
        )
        self.bouton_code = ft.FilledButton(
            "Recevoir le code par SMS", icon=ft.Icons.SMARTPHONE, on_click=self.demander_code
        )
        self.champ_code = ft.TextField(
            label="Code reçu (6 chiffres)",
            max_length=6,
            keyboard_type=ft.KeyboardType.NUMBER,
            visible=False,
        )
        self.choix_role = ft.Dropdown(
            label="Je suis (première connexion)",
            options=[
                ft.DropdownOption(key="client", text="Client : j'envoie des colis"),
                ft.DropdownOption(key="livreur", text="Livreur : je livre des colis"),
            ],
            value="client",
            visible=False,
        )
        self.champ_nom = ft.TextField(label="Votre nom (première connexion)", visible=False)
        self.bouton_connexion = ft.FilledButton(
            "Se connecter", icon=ft.Icons.LOCK, on_click=self.connecter, visible=False
        )
        self.indication = ft.Text("", size=13, color=ft.Colors.GREY_700)
        self.erreur = ft.Text("", size=13, color=ft.Colors.RED_700)

    # ------------------------------------------------------------------ connexion
    def afficher_connexion(self) -> None:
        self.page.clean()
        self.page.appbar = ft.AppBar(title=ft.Text("Livraison SMA"), center_title=False)
        self.page.navigation_bar = None
        self.page.add(
            ft.Column(
                [
                    titre("Connexion"),
                    secondaire(
                        "Entrez votre numéro : un code à usage unique vous est envoyé par SMS."
                    ),
                    self.champ_telephone,
                    self.bouton_code,
                    self.indication,
                    self.champ_code,
                    self.choix_role,
                    self.champ_nom,
                    self.bouton_connexion,
                    self.erreur,
                ],
                spacing=12,
                width=420,
            )
        )
        self.page.update()

    def _erreur(self, texte: str) -> None:
        self.erreur.value = texte
        self.page.update()

    async def demander_code(self, _=None) -> None:
        self.erreur.value = ""
        telephone = (self.champ_telephone.value or "").strip()
        if not telephone:
            self._erreur("Saisissez votre numéro de téléphone.")
            return
        from livraison.interfaces.api_client import ErreurApi

        try:
            reponse = await self.api.demander_code(telephone)
        except ErreurApi as erreur:
            self._erreur(erreur.detail)
            return
        if reponse.get(
            "code_dev"
        ):  # mode développement : pas de vrai SMS, le serveur donne le code
            self.champ_code.value = reponse["code_dev"]
            self.indication.value = f"Mode développement : le code {reponse['code_dev']} est pré-rempli (aucun SMS envoyé)."
        else:
            self.indication.value = "Code envoyé par SMS."
        for controle in (self.champ_code, self.choix_role, self.champ_nom, self.bouton_connexion):
            controle.visible = True
        self.page.update()

    async def connecter(self, _=None) -> None:
        from livraison.interfaces.api_client import ErreurApi

        self.erreur.value = ""
        try:
            utilisateur = await self.api.se_connecter(
                (self.champ_telephone.value or "").strip(),
                (self.champ_code.value or "").strip(),
                self.choix_role.value or "client",
                (self.champ_nom.value or "").strip() or None,
            )
        except ErreurApi as erreur:
            self._erreur(erreur.detail)
            return
        await self.afficher_espace(utilisateur)

    # ------------------------------------------------------------------ espaces
    async def afficher_espace(self, utilisateur: dict) -> None:
        self.page.clean()
        self.espace = ESPACES[utilisateur["role"]](self.page, self.api)
        self.page.appbar = ft.AppBar(
            title=ft.Text(
                f"{utilisateur['nom'] or utilisateur['telephone']} · {LIBELLES_ROLE[utilisateur['role']]}"
            ),
            center_title=False,
            actions=[
                ft.IconButton(
                    icon=ft.Icons.LOGOUT, tooltip="Se déconnecter", on_click=self.deconnecter
                )
            ],
        )
        self.page.add(self.espace.build())
        self.espace.installer_navigation()
        await self.espace.demarrer()
        self.page.update()

    async def deconnecter(self, _=None) -> None:
        self.arreter()
        self.api.deconnecter()
        for controle in (self.champ_code, self.choix_role, self.champ_nom, self.bouton_connexion):
            controle.visible = False
        self.champ_telephone.value = self.champ_code.value = self.indication.value = ""
        self.afficher_connexion()

    def arreter(self) -> None:
        if self.espace is not None:
            self.espace.arreter()
            self.espace = None

    async def fin_de_session(self, _=None) -> None:
        """La page est fermée : on arrête les actualisations et on libère la connexion à l'API."""
        self.arreter()
        with contextlib.suppress(Exception):
            await self.api.fermer()


def creer_application(url_api: str):
    """Fonction `main` à donner à Flet."""

    async def main(page: ft.Page) -> None:
        page.title = "Livraison SMA"
        page.theme_mode = ft.ThemeMode.LIGHT
        page.padding = 16
        application = Application(page, ApiClient(url_api))
        page.on_disconnect = application.fin_de_session
        application.afficher_connexion()

    return main
