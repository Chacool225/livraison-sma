"""Interfaces Flet. Une page factice remplace la vraie page : les contrôles Flet sont bien construits
(un paramètre invalide lèverait une erreur) et les écrans sont pilotés comme le ferait un utilisateur.
Le parcours complet (voir plus bas) exige PostgreSQL et le serveur XMPP ; le reste, rien."""

import asyncio
from typing import ClassVar

import flet as ft
import httpx
import pytest
from httpx import ASGITransport

from livraison.interfaces import formats
from livraison.interfaces.api_client import ApiClient, ErreurApi
from livraison.interfaces.application import Application, creer_application
from livraison.interfaces.composants import ChampLieu, textes
from livraison.interfaces.espace_client import EspaceClient
from livraison.interfaces.espace_livreur import EspaceLivreur
from livraison.interfaces.espace_supervision import EspaceSupervision
from test_api_courses import Scenario


class _TacheNulle:
    def cancel(self):
        pass


class PageFactice:
    """Juste ce que les écrans utilisent de `ft.Page`."""

    def __init__(self, executer_taches: bool = False):
        self.controls: list = []
        self.appbar = self.navigation_bar = self.on_disconnect = None
        self.title, self.theme_mode, self.padding = "", None, None
        self.dialogs: list = []
        self.mises_a_jour = 0
        self.taches: list = []
        self._executer = executer_taches

    def add(self, *controles):
        self.controls.extend(controles)

    def clean(self):
        self.controls.clear()

    def update(self, *_):
        self.mises_a_jour += 1

    def show_dialog(self, dialogue):
        self.dialogs.append(dialogue)

    def pop_dialog(self):
        return self.dialogs.pop() if self.dialogs else None

    def run_task(self, fonction, *args, **options):
        if self._executer:
            tache = asyncio.get_running_loop().create_task(fonction(*args, **options))
            self.taches.append(tache)
            return tache
        return _TacheNulle()

    def message(self) -> str:
        """Texte du dernier message affiché (SnackBar)."""
        snack = next((d for d in reversed(self.dialogs) if isinstance(d, ft.SnackBar)), None)
        return " ".join(textes(snack)) if snack else ""

    def texte_ecran(self) -> str:
        return " | ".join(textes(ft.Column(self.controls)))


# --------------------------------------------------------------------------- données simulées
class FauxApi:
    """Réponses réalistes de l'API, pour construire et afficher tous les écrans sans serveur."""

    def __init__(self):
        self.appels: list = []

    def __getattr__(self, nom):
        async def appel(*args, **options):
            self.appels.append((nom, args, options))
            return getattr(self, f"_{nom}", lambda *a, **k: None)(*args, **options)

        return appel

    LIEU: ClassVar[dict] = {"adresse": "Plateau, Abidjan", "longitude": -4.02, "latitude": 5.32}

    def _commande(self, *a, **k):
        return {
            "id": "c1",
            "numero": 1000,
            "etat": "attribuee",
            "enlevement": self.LIEU,
            "livraison": {**self.LIEU, "adresse": "Cocody, Abidjan"},
            "taille_colis": "petit",
            "description_colis": None,
            "consignes": None,
            "destinataire_nom": "Awa",
            "destinataire_telephone": "+2250711223344",
            "prix": 1750,
            "distance_m": 8100,
            "duree_estimee_s": 1100,
            "mode_paiement": "especes",
            "priorite": "normale",
            "cree_le": "2026-11-14T10:00:00Z",
            "attribuee_le": None,
            "enlevee_le": None,
            "livree_le": None,
            "annulee_le": None,
            "livreur": {
                "nom": "Moussa",
                "telephone": "+2250700000001",
                "type_vehicule": "moto",
                "note": 4.5,
                "position": {"longitude": -4.01, "latitude": 5.33, "age_s": 3.2},
            },
        }

    def _creer_commande(self, corps):
        return {**self._commande(), "code_remise": "4821"}

    def _mes_commandes(self):
        return [
            {
                "id": "c1",
                "numero": 1000,
                "etat": "en_recherche",
                "prix": 1750,
                "adresse_enlevement": "Plateau, Abidjan",
                "adresse_livraison": "Cocody, Abidjan",
                "cree_le": "2026-11-14T10:00:00Z",
            }
        ]

    def _estimer(self, *a):
        return {"prix": 1750, "distance_m": 8100, "duree_estimee_s": 1100}

    def _mon_dossier(self):
        return {
            "utilisateur_id": "u1",
            "type_vehicule": "moto",
            "capacite_courses": 2,
            "taille_colis_max": "moyen",
            "pieces": [],
            "statut_validation": "valide",
            "valide_le": None,
            "note": None,
            "en_ligne": True,
        }

    def _mes_courses(self):
        return {
            "propositions": [
                {
                    "commande_id": "c2",
                    "numero": 1001,
                    "adresse_enlevement": "Plateau, Abidjan",
                    "adresse_livraison": "Cocody, Abidjan",
                    "enlevement": {"longitude": -4.0, "latitude": 5.3},
                    "livraison": {"longitude": -3.9, "latitude": 5.3},
                    "prix": 1750,
                    "expire_dans_s": 24.0,
                }
            ],
            "en_cours": [
                {
                    "commande_id": "c1",
                    "numero": 1000,
                    "etat": etat,
                    "enlevement": self.LIEU,
                    "livraison": {**self.LIEU, "adresse": "Cocody, Abidjan"},
                    "destinataire_nom": "Awa",
                    "destinataire_telephone": "+2250711223344",
                    "consignes": "Sonner deux fois",
                    "prix": 1750,
                    "mode_paiement": "especes",
                }
                for etat in ("attribuee", "enlevee", "en_livraison")
            ],
        }

    def _alertes(self):
        return [
            {
                "commande_id": "c1",
                "numero": 1000,
                "etat": "en_recherche",
                "raison": "attribution_impossible",
                "cree_le": "2026-11-14T10:00:00Z",
            },
            {
                "commande_id": "c3",
                "numero": 1002,
                "etat": "echec_livraison",
                "raison": "echec_apres_enlevement",
                "cree_le": "2026-11-14T10:05:00Z",
            },
        ]

    def _dossiers(self, statut="en_attente"):
        return [
            {
                "utilisateur_id": "u1",
                "nom": "Moussa",
                "telephone": "+2250700000001",
                "type_vehicule": "moto",
                "capacite_courses": 2,
                "taille_colis_max": "moyen",
                "pieces": [{"type": "permis", "reference": "P-1"}],
                "statut_validation": "en_attente",
                "valide_le": None,
                "note": None,
                "en_ligne": False,
            }
        ]

    def _toutes_les_commandes(self, etat=None):
        return self._mes_commandes()

    def _livreurs_en_ligne(self):
        return [
            {
                "livreur_id": "u1",
                "nom": "Moussa",
                "telephone": "+2250700000001",
                "longitude": -4.01,
                "latitude": 5.33,
                "age_position_s": 4.0,
                "vehicule": "moto",
            }
        ]


# --------------------------------------------------------------------------- tests sans serveur
def test_formats():
    assert formats.prix(1750) == "1 750 F" and formats.prix(None) == "-"
    assert formats.distance(8100) == "8,1 km"
    assert (
        formats.duree(1100) == "18 min"
        and formats.duree(4000) == "1 h 07"
        and formats.duree(10) == "1 min"
    )
    assert formats.il_y_a(2) == "à l'instant" and formats.il_y_a(32.4) == "il y a 32 s"
    assert formats.libelle_etat("en_recherche") == "Recherche d'un livreur"
    assert formats.avancement("livree") == 1.0 and formats.avancement("inconnu") == 0.0
    assert formats.heure(None) == "-" and ":" in formats.heure("2026-11-14T10:00:00Z")


def test_champ_lieu():
    champ = ChampLieu("Enlèvement (commune)", lambda: None)
    with pytest.raises(ValueError, match="Choisissez le lieu"):
        champ.lieu()
    champ.liste.value = "Cocody"
    assert champ.lieu() == {"adresse": "Cocody, Abidjan", "longitude": -3.987, "latitude": 5.348}
    champ.detail.value = "Rue des Jardins"
    assert champ.lieu()["adresse"] == "Rue des Jardins, Cocody"

    champ.liste.value = "autre"
    champ._choisi()
    assert champ.longitude.visible and champ.latitude.visible
    with pytest.raises(ValueError, match="longitude et une latitude"):
        champ.lieu()
    champ.longitude.value, champ.latitude.value = "-4,0267", "5.32"  # virgule décimale acceptée
    assert champ.lieu()["longitude"] == -4.0267
    champ.latitude.value = "95"
    with pytest.raises(ValueError, match="hors limites"):
        champ.lieu()
    champ.vider()
    assert champ.liste.value is None and not champ.longitude.visible


async def test_client_api_traduit_les_erreurs():
    def reponse(requete: httpx.Request) -> httpx.Response:
        chemin = requete.url.path
        if chemin == "/refus":
            return httpx.Response(403, json={"detail": "Droits insuffisants."})
        if chemin == "/invalide":
            return httpx.Response(
                422, json={"detail": [{"loc": ["body", "telephone"], "msg": "trop court"}]}
            )
        if chemin == "/livreurs/moi/dossier":
            return httpx.Response(404, json={"detail": "Aucun dossier déposé."})
        if chemin == "/panne":
            return httpx.Response(500, text="boom")
        raise httpx.ConnectError("refusé")

    api = ApiClient("http://x", transport=httpx.MockTransport(reponse))
    with pytest.raises(ErreurApi) as e:
        await api._appel("GET", "/refus")
    assert (e.value.statut, e.value.detail) == (403, "Droits insuffisants.")
    with pytest.raises(ErreurApi) as e:
        await api._appel("POST", "/invalide")
    assert "telephone trop court" in e.value.detail
    with pytest.raises(ErreurApi) as e:
        await api._appel("GET", "/panne")
    assert e.value.statut == 500
    with pytest.raises(ErreurApi) as e:
        await api._appel("GET", "/injoignable")
    assert e.value.statut == 0 and "injoignable" in e.value.detail
    assert await api.mon_dossier() is None  # 404 = pas encore de dossier


async def test_chaque_ecran_se_construit_avec_des_donnees_reelles():
    """Construit toutes les vues : tout paramètre de contrôle invalide lèverait une erreur ici."""
    page, api = PageFactice(), FauxApi()

    client = EspaceClient(page, api)
    page.add(client.build())
    client.installer_navigation()
    await client.demarrer()
    assert "Nouvelle livraison" in page.texte_ecran() and page.navigation_bar is not None
    client.codes["c1"] = "4821"
    await client.aller("suivi", "c1")
    ecran = page.texte_ecran()
    assert "Commande n°1000" in ecran and "1 750 F" in ecran and "4821" in ecran
    assert "Votre livreur" in ecran and "Moussa" in ecran and "Annuler la commande" in ecran
    await client.aller("commandes")
    assert "N°1000" in page.texte_ecran()
    await client.demander_annulation("c1")
    assert isinstance(page.dialogs[-1], ft.AlertDialog)
    client.arreter()

    page = PageFactice()
    livreur = EspaceLivreur(page, api)
    page.add(livreur.build())
    livreur.installer_navigation()
    await livreur.demarrer()
    ecran = page.texte_ecran()
    assert "Nouvelle course" in ecran and "Accepter" in ecran and "À confirmer dans 24 s" in ecran
    assert "J'ai enlevé le colis" in ecran and "Je pars livrer" in ecran and "Colis livré" in ecran
    assert "Sonner deux fois" in ecran and "En ligne" in ecran
    await livreur.aller("dossier")
    assert "Modifier mon dossier" in page.texte_ecran()
    await livreur.modifier_dossier()
    assert "Envoyer mon dossier" in page.texte_ecran()
    await livreur.demander_code("c1")
    await livreur.demander_motif("c1")
    livreur.arreter()

    page = PageFactice()
    supervision = EspaceSupervision(page, api)
    page.add(supervision.build())
    supervision.installer_navigation()
    await supervision.demarrer()
    assert "Alertes (2)" in page.texte_ecran() and "Relancer la recherche" in page.texte_ecran()
    assert "Aucun livreur disponible" in page.texte_ecran()
    await supervision.aller("dossiers")
    assert "Moussa" in page.texte_ecran() and "Valider" in page.texte_ecran()
    await supervision.aller("commandes")
    assert "N°1000" in page.texte_ecran()
    await supervision.ouvrir_detail("c1")
    await supervision.aller("en_ligne")
    assert "Moussa" in page.texte_ecran()
    supervision.arreter()


async def test_ecran_de_connexion_et_cycle_de_vie():
    page, api = (
        PageFactice(executer_taches=True),
        ApiClient(
            "http://x", transport=httpx.MockTransport(lambda r: httpx.Response(200, json={}))
        ),
    )
    await creer_application("http://127.0.0.1:8000")(page)
    assert page.title == "Livraison SMA" and page.on_disconnect is not None
    assert "Connexion" in page.texte_ecran()

    application = Application(page, api)
    application.afficher_connexion()
    await application.demander_code()
    assert "numéro" in application.erreur.value  # numéro vide
    await application.fin_de_session()


async def test_l_actualisation_periodique_s_arrete_avec_l_espace():
    page, api = PageFactice(executer_taches=True), FauxApi()
    espace = EspaceClient(page, api)
    await espace.demarrer()
    assert len(espace._taches) == 1 and not espace._taches[0].done()
    espace.arreter()
    await asyncio.sleep(0.05)
    assert espace.actif is False and not espace._taches and page.taches[0].cancelled()


async def test_une_erreur_de_l_api_est_affichee_pas_propagee():
    class ApiEnPanne(FauxApi):
        async def creer_commande(self, corps):
            raise ErreurApi(503, "Le service d'attribution des courses est indisponible.")

    page, api = PageFactice(), ApiEnPanne()
    espace = EspaceClient(page, api)
    espace.lieu_enlevement.liste.value, espace.lieu_livraison.liste.value = "Plateau", "Cocody"
    await espace.commander()
    assert "indisponible" in page.message() and espace.vue == "commander"
    espace.lieu_livraison.liste.value = None
    await espace.commander()
    assert "Choisissez le lieu" in page.message()


# --------------------------------------------------------------------------- parcours complet
async def jusqu_a(condition, espace, timeout=25):
    """Actualise l'écran (comme le ferait la boucle périodique) jusqu'à ce que `condition` soit vraie."""
    async with asyncio.timeout(timeout):
        while True:
            await espace.rafraichir()
            if condition():
                return
            await asyncio.sleep(0.2)


async def ouvrir_session(
    application: Application, telephone: str, role: str, nom: str | None = None
):
    application.afficher_connexion()
    application.champ_telephone.value = telephone
    await application.demander_code()
    assert application.champ_code.value  # le mode développement pré-remplit le code
    application.choix_role.value, application.champ_nom.value = role, nom or ""
    await application.connecter()
    return application.espace


async def test_parcours_complet_ecran_par_ecran(creer_api):
    from livraison.api.main import app

    api_http = await creer_api()
    scenario = Scenario(api_http)
    await scenario.administrateur(
        "07 00 00 99 99"
    )  # le compte administrateur se crée hors inscription

    def ouvrir(telephone, role, nom=None):
        page = PageFactice()
        application = Application(page, ApiClient("http://test", transport=ASGITransport(app=app)))
        return page, application, ouvrir_session(application, telephone, role, nom)

    page_a, app_a, ouverture = ouvrir("07 00 00 99 99", "client")
    admin = await ouverture
    assert isinstance(admin, EspaceSupervision) and "Alertes" in page_a.texte_ecran()

    page_l, app_l, ouverture = ouvrir("07 00 00 30 01", "livreur", "Moussa Livreur")
    livreur = await ouverture
    assert (
        isinstance(livreur, EspaceLivreur)
        and "Déposez d'abord votre dossier" in page_l.texte_ecran()
    )

    page_c, app_c, ouverture = ouvrir("07 00 00 30 02", "client", "Awa Cliente")
    client = await ouverture
    assert isinstance(client, EspaceClient) and "Nouvelle livraison" in page_c.texte_ecran()
    assert "Awa Cliente · Client" in textes(page_c.appbar)[0]

    # 1. Le livreur dépose son dossier, l'administrateur le valide.
    await livreur.aller("dossier")
    livreur.piece_reference.value = "P-123"
    await livreur.enregistrer_dossier()
    assert "En attente de validation" in page_l.texte_ecran()

    await admin.aller("dossiers")
    assert "Moussa Livreur" in page_a.texte_ecran() and "permis P-123" in page_a.texte_ecran()
    await admin.decider(admin.donnees["dossiers"][0]["utilisateur_id"], "valide")
    assert "Aucun dossier en attente" in page_a.texte_ecran()

    # 2. Le livreur se met en ligne près du Plateau ; la supervision le voit.
    await livreur.aller("courses")
    await livreur.deplacer_vers("Plateau")
    await livreur.basculer_en_ligne(True)
    assert livreur.en_ligne and livreur.interrupteur.value
    await admin.aller("en_ligne")
    assert "Moussa Livreur" in page_a.texte_ecran()

    # 3. Le client estime puis commande.
    client.lieu_enlevement.liste.value, client.lieu_enlevement.detail.value = (
        "Plateau",
        "Rue du Commerce",
    )
    client.lieu_livraison.liste.value = "Cocody"
    client.destinataire_nom.value, client.destinataire_telephone.value = "Koffi", "07 11 22 33 44"
    client.consignes.value = "Sonner deux fois"
    await client.estimer()
    assert " F" in client.texte_estimation.value and client.estimation["prix"] >= 500
    await client.commander()
    assert client.vue == "suivi" and "Commande enregistrée" not in page_c.message()
    cid = client.commande_id
    code = client.codes[cid]
    assert (
        len(code) == 4 and code in page_c.texte_ecran() and "Code de remise" in page_c.texte_ecran()
    )

    # 4. Le livreur voit la proposition et l'accepte.
    await jusqu_a(lambda: bool(livreur.courses["propositions"]), livreur)
    assert "Rue du Commerce, Plateau" in page_l.texte_ecran() and "Accepter" in page_l.texte_ecran()
    await livreur.repondre(cid, True)
    await jusqu_a(lambda: "Votre livreur" in page_c.texte_ecran(), client)
    assert (
        "Moussa Livreur" in page_c.texte_ecran()
        and "Livreur en route vers l'enlèvement" in page_c.texte_ecran()
    )

    # 5. Enlèvement, départ, puis livraison : un faux code est refusé, le bon accepté.
    await jusqu_a(
        lambda: any(c["etat"] == "attribuee" for c in livreur.courses["en_cours"]), livreur
    )
    assert (
        "J'ai enlevé le colis" in page_l.texte_ecran()
        and "Sonner deux fois" in page_l.texte_ecran()
    )
    await livreur.signaler(cid, "enlevee")
    await jusqu_a(lambda: any(c["etat"] == "enlevee" for c in livreur.courses["en_cours"]), livreur)
    await livreur.signaler(cid, "en_livraison")
    await jusqu_a(
        lambda: any(c["etat"] == "en_livraison" for c in livreur.courses["en_cours"]), livreur
    )

    await livreur.demander_code(cid)
    livreur.champ_code.value = "0000" if code != "0000" else "1111"
    await livreur.confirmer_livraison(cid)
    assert "incorrect" in page_l.message()
    assert isinstance(page_l.dialogs[-2], ft.AlertDialog)  # la fenêtre reste ouverte pour corriger
    livreur.champ_code.value = code
    await livreur.confirmer_livraison(cid)
    assert "Livraison enregistrée" in page_l.message()

    # 6. Le client voit « Livrée », la supervision aussi.
    await jusqu_a(lambda: "Livrée" in page_c.texte_ecran(), client)
    assert code not in page_c.texte_ecran()  # le code n'est plus affiché une fois livré
    await admin.aller("commandes")
    assert "Livrée" in page_a.texte_ecran()
    await admin.filtrer("livree")
    assert "N°" in page_a.texte_ecran()

    # 7. Hors ligne, déconnexion : le serveur n'a plus d'agent pour ce livreur.
    await livreur.basculer_en_ligne(False)
    assert not livreur.en_ligne and api_http.flotte.livreurs == {}
    await app_l.deconnecter()
    assert "Connexion" in page_l.texte_ecran() and app_l.api.jeton is None
    for application in (app_a, app_l, app_c):
        await application.fin_de_session()


async def test_alerte_relance_et_annulation_depuis_les_ecrans(creer_api):
    from livraison.api.main import app

    api_http = await creer_api(tentatives_attribution_max=2, delai_relance_s=0.2)
    scenario = Scenario(api_http)
    await scenario.administrateur("07 00 00 99 98")

    def ouvrir(telephone, role):
        page = PageFactice()
        application = Application(page, ApiClient("http://test", transport=ASGITransport(app=app)))
        return page, application, ouvrir_session(application, telephone, role)

    page_a, app_a, ouverture = ouvrir("07 00 00 99 98", "client")
    admin = await ouverture
    page_c, app_c, ouverture = ouvrir("07 00 00 30 03", "client")
    client = await ouverture

    client.lieu_enlevement.liste.value = client.lieu_livraison.liste.value = None
    client.lieu_enlevement.liste.value, client.lieu_livraison.liste.value = "Plateau", "Marcory"
    await client.commander()
    cid = client.commande_id

    # Aucun livreur en ligne : la commande finit en alerte pour le répartiteur.
    await admin.aller("alertes")
    await jusqu_a(lambda: "Aucun livreur disponible" in page_a.texte_ecran(), admin)
    assert "Relancer la recherche" in page_a.texte_ecran()
    await admin.relancer(cid)
    assert "relancée" in page_a.message()

    # Le client change d'avis : l'annulation retire l'alerte.
    await client.annuler(cid)
    await jusqu_a(lambda: "Annulée" in page_c.texte_ecran(), client)
    assert "Annulée" in page_c.texte_ecran() and "Annuler la commande" not in page_c.texte_ecran()
    await jusqu_a(lambda: "Aucune alerte" in page_a.texte_ecran(), admin)
    for application in (app_a, app_c):
        await application.fin_de_session()
