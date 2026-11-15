"""Espace de supervision (administrateur et répartiteur) : alertes, dossiers, commandes, livreurs."""

import flet as ft

from livraison.interfaces import formats
from livraison.interfaces.composants import (
    Espace,
    carte,
    libelle_etat_puce,
    puce,
    secondaire,
    titre,
)

VUES = ("alertes", "dossiers", "commandes", "en_ligne")
FILTRES = {
    "toutes": "Toutes",
    "en_recherche": "En recherche",
    "attribuee": "Attribuées",
    "enlevee": "Enlevées",
    "en_livraison": "En livraison",
    "livree": "Livrées",
    "annulee": "Annulées",
    "echec_livraison": "Échecs de livraison",
}
RAISONS = {
    "attribution_impossible": "Aucun livreur disponible n'a pu être trouvé",
    "echec_apres_enlevement": "Échec de livraison après l'enlèvement du colis",
    "signal_perdu_apres_enlevement": "Signal du livreur perdu après l'enlèvement",
}


class EspaceSupervision(Espace):
    def __init__(self, page, api):
        super().__init__(page, api)
        self.vue = "alertes"
        self.filtre: str | None = None
        self.donnees: dict[str, list[dict]] = {v: [] for v in VUES}
        self.liste_filtre = ft.Dropdown(
            label="Afficher",
            options=[ft.DropdownOption(key=k, text=t) for k, t in FILTRES.items()],
            value="toutes",
            on_select=self._filtre_choisi,
            expand=True,
        )
        self.contenu = ft.Column(spacing=10, scroll=ft.ScrollMode.AUTO, expand=True)

    # ------------------------------------------------------------------ cadre
    def build(self) -> ft.Control:
        return ft.Column([self.bandeau, self.contenu], expand=True)

    def installer_navigation(self) -> None:
        self.page.navigation_bar = ft.NavigationBar(
            destinations=[
                ft.NavigationBarDestination(icon=ft.Icons.WARNING, label="Alertes"),
                ft.NavigationBarDestination(icon=ft.Icons.FACT_CHECK, label="Dossiers"),
                ft.NavigationBarDestination(icon=ft.Icons.LIST_ALT, label="Commandes"),
                ft.NavigationBarDestination(icon=ft.Icons.TWO_WHEELER, label="En ligne"),
            ],
            selected_index=0,
            on_change=self._navigation,
        )

    async def _navigation(self, e) -> None:
        await self.aller(VUES[e.control.selected_index])

    async def aller(self, vue: str) -> None:
        self.vue = vue
        await self.rafraichir()

    async def demarrer(self) -> None:
        self.actif = True
        await self.rafraichir()
        self.lancer(self.rafraichir, intervalle_s=5.0, immediat=False)

    # ------------------------------------------------------------------ actualisation
    async def rafraichir(self) -> None:
        if self.vue == "alertes":
            self.donnees["alertes"] = await self.api.alertes()
        elif self.vue == "dossiers":
            self.donnees["dossiers"] = await self.api.dossiers("en_attente")
        elif self.vue == "commandes":
            self.donnees["commandes"] = await self.api.toutes_les_commandes(self.filtre)
        else:
            self.donnees["en_ligne"] = await self.api.livreurs_en_ligne()
        self.contenu.controls = getattr(self, f"_controles_{self.vue}")()
        self.maj()

    # ------------------------------------------------------------------ alertes
    def _controles_alertes(self) -> list[ft.Control]:
        alertes = self.donnees["alertes"]
        if not alertes:
            return [
                titre("Alertes"),
                secondaire("Aucune alerte : toutes les commandes suivent leur cours."),
            ]
        cartes = []
        for a in alertes:
            boutons: list[ft.Control] = []
            if a["etat"] == "en_recherche":
                boutons.append(
                    ft.FilledButton(
                        "Relancer la recherche",
                        icon=ft.Icons.SYNC,
                        on_click=self.action(self.relancer, a["commande_id"]),
                    )
                )
            boutons.append(
                ft.OutlinedButton(
                    "Annuler la commande",
                    icon=ft.Icons.CANCEL,
                    on_click=self.action(self.annuler, a["commande_id"]),
                )
            )
            cartes.append(
                carte(
                    ft.Row(
                        [
                            ft.Text(f"Commande n°{a['numero']}", weight=ft.FontWeight.BOLD),
                            libelle_etat_puce(a["etat"]),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Text(RAISONS.get(a["raison"], a["raison"] or "Alerte")),
                    secondaire(f"Signalée à {formats.heure(a['cree_le'])}"),
                    ft.Row(boutons, wrap=True),
                )
            )
        return [titre(f"Alertes ({len(alertes)})"), *cartes]

    async def relancer(self, commande_id: str) -> None:
        ok, _ = await self.appeler(self.api.relancer(commande_id))
        if ok:
            self.message("Recherche relancée.")
            await self.rafraichir()

    async def annuler(self, commande_id: str) -> None:
        self.fermer_dialogue()
        ok, _ = await self.appeler(self.api.annuler(commande_id))
        if ok:
            self.message("Commande annulée.")
            await self.rafraichir()

    # ------------------------------------------------------------------ dossiers
    def _controles_dossiers(self) -> list[ft.Control]:
        dossiers = self.donnees["dossiers"]
        if not dossiers:
            return [titre("Dossiers à valider"), secondaire("Aucun dossier en attente.")]
        cartes = []
        for d in dossiers:
            pieces = (
                ", ".join(f"{p['type']} {p['reference']}" for p in d["pieces"]) or "aucune pièce"
            )
            cartes.append(
                carte(
                    ft.Text(
                        f"{d['nom'] or 'Sans nom'} · {d['telephone']}", weight=ft.FontWeight.BOLD
                    ),
                    ft.Text(
                        f"Véhicule : {d['type_vehicule']} · {d['capacite_courses']} course(s) · colis {d['taille_colis_max']}"
                    ),
                    secondaire(f"Pièces : {pieces}"),
                    ft.Row(
                        [
                            ft.FilledButton(
                                "Valider",
                                icon=ft.Icons.CHECK_CIRCLE,
                                on_click=self.action(self.decider, d["utilisateur_id"], "valide"),
                            ),
                            ft.OutlinedButton(
                                "Refuser",
                                icon=ft.Icons.CANCEL,
                                on_click=self.action(self.decider, d["utilisateur_id"], "refuse"),
                            ),
                        ]
                    ),
                )
            )
        return [titre(f"Dossiers à valider ({len(dossiers)})"), *cartes]

    async def decider(self, utilisateur_id: str, decision: str) -> None:
        ok, _ = await self.appeler(self.api.decider_dossier(utilisateur_id, decision))
        if ok:
            self.message("Dossier validé." if decision == "valide" else "Dossier refusé.")
            await self.rafraichir()

    # ------------------------------------------------------------------ commandes
    async def _filtre_choisi(self, e) -> None:
        await self.filtrer(self.liste_filtre.value)

    async def filtrer(self, cle: str) -> None:
        self.liste_filtre.value = cle
        self.filtre = None if cle in (None, "toutes") else cle
        await self.rafraichir()

    def _controles_commandes(self) -> list[ft.Control]:
        commandes = self.donnees["commandes"]
        tuiles = [
            ft.ListTile(
                leading=ft.Icon(ft.Icons.INVENTORY_2),
                title=ft.Text(
                    f"N°{c['numero']} · {c['adresse_enlevement']} → {c['adresse_livraison']}"
                ),
                subtitle=ft.Text(f"{formats.prix(c['prix'])} · {formats.heure(c['cree_le'])}"),
                trailing=libelle_etat_puce(c["etat"]),
                on_click=self.action(self.ouvrir_detail, c["id"]),
            )
            for c in commandes
        ]
        vide = [secondaire("Aucune commande.")] if not commandes else []
        return [titre("Commandes"), self.liste_filtre, *vide, *tuiles]

    async def ouvrir_detail(self, commande_id: str) -> None:
        ok, d = await self.appeler(self.api.commande(commande_id))
        if not ok:
            return
        lignes: list[ft.Control] = [
            ft.Row(
                [
                    ft.Text(f"N°{d['numero']}", weight=ft.FontWeight.BOLD),
                    libelle_etat_puce(d["etat"]),
                ]
            ),
            ft.Text(f"De : {d['enlevement']['adresse']}"),
            ft.Text(f"À : {d['livraison']['adresse']}"),
            ft.Text(
                f"{formats.prix(d['prix'])} · {formats.distance(d['distance_m'])} · {formats.duree(d['duree_estimee_s'])}"
            ),
        ]
        if d.get("destinataire_nom") or d.get("destinataire_telephone"):
            lignes.append(
                ft.Text(
                    f"Destinataire : {d.get('destinataire_nom') or ''} {d.get('destinataire_telephone') or ''}".strip()
                )
            )
        if d.get("livreur"):
            lignes.append(
                ft.Text(f"Livreur : {d['livreur']['nom'] or '-'} · {d['livreur']['telephone']}")
            )
        actions: list[ft.Control] = [ft.TextButton("Fermer", on_click=self.action(self._fermer))]
        if d["etat"] in (*formats.ETATS_ANNULABLES, "echec_livraison"):
            actions.append(
                ft.FilledButton("Annuler la commande", on_click=self.action(self.annuler, d["id"]))
            )
        self.dialogue("Commande", ft.Column(lignes, tight=True, spacing=4), *actions)

    async def _fermer(self) -> None:
        self.fermer_dialogue()

    # ------------------------------------------------------------------ livreurs en ligne
    def _controles_en_ligne(self) -> list[ft.Control]:
        agents = self.donnees["en_ligne"]
        if not agents:
            return [titre("Livreurs en ligne"), secondaire("Aucun livreur en ligne.")]
        tuiles = [
            ft.ListTile(
                leading=ft.Icon(ft.Icons.TWO_WHEELER),
                title=ft.Text(f"{a['nom'] or 'Livreur'} · {a['telephone'] or ''}".strip(" ·")),
                subtitle=ft.Text(
                    f"{a['vehicule']} · {a['latitude']:.4f}, {a['longitude']:.4f} · {formats.il_y_a(a['age_position_s'])}"
                ),
                trailing=puce("En ligne", "valide"),
            )
            for a in agents
        ]
        return [titre(f"Livreurs en ligne ({len(agents)})"), *tuiles]
