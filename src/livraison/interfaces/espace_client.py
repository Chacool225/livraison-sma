"""Espace du client : commander (avec estimation du prix), suivre ses commandes, annuler."""

import flet as ft

from livraison.interfaces import formats
from livraison.interfaces.composants import (
    ChampLieu,
    Espace,
    carte,
    libelle_etat_puce,
    secondaire,
    titre,
)

TAILLES = {
    "petit": "Petit : enveloppe, petit paquet",
    "moyen": "Moyen : sac, carton",
    "grand": "Grand : colis volumineux",
}


class EspaceClient(Espace):
    def __init__(self, page, api):
        super().__init__(page, api)
        self.vue = "commander"  # commander | commandes | suivi
        self.commande_id: str | None = None
        self.codes: dict[
            str, str
        ] = {}  # codes de remise des commandes créées pendant cette session
        self.estimation: dict | None = None

        self.lieu_enlevement = ChampLieu("Enlèvement (commune)", self.maj)
        self.lieu_livraison = ChampLieu("Livraison (commune)", self.maj)
        self.taille = ft.Dropdown(
            label="Taille du colis",
            options=[ft.DropdownOption(key=k, text=t) for k, t in TAILLES.items()],
            value="petit",
            expand=True,
        )
        self.destinataire_nom = ft.TextField(label="Nom du destinataire")
        self.destinataire_telephone = ft.TextField(
            label="Téléphone du destinataire", keyboard_type=ft.KeyboardType.PHONE
        )
        self.description = ft.TextField(label="Contenu du colis (facultatif)")
        self.consignes = ft.TextField(label="Consignes pour le livreur (facultatif)")
        self.texte_estimation = ft.Text("", size=16, weight=ft.FontWeight.BOLD)
        self.contenu = ft.Column(spacing=12, scroll=ft.ScrollMode.AUTO, expand=True)

    # ------------------------------------------------------------------ cadre
    def build(self) -> ft.Control:
        return ft.Column([self.bandeau, self.contenu], expand=True)

    def installer_navigation(self) -> None:
        self.page.navigation_bar = ft.NavigationBar(
            destinations=[
                ft.NavigationBarDestination(icon=ft.Icons.ADD_BOX, label="Commander"),
                ft.NavigationBarDestination(icon=ft.Icons.LIST_ALT, label="Mes commandes"),
            ],
            selected_index=0,
            on_change=self._navigation,
        )

    async def _navigation(self, e) -> None:
        await self.aller(("commander", "commandes")[e.control.selected_index])

    async def demarrer(self) -> None:
        self.actif = True
        await self.afficher()
        self.lancer(self.rafraichir, intervalle_s=3.0, immediat=False)

    async def aller(self, vue: str, commande_id: str | None = None) -> None:
        self.vue = vue
        self.commande_id = commande_id
        await self.rafraichir()

    # ------------------------------------------------------------------ rendu
    async def rafraichir(self) -> None:
        if self.vue == "suivi" and self.commande_id:
            detail = await self.api.commande(self.commande_id)
            self.contenu.controls = self._controles_suivi(detail)
        elif self.vue == "commandes":
            self.contenu.controls = self._controles_liste(await self.api.mes_commandes())
        else:
            self.contenu.controls = self._controles_formulaire()
        self.maj()

    async def afficher(self) -> None:
        await self.rafraichir()

    def _controles_formulaire(self) -> list[ft.Control]:
        return [
            titre("Nouvelle livraison"),
            self.lieu_enlevement.controle,
            self.lieu_livraison.controle,
            self.taille,
            self.destinataire_nom,
            self.destinataire_telephone,
            self.description,
            self.consignes,
            ft.Row(
                [
                    ft.OutlinedButton(
                        "Estimer le prix", icon=ft.Icons.RECEIPT_LONG, on_click=self.estimer
                    ),
                    ft.FilledButton("Commander", icon=ft.Icons.SEND, on_click=self.commander),
                ],
                wrap=True,
            ),
            self.texte_estimation,
        ]

    def _controles_liste(self, commandes: list[dict]) -> list[ft.Control]:
        if not commandes:
            return [titre("Mes commandes"), secondaire("Vous n'avez pas encore de commande.")]
        tuiles = [
            ft.ListTile(
                leading=ft.Icon(ft.Icons.INVENTORY_2),
                title=ft.Text(
                    f"N°{c['numero']} · {c['adresse_enlevement']} → {c['adresse_livraison']}"
                ),
                subtitle=ft.Text(f"{formats.prix(c['prix'])} · {formats.heure(c['cree_le'])}"),
                trailing=libelle_etat_puce(c["etat"]),
                on_click=self.action(self.aller, "suivi", c["id"]),
            )
            for c in commandes
        ]
        return [titre("Mes commandes"), *tuiles]

    def _controles_suivi(self, d: dict) -> list[ft.Control]:
        controles: list[ft.Control] = [
            ft.Row(
                [titre(f"Commande n°{d['numero']}"), libelle_etat_puce(d["etat"])],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
        ]
        if d["etat"] not in ("annulee", "echec_livraison", "litige"):
            controles.append(ft.ProgressBar(value=formats.avancement(d["etat"])))
        controles.append(
            carte(
                ft.Text(f"De : {d['enlevement']['adresse']}"),
                ft.Text(f"À : {d['livraison']['adresse']}"),
                ft.Text(
                    f"{formats.prix(d['prix'])} · {formats.distance(d['distance_m'])} · "
                    f"environ {formats.duree(d['duree_estimee_s'])}",
                    weight=ft.FontWeight.BOLD,
                ),
                secondaire(f"Paiement en espèces à la livraison · {TAILLES[d['taille_colis']]}"),
            )
        )
        code = self.codes.get(d["id"])
        if code and d["etat"] not in ("livree", "cloturee", "annulee"):
            controles.append(
                carte(
                    ft.Text("Code de remise", weight=ft.FontWeight.BOLD),
                    ft.Text(code, size=36, weight=ft.FontWeight.BOLD, selectable=True),
                    secondaire(
                        "Donnez ce code au destinataire : le livreur doit le saisir pour confirmer la livraison."
                    ),
                )
            )
        livreur = d.get("livreur")
        if livreur:
            lignes = [
                ft.Text("Votre livreur", weight=ft.FontWeight.BOLD),
                ft.Text(f"{livreur['nom'] or 'Livreur'} · {livreur['telephone']}"),
                secondaire(f"Véhicule : {livreur['type_vehicule']}"),
            ]
            if livreur.get("position"):
                p = livreur["position"]
                lignes.append(
                    secondaire(
                        f"Position : {p['latitude']:.4f}, {p['longitude']:.4f} ({formats.il_y_a(p['age_s'])})"
                    )
                )
            controles.append(carte(*lignes))
        elif d["etat"] in ("validee", "en_recherche"):
            controles.append(secondaire("Nous cherchons un livreur près de l'enlèvement…"))
        if d["etat"] in formats.ETATS_ANNULABLES:
            controles.append(
                ft.OutlinedButton(
                    "Annuler la commande",
                    icon=ft.Icons.CANCEL,
                    on_click=self.action(self.demander_annulation, d["id"]),
                )
            )
        controles.append(
            ft.TextButton(
                "Retour", icon=ft.Icons.ARROW_BACK, on_click=self.action(self.aller, "commandes")
            )
        )
        return controles

    # ------------------------------------------------------------------ actions
    def _corps(self) -> dict:
        enlevement, livraison = self.lieu_enlevement.lieu(), self.lieu_livraison.lieu()
        corps = {
            "enlevement": enlevement,
            "livraison": livraison,
            "taille_colis": self.taille.value or "petit",
            "mode_paiement": "especes",
        }
        for champ, controle in (
            ("destinataire_nom", self.destinataire_nom),
            ("destinataire_telephone", self.destinataire_telephone),
            ("description_colis", self.description),
            ("consignes", self.consignes),
        ):
            if (controle.value or "").strip():
                corps[champ] = controle.value.strip()
        return corps

    async def estimer(self, _=None) -> None:
        try:
            corps = self._corps()
        except ValueError as erreur:
            self.message(str(erreur), erreur=True)
            return
        ok, estimation = await self.appeler(
            self.api.estimer(corps["enlevement"], corps["livraison"])
        )
        if ok:
            self.estimation = estimation
            self.texte_estimation.value = (
                f"{formats.prix(estimation['prix'])} · {formats.distance(estimation['distance_m'])} · "
                f"environ {formats.duree(estimation['duree_estimee_s'])}"
            )
            self.maj()

    async def commander(self, _=None) -> None:
        try:
            corps = self._corps()
        except ValueError as erreur:
            self.message(str(erreur), erreur=True)
            return
        ok, commande = await self.appeler(self.api.creer_commande(corps))
        if not ok:
            return
        self.codes[commande["id"]] = commande["code_remise"]
        for controle in (
            self.destinataire_nom,
            self.destinataire_telephone,
            self.description,
            self.consignes,
        ):
            controle.value = ""
        self.lieu_enlevement.vider()
        self.lieu_livraison.vider()
        self.texte_estimation.value = ""
        self.message(
            f"Commande n°{commande['numero']} enregistrée : {formats.prix(commande['prix'])}."
        )
        await self.aller("suivi", commande["id"])

    async def demander_annulation(self, commande_id: str) -> None:
        self.dialogue(
            "Annuler la commande ?",
            ft.Text(
                "Le livreur éventuellement prévenu ne se déplacera pas. Cette action est définitive."
            ),
            ft.TextButton("Non, garder", on_click=self.action(self._fermer)),
            ft.FilledButton("Oui, annuler", on_click=self.action(self.annuler, commande_id)),
        )

    async def _fermer(self) -> None:
        self.fermer_dialogue()

    async def annuler(self, commande_id: str) -> None:
        self.fermer_dialogue()
        ok, _ = await self.appeler(self.api.annuler(commande_id))
        if ok:
            self.message("Commande annulée.")
            await self.rafraichir()
