"""Espace du livreur : dossier, mise en ligne, propositions de courses, étapes de la livraison."""

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
from livraison.interfaces.lieux import LIEUX

VEHICULES = {"velo": "Vélo", "moto": "Moto", "voiture": "Voiture"}
TAILLES_MAX = {"petit": "Petit colis", "moyen": "Colis moyen", "grand": "Grand colis"}
PIECES = {
    "permis": "Permis de conduire",
    "carte_identite": "Carte d'identité",
    "carte_grise": "Carte grise",
}
LIBELLES_VALIDATION = {
    "en_attente": "En attente de validation",
    "valide": "Dossier validé",
    "refuse": "Dossier refusé",
}
INTERVALLE_POSITION_S = 20.0  # sans position récente, une course en cours peut être réattribuée


class EspaceLivreur(Espace):
    def __init__(self, page, api):
        super().__init__(page, api)
        self.vue = "courses"  # courses | dossier
        self.dossier: dict | None = None
        self.modification = False
        self.en_ligne = False
        self.position: tuple[float, float] = LIEUX["Plateau"]
        self.courses: dict = {"propositions": [], "en_cours": []}

        self.liste_position = ft.Dropdown(
            label="Ma position",
            options=[ft.DropdownOption(key=nom, text=nom) for nom in LIEUX],
            value="Plateau",
            on_select=self._position_choisie,
            expand=True,
        )
        self.interrupteur = ft.Switch(label="En ligne", value=False, on_change=self._bascule)
        self.champ_code = ft.TextField(
            label="Code donné par le destinataire",
            max_length=4,
            keyboard_type=ft.KeyboardType.NUMBER,
        )
        self.champ_motif = ft.TextField(
            label="Motif (client injoignable, panne...)", multiline=True
        )

        self.vehicule = ft.Dropdown(
            label="Véhicule",
            options=[ft.DropdownOption(key=k, text=t) for k, t in VEHICULES.items()],
            value="moto",
            expand=True,
        )
        self.capacite = ft.Dropdown(
            label="Courses simultanées",
            options=[ft.DropdownOption(key=str(n), text=str(n)) for n in range(1, 6)],
            value="2",
            expand=True,
        )
        self.taille_max = ft.Dropdown(
            label="Taille maximale des colis",
            options=[ft.DropdownOption(key=k, text=t) for k, t in TAILLES_MAX.items()],
            value="moyen",
            expand=True,
        )
        self.piece_type = ft.Dropdown(
            label="Pièce justificative",
            options=[ft.DropdownOption(key=k, text=t) for k, t in PIECES.items()],
            value="permis",
            expand=True,
        )
        self.piece_reference = ft.TextField(label="Numéro de la pièce")
        self.contenu = ft.Column(spacing=12, scroll=ft.ScrollMode.AUTO, expand=True)

    # ------------------------------------------------------------------ cadre
    def build(self) -> ft.Control:
        return ft.Column([self.bandeau, self.contenu], expand=True)

    def installer_navigation(self) -> None:
        self.page.navigation_bar = ft.NavigationBar(
            destinations=[
                ft.NavigationBarDestination(icon=ft.Icons.DELIVERY_DINING, label="Courses"),
                ft.NavigationBarDestination(icon=ft.Icons.BADGE, label="Mon dossier"),
            ],
            selected_index=0,
            on_change=self._navigation,
        )

    async def _navigation(self, e) -> None:
        await self.aller(("courses", "dossier")[e.control.selected_index])

    async def aller(self, vue: str) -> None:
        self.vue = vue
        await self.rafraichir()

    async def demarrer(self) -> None:
        self.actif = True
        await self.rafraichir()
        self.lancer(self.rafraichir, intervalle_s=2.0, immediat=False)
        self.lancer(self.envoyer_position, intervalle_s=INTERVALLE_POSITION_S, immediat=False)

    # ------------------------------------------------------------------ actualisation
    @property
    def valide(self) -> bool:
        return bool(self.dossier) and self.dossier["statut_validation"] == "valide"

    async def rafraichir(self) -> None:
        self.dossier = await self.api.mon_dossier()
        if self.dossier is not None:
            self.en_ligne = self.dossier.get("en_ligne", False)
            self.interrupteur.value = self.en_ligne
        if self.valide:
            self.courses = await self.api.mes_courses()
        self.contenu.controls = (
            self._controles_dossier() if self.vue == "dossier" else self._controles_courses()
        )
        self.maj()

    async def envoyer_position(self) -> None:
        """Rappelée toutes les 20 s : le serveur sait ainsi que le livreur est toujours joignable."""
        if self.en_ligne:
            await self.api.envoyer_position(*self.position)

    # ------------------------------------------------------------------ vue « courses »
    def _controles_courses(self) -> list[ft.Control]:
        if self.dossier is None:
            return [
                titre("Bienvenue"),
                secondaire("Déposez d'abord votre dossier de livreur (onglet « Mon dossier »)."),
            ]
        if not self.valide:
            return [
                titre("Courses"),
                carte(
                    puce(
                        LIBELLES_VALIDATION[self.dossier["statut_validation"]],
                        self.dossier["statut_validation"],
                    ),
                    secondaire(
                        "Vous pourrez recevoir des courses dès que l'administrateur aura validé votre dossier."
                    ),
                ),
            ]
        controles: list[ft.Control] = [
            carte(
                ft.Row(
                    [
                        self.interrupteur,
                        puce(
                            "En ligne" if self.en_ligne else "Hors ligne",
                            "valide" if self.en_ligne else "annulee",
                        ),
                    ]
                ),
                self.liste_position,
                secondaire(
                    "Votre position est envoyée automatiquement toutes les 20 s tant que vous êtes en ligne."
                ),
            )
        ]
        propositions, en_cours = self.courses["propositions"], self.courses["en_cours"]
        if propositions:
            controles.append(titre("Nouvelle course"))
            controles += [self._carte_proposition(p) for p in propositions]
        if en_cours:
            controles.append(titre("Courses en cours"))
            controles += [self._carte_course(c) for c in en_cours]
        if not propositions and not en_cours:
            controles.append(
                secondaire(
                    "Aucune course pour le moment."
                    if self.en_ligne
                    else "Passez en ligne pour recevoir des courses."
                )
            )
        return controles

    def _carte_proposition(self, p: dict) -> ft.Control:
        return carte(
            ft.Row(
                [
                    ft.Text(f"Course n°{p['numero']}", weight=ft.FontWeight.BOLD),
                    puce(formats.prix(p["prix"]), "valide"),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            ft.Text(f"Enlèvement : {p['adresse_enlevement']}"),
            ft.Text(f"Livraison : {p['adresse_livraison']}"),
            secondaire(f"À confirmer dans {p['expire_dans_s']:.0f} s"),
            ft.Row(
                [
                    ft.FilledButton(
                        "Accepter",
                        icon=ft.Icons.CHECK_CIRCLE,
                        on_click=self.action(self.repondre, p["commande_id"], True),
                    ),
                    ft.OutlinedButton(
                        "Refuser",
                        icon=ft.Icons.CANCEL,
                        on_click=self.action(self.repondre, p["commande_id"], False),
                    ),
                ]
            ),
        )

    def _carte_course(self, c: dict) -> ft.Control:
        cid, etat = c["commande_id"], c["etat"]
        boutons: list[ft.Control] = []
        if etat == "attribuee":
            boutons.append(
                ft.FilledButton(
                    "J'ai enlevé le colis",
                    icon=ft.Icons.INVENTORY_2,
                    on_click=self.action(self.signaler, cid, "enlevee"),
                )
            )
        if etat == "enlevee":
            boutons.append(
                ft.FilledButton(
                    "Je pars livrer",
                    icon=ft.Icons.DELIVERY_DINING,
                    on_click=self.action(self.signaler, cid, "en_livraison"),
                )
            )
        if etat in ("enlevee", "en_livraison"):
            boutons.append(
                ft.FilledButton(
                    "Colis livré",
                    icon=ft.Icons.CHECK_CIRCLE,
                    on_click=self.action(self.demander_code, cid),
                )
            )
        boutons.append(
            ft.TextButton(
                "Signaler un échec",
                icon=ft.Icons.REPORT_PROBLEM,
                on_click=self.action(self.demander_motif, cid),
            )
        )
        lignes: list[ft.Control] = [
            ft.Row(
                [
                    ft.Text(f"Course n°{c['numero']}", weight=ft.FontWeight.BOLD),
                    libelle_etat_puce(etat),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            ft.Text(f"Enlèvement : {c['enlevement']['adresse']}"),
            ft.Text(f"Livraison : {c['livraison']['adresse']}"),
        ]
        if c.get("destinataire_nom") or c.get("destinataire_telephone"):
            lignes.append(
                ft.Text(
                    f"Destinataire : {c.get('destinataire_nom') or ''} {c.get('destinataire_telephone') or ''}".strip()
                )
            )
        if c.get("consignes"):
            lignes.append(secondaire(f"Consignes : {c['consignes']}"))
        lignes.append(secondaire(f"{formats.prix(c['prix'])} à encaisser en espèces"))
        lignes.append(ft.Row(boutons, wrap=True))
        return carte(*lignes)

    # ------------------------------------------------------------------ vue « dossier »
    def _controles_dossier(self) -> list[ft.Control]:
        if self.dossier is not None and not self.modification:
            d = self.dossier
            return [
                titre("Mon dossier"),
                carte(
                    puce(LIBELLES_VALIDATION[d["statut_validation"]], d["statut_validation"]),
                    ft.Text(f"Véhicule : {VEHICULES.get(d['type_vehicule'], d['type_vehicule'])}"),
                    ft.Text(f"Courses simultanées : {d['capacite_courses']}"),
                    ft.Text(
                        f"Taille maximale : {TAILLES_MAX.get(d['taille_colis_max'], d['taille_colis_max'])}"
                    ),
                    secondaire("Modifier le dossier le remet en attente de validation."),
                ),
                ft.OutlinedButton(
                    "Modifier mon dossier",
                    icon=ft.Icons.EDIT,
                    on_click=self.action(self.modifier_dossier),
                ),
            ]
        return [
            titre("Mon dossier"),
            self.vehicule,
            self.capacite,
            self.taille_max,
            self.piece_type,
            self.piece_reference,
            ft.FilledButton(
                "Envoyer mon dossier",
                icon=ft.Icons.SEND,
                on_click=self.action(self.enregistrer_dossier),
            ),
        ]

    async def modifier_dossier(self) -> None:
        self.modification = True
        await self.rafraichir()

    async def enregistrer_dossier(self) -> None:
        corps = {
            "type_vehicule": self.vehicule.value,
            "capacite_courses": int(self.capacite.value or 2),
            "taille_colis_max": self.taille_max.value,
            "pieces": [
                {"type": self.piece_type.value, "reference": self.piece_reference.value.strip()}
            ]
            if (self.piece_reference.value or "").strip()
            else [],
        }
        ok, _ = await self.appeler(self.api.deposer_dossier(corps))
        if ok:
            self.modification = False
            self.message("Dossier envoyé : il sera examiné par l'administrateur.")
            await self.rafraichir()

    # ------------------------------------------------------------------ mise en ligne et position
    async def _bascule(self, e) -> None:
        await self.basculer_en_ligne(bool(e.control.value))

    async def basculer_en_ligne(self, voulu: bool) -> None:
        if voulu:
            ok, _ = await self.appeler(self.api.passer_en_ligne(*self.position))
        else:
            ok, _ = await self.appeler(self.api.passer_hors_ligne())
        if ok:
            self.en_ligne = voulu
        self.interrupteur.value = (
            self.en_ligne
        )  # en cas de refus, l'interrupteur revient en arrière
        await self.rafraichir()

    async def _position_choisie(self, e) -> None:
        await self.deplacer_vers(self.liste_position.value)

    async def deplacer_vers(self, lieu: str) -> None:
        self.liste_position.value = lieu
        self.position = LIEUX[lieu]
        if self.en_ligne:
            await self.appeler(self.api.envoyer_position(*self.position))
        self.maj()

    # ------------------------------------------------------------------ courses
    async def repondre(self, commande_id: str, accepte: bool) -> None:
        ok, _ = await self.appeler(self.api.repondre(commande_id, accepte))
        if ok:
            self.message(
                "Course acceptée : rendez-vous à l'enlèvement." if accepte else "Course refusée."
            )
            await self.rafraichir()

    def _course(self, commande_id: str) -> dict | None:
        return next((c for c in self.courses["en_cours"] if c["commande_id"] == commande_id), None)

    async def signaler(self, commande_id: str, etape: str) -> None:
        course = self._course(commande_id)
        ok, _ = await self.appeler(self.api.signaler_etape(commande_id, etape))
        if ok and course and etape == "enlevee":
            self.position = (course["enlevement"]["longitude"], course["enlevement"]["latitude"])
            await self.appeler(self.api.envoyer_position(*self.position))
        if ok:
            await self.rafraichir()

    async def demander_code(self, commande_id: str) -> None:
        self.champ_code.value = ""
        self.dialogue(
            "Confirmer la livraison",
            ft.Column(
                [
                    secondaire("Demandez au destinataire le code à 4 chiffres reçu du client."),
                    self.champ_code,
                ],
                tight=True,
            ),
            ft.TextButton("Annuler", on_click=self.action(self._fermer)),
            ft.FilledButton(
                "Confirmer", on_click=self.action(self.confirmer_livraison, commande_id)
            ),
        )

    async def confirmer_livraison(self, commande_id: str) -> None:
        course = self._course(commande_id)
        ok, _ = await self.appeler(
            self.api.signaler_etape(commande_id, "livree", code=self.champ_code.value)
        )
        if not ok:
            return  # le dialogue reste ouvert : le livreur peut corriger le code
        self.fermer_dialogue()
        if course:
            self.position = (course["livraison"]["longitude"], course["livraison"]["latitude"])
            await self.appeler(self.api.envoyer_position(*self.position))
        self.message("Livraison enregistrée. Merci !")
        await self.rafraichir()

    async def demander_motif(self, commande_id: str) -> None:
        self.champ_motif.value = ""
        self.dialogue(
            "Signaler un échec",
            self.champ_motif,
            ft.TextButton("Annuler", on_click=self.action(self._fermer)),
            ft.FilledButton("Signaler", on_click=self.action(self.signaler_echec, commande_id)),
        )

    async def signaler_echec(self, commande_id: str) -> None:
        ok, _ = await self.appeler(
            self.api.signaler_etape(commande_id, "echec", motif=self.champ_motif.value)
        )
        if ok:
            self.fermer_dialogue()
            self.message("Échec signalé : le répartiteur est prévenu si besoin.")
            await self.rafraichir()

    async def _fermer(self) -> None:
        self.fermer_dialogue()
