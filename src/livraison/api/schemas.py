"""Formats d'échange de l'API."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from livraison.db.modeles import StatutValidation, TailleColis, TypeVehicule


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


class DecisionValidation(BaseModel):
    decision: Literal["valide", "refuse"]
