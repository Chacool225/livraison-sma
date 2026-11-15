"""Client de l'API pour les interfaces : un petit objet qui parle HTTP et traduit les erreurs.

Les écrans n'écrivent jamais d'URL : ils appellent des méthodes (`creer_commande`, `repondre`...).
"""

import uuid
from typing import Any

import httpx


class ErreurApi(Exception):
    """Réponse d'erreur de l'API (ou serveur injoignable : statut 0). `detail` est affichable."""

    def __init__(self, statut: int, detail: str):
        super().__init__(detail)
        self.statut = statut
        self.detail = detail


def _lire_detail(reponse: httpx.Response) -> str:
    try:
        detail = reponse.json().get("detail")
    except (ValueError, AttributeError):
        return f"Erreur {reponse.status_code}"
    if isinstance(detail, list):  # erreurs de validation de FastAPI
        return "Données invalides : " + " ; ".join(
            f"{'.'.join(str(x) for x in e.get('loc', [])[1:])} {e.get('msg', '')}".strip()
            for e in detail
        )
    return str(detail) if detail else f"Erreur {reponse.status_code}"


class ApiClient:
    def __init__(
        self,
        base_url: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        delai_s: float = 10.0,
    ):
        self._http = httpx.AsyncClient(base_url=base_url, transport=transport, timeout=delai_s)
        self.jeton: str | None = None
        self.utilisateur: dict | None = None

    async def fermer(self) -> None:
        await self._http.aclose()

    async def _appel(self, methode: str, chemin: str, **options) -> Any:
        entetes = {"Authorization": f"Bearer {self.jeton}"} if self.jeton else {}
        try:
            reponse = await self._http.request(methode, chemin, headers=entetes, **options)
        except httpx.HTTPError as erreur:
            raise ErreurApi(0, "Serveur injoignable : l'API est-elle lancée ?") from erreur
        if reponse.status_code >= 400:
            raise ErreurApi(reponse.status_code, _lire_detail(reponse))
        return reponse.json() if reponse.content else None

    # ------------------------------------------------------------------ connexion
    async def etat_serveur(self) -> dict:
        return await self._appel("GET", "/sante")

    async def demander_code(self, telephone: str) -> dict:
        return await self._appel("POST", "/auth/demander-code", json={"telephone": telephone})

    async def se_connecter(self, telephone: str, code: str, role: str, nom: str | None) -> dict:
        donnees = await self._appel(
            "POST",
            "/auth/verifier-code",
            json={"telephone": telephone, "code": code, "role": role, "nom": nom or None},
        )
        self.jeton, self.utilisateur = donnees["access_token"], donnees["utilisateur"]
        return donnees["utilisateur"]

    def deconnecter(self) -> None:
        self.jeton = self.utilisateur = None

    # ------------------------------------------------------------------ client
    async def estimer(self, enlevement: dict, livraison: dict) -> dict:
        coordonnees = lambda lieu: {"longitude": lieu["longitude"], "latitude": lieu["latitude"]}
        return await self._appel(
            "POST",
            "/commandes/estimation",
            json={"enlevement": coordonnees(enlevement), "livraison": coordonnees(livraison)},
        )

    async def creer_commande(self, corps: dict) -> dict:
        return await self._appel("POST", "/commandes", json=corps)

    async def mes_commandes(self) -> list[dict]:
        return await self._appel("GET", "/commandes", params={"limite": 50})

    async def commande(self, commande_id: str | uuid.UUID) -> dict:
        return await self._appel("GET", f"/commandes/{commande_id}")

    async def annuler(self, commande_id: str | uuid.UUID) -> dict:
        return await self._appel("POST", f"/commandes/{commande_id}/annulation")

    # ------------------------------------------------------------------ livreur
    async def mon_dossier(self) -> dict | None:
        try:
            return await self._appel("GET", "/livreurs/moi/dossier")
        except ErreurApi as erreur:
            if erreur.statut == 404:
                return None
            raise

    async def deposer_dossier(self, corps: dict) -> dict:
        return await self._appel("PUT", "/livreurs/moi/dossier", json=corps)

    async def passer_en_ligne(self, longitude: float, latitude: float) -> dict:
        return await self._appel(
            "POST", "/livreurs/moi/en-ligne", json={"longitude": longitude, "latitude": latitude}
        )

    async def passer_hors_ligne(self) -> dict:
        return await self._appel("POST", "/livreurs/moi/hors-ligne")

    async def envoyer_position(self, longitude: float, latitude: float) -> dict:
        return await self._appel(
            "PUT", "/livreurs/moi/position", json={"longitude": longitude, "latitude": latitude}
        )

    async def mes_courses(self) -> dict:
        return await self._appel("GET", "/livreurs/moi/courses")

    async def repondre(self, commande_id: str, accepte: bool) -> dict:
        return await self._appel(
            "POST", f"/livreurs/moi/courses/{commande_id}/reponse", json={"accepte": accepte}
        )

    async def signaler_etape(
        self, commande_id: str, etape: str, code: str | None = None, motif: str | None = None
    ) -> dict:
        return await self._appel(
            "POST",
            f"/livreurs/moi/courses/{commande_id}/etape",
            json={"etape": etape, "code": code or None, "motif": motif or None},
        )

    # ------------------------------------------------------------------ supervision
    async def dossiers(self, statut: str = "en_attente") -> list[dict]:
        return await self._appel("GET", "/admin/livreurs", params={"statut": statut})

    async def decider_dossier(self, utilisateur_id: str, decision: str) -> dict:
        return await self._appel(
            "POST", f"/admin/livreurs/{utilisateur_id}/validation", json={"decision": decision}
        )

    async def toutes_les_commandes(self, etat: str | None = None) -> list[dict]:
        return await self._appel(
            "GET",
            "/admin/commandes",
            params={"etat": etat, "limite": 100} if etat else {"limite": 100},
        )

    async def livreurs_en_ligne(self) -> list[dict]:
        return await self._appel("GET", "/admin/agents")

    async def alertes(self) -> list[dict]:
        return await self._appel("GET", "/admin/alertes")

    async def relancer(self, commande_id: str) -> dict:
        return await self._appel("POST", f"/admin/commandes/{commande_id}/relance")
