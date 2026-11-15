"""Formats d'échange de l'API."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from livraison.db.modeles import (
    EtatCommande,
    ModePaiement,
    Priorite,
    StatutValidation,
    TailleColis,
    TypeVehicule,
)


class DemandeCode(BaseModel):
    telephone: str


class ReponseDemandeCode(BaseModel):
    message: str
    code_dev: str | None = Field(None, description="Présent uniquement en environnement « dev ».")


class VerificationCode(BaseModel):
    telephone: str
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")
    # Rôle d'un NOUVEAU compte. Les rôles répartiteur et administrateur ne s'obtiennent pas ici.
    role: Literal["client", "livreur"] = "client"
    nom: str | None = Field(None, max_length=120)


class UtilisateurSortie(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    telephone: str
    nom: str | None
    role: str
    statut: str


class Jeton(BaseModel):
    access_token: str
    token_type: str = "bearer"
    utilisateur: UtilisateurSortie


class Piece(BaseModel):
    type: str = Field(max_length=40, examples=["permis", "carte_identite"])
    reference: str = Field(max_length=80)


class DossierLivreur(BaseModel):
    type_vehicule: TypeVehicule
    capacite_courses: int = Field(3, ge=1, le=10)
    taille_colis_max: TailleColis = TailleColis.MOYEN
    pieces: list[Piece] = Field(default_factory=list, max_length=10)


class DossierLivreurSortie(DossierLivreur):
    model_config = ConfigDict(from_attributes=True)

    utilisateur_id: uuid.UUID
    statut_validation: StatutValidation
    valide_le: datetime | None
    note: float | None
    en_ligne: bool = False


class DossierAValider(DossierLivreurSortie):
    nom: str | None
    telephone: str


class DecisionValidation(BaseModel):
    decision: Literal["valide", "refuse"]


# --------------------------------------------------------------------------- commandes
class Coordonnees(BaseModel):
    longitude: float = Field(ge=-180, le=180, examples=[-4.0267])
    latitude: float = Field(ge=-90, le=90, examples=[5.32])


class Lieu(Coordonnees):
    adresse: str = Field(min_length=1, max_length=300, examples=["Plateau, Abidjan"])


class NouvelleCommande(BaseModel):
    enlevement: Lieu
    livraison: Lieu
    taille_colis: TailleColis
    description_colis: str | None = Field(None, max_length=500)
    consignes: str | None = Field(None, max_length=500)
    destinataire_nom: str | None = Field(None, max_length=120)
    destinataire_telephone: str | None = Field(None, max_length=25)
    mode_paiement: Literal["especes"] = "especes"  # les autres modes viendront avec le lot paiement


class PositionLivreur(Coordonnees):
    age_s: float | None


class LivreurDeLaCommande(BaseModel):
    nom: str | None
    telephone: str
    type_vehicule: TypeVehicule
    note: float | None
    position: PositionLivreur | None


class CommandeDetail(BaseModel):
    id: uuid.UUID
    numero: int
    etat: EtatCommande
    enlevement: Lieu
    livraison: Lieu
    taille_colis: TailleColis
    description_colis: str | None
    consignes: str | None
    destinataire_nom: str | None
    destinataire_telephone: str | None
    prix: int = Field(description="Francs CFA")
    distance_m: int | None
    duree_estimee_s: int | None
    mode_paiement: ModePaiement
    priorite: Priorite
    cree_le: datetime
    attribuee_le: datetime | None
    enlevee_le: datetime | None
    livree_le: datetime | None
    annulee_le: datetime | None
    livreur: LivreurDeLaCommande | None


class CommandeCreee(CommandeDetail):
    code_remise: str = Field(
        description="À donner au destinataire : le livreur doit le saisir à la livraison. Affiché une seule fois."
    )


class CommandeResume(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    numero: int
    etat: EtatCommande
    prix: int
    adresse_enlevement: str
    adresse_livraison: str
    cree_le: datetime


class DemandeEstimation(BaseModel):
    enlevement: Coordonnees
    livraison: Coordonnees


class Estimation(BaseModel):
    prix: int = Field(description="Francs CFA")
    distance_m: int
    duree_estimee_s: int


class AlerteSortie(BaseModel):
    commande_id: uuid.UUID
    numero: int
    etat: EtatCommande
    raison: str | None
    cree_le: datetime


class AgentEnLigne(BaseModel):
    livreur_id: str
    nom: str | None = None
    telephone: str | None = None
    longitude: float
    latitude: float
    age_position_s: float | None
    vehicule: str


# --------------------------------------------------------------------------- courses du livreur
class PositionIn(Coordonnees):
    precision_m: float | None = Field(None, ge=0)


class PropositionSortie(BaseModel):
    commande_id: uuid.UUID
    numero: int
    adresse_enlevement: str
    adresse_livraison: str
    enlevement: Coordonnees
    livraison: Coordonnees
    prix: int
    expire_dans_s: float


class CourseSortie(BaseModel):
    commande_id: uuid.UUID
    numero: int
    etat: EtatCommande
    enlevement: Lieu
    livraison: Lieu
    destinataire_nom: str | None
    destinataire_telephone: str | None
    consignes: str | None
    prix: int
    mode_paiement: ModePaiement


class MesCourses(BaseModel):
    propositions: list[PropositionSortie]
    en_cours: list[CourseSortie]


class ReponseProposition(BaseModel):
    accepte: bool


class EtapeIn(BaseModel):
    etape: Literal["enlevee", "en_livraison", "livree", "echec"]
    code: str | None = Field(
        None, pattern=r"^\d{4}$", description="Code de remise (étape « livree »)"
    )
    motif: str | None = Field(None, max_length=300)
