"""Modèle de données (cahier des charges, § 7.1) : PostgreSQL + PostGIS.

Conventions : identifiants UUID pour les entités exposées, horodatages avec fuseau horaire,
montants en francs CFA (entiers), coordonnées en WGS 84 (longitude, latitude) dans des colonnes
`Geography`, qui permettent des distances en mètres.
"""

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from geoalchemy2 import Geography
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from livraison.db.base import Base


# ----------------------------------------------------------------------------- énumérations
class Role(str, enum.Enum):
    CLIENT = "client"
    LIVREUR = "livreur"
    REPARTITEUR = "repartiteur"
    ADMINISTRATEUR = "administrateur"


class StatutCompte(str, enum.Enum):
    ACTIF = "actif"
    SUSPENDU = "suspendu"


class TypeVehicule(str, enum.Enum):
    VELO = "velo"
    MOTO = "moto"
    VOITURE = "voiture"


class TailleColis(str, enum.Enum):
    PETIT = "petit"
    MOYEN = "moyen"
    GRAND = "grand"


class StatutValidation(str, enum.Enum):
    EN_ATTENTE = "en_attente"
    VALIDE = "valide"
    REFUSE = "refuse"


class Priorite(str, enum.Enum):
    NORMALE = "normale"
    URGENTE = "urgente"


class EtatCommande(str, enum.Enum):
    """Cycle de vie (§ 3.4) : Créée → Validée → En recherche → Attribuée → Enlevée →
    En livraison → Livrée → Clôturée ; états d'exception : Annulée, Échec, Litige."""

    CREEE = "creee"
    VALIDEE = "validee"
    EN_RECHERCHE = "en_recherche"
    ATTRIBUEE = "attribuee"
    ENLEVEE = "enlevee"
    EN_LIVRAISON = "en_livraison"
    LIVREE = "livree"
    CLOTUREE = "cloturee"
    ANNULEE = "annulee"
    ECHEC_LIVRAISON = "echec_livraison"
    LITIGE = "litige"


class ResultatOffre(str, enum.Enum):
    PROPOSEE = "proposee"  # offre faite, pas encore tranchée
    RETENUE = "retenue"  # acceptée par le dispatcher
    REJETEE = "rejetee"  # une meilleure offre a été retenue
    REFUSEE = "refusee"  # l'agent livreur a refusé de proposer (saturé, hors zone...)
    DECLINEE = "declinee"  # le livreur humain a décliné la course
    EXPIREE = "expiree"  # le livreur humain n'a pas répondu à temps


class ModePaiement(str, enum.Enum):
    ESPECES = "especes"
    MOBILE_MONEY = "mobile_money"
    CARTE = "carte"


class EtatPaiement(str, enum.Enum):
    EN_ATTENTE = "en_attente"
    CONFIRME = "confirme"
    ECHOUE = "echoue"
    REMBOURSE = "rembourse"


def _enum(cls: type[enum.Enum]) -> SAEnum:
    """Énumération stockée en texte avec une contrainte CHECK (plus simple à faire évoluer
    qu'un type ENUM natif de PostgreSQL)."""
    return SAEnum(
        cls,
        name=cls.__name__.lower(),
        native_enum=False,
        length=30,
        create_constraint=True,
        validate_strings=True,
        values_callable=lambda e: [m.value for m in e],
    )


def _horodatage() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


def _point() -> Mapped[str]:
    # L'index spatial est déclaré explicitement dans __table_args__ (spatial_index=False ici).
    return mapped_column(Geography("POINT", srid=4326, spatial_index=False))


_UUID_PK = {"primary_key": True, "default": uuid.uuid4, "server_default": text("gen_random_uuid()")}


# ----------------------------------------------------------------------------- comptes
class Utilisateur(Base):
    __tablename__ = "utilisateurs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **_UUID_PK)
    telephone: Mapped[str] = mapped_column(String(20), unique=True)  # format E.164 : +2250700000000
    nom: Mapped[str | None] = mapped_column(String(120))
    role: Mapped[Role] = mapped_column(_enum(Role), default=Role.CLIENT)
    statut: Mapped[StatutCompte] = mapped_column(_enum(StatutCompte), default=StatutCompte.ACTIF)
    cree_le: Mapped[datetime] = _horodatage()
    derniere_connexion: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CodeVerification(Base):
    """Code à usage unique envoyé par SMS. Seul son empreinte est stockée."""

    __tablename__ = "codes_verification"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    telephone: Mapped[str] = mapped_column(String(20))
    code_hash: Mapped[str] = mapped_column(String(64))
    expire_le: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    tentatives: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    utilise: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    cree_le: Mapped[datetime] = _horodatage()

    __table_args__ = (Index("ix_codes_verification_telephone_cree_le", "telephone", "cree_le"),)


class Livreur(Base):
    """Dossier du livreur (F-03). Un livreur ne peut recevoir de course qu'une fois validé."""

    __tablename__ = "livreurs"

    utilisateur_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("utilisateurs.id", ondelete="CASCADE"), primary_key=True
    )
    type_vehicule: Mapped[TypeVehicule] = mapped_column(_enum(TypeVehicule))
    capacite_courses: Mapped[int] = mapped_column(Integer, default=3, server_default="3")
    taille_colis_max: Mapped[TailleColis] = mapped_column(
        _enum(TailleColis), default=TailleColis.MOYEN, server_default="moyen"
    )
    pieces: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    statut_validation: Mapped[StatutValidation] = mapped_column(
        _enum(StatutValidation),
        default=StatutValidation.EN_ATTENTE,
        server_default="en_attente",
    )
    valide_par: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("utilisateurs.id"))
    valide_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))  # moyenne des évaluations, 0 à 5
    nb_evaluations: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    en_ligne: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    cree_le: Mapped[datetime] = _horodatage()
    modifie_le: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint("capacite_courses > 0", name="capacite_positive"),
        CheckConstraint("note IS NULL OR (note >= 0 AND note <= 5)", name="note_0_a_5"),
    )


class Position(Base):
    """Historique des positions GPS (les positions « en direct » vivent dans Redis)."""

    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    livreur_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("livreurs.utilisateur_id", ondelete="CASCADE")
    )
    point: Mapped[str] = _point()
    precision_m: Mapped[float | None] = mapped_column(Numeric(7, 1))
    enregistree_le: Mapped[datetime] = _horodatage()

    __table_args__ = (
        Index("ix_positions_livreur_id_enregistree_le", "livreur_id", "enregistree_le"),
        Index("ix_positions_point", "point", postgresql_using="gist"),
    )


# ----------------------------------------------------------------------------- commandes
class Commande(Base):
    __tablename__ = "commandes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **_UUID_PK)
    numero: Mapped[int] = mapped_column(BigInteger, Identity(start=1000), unique=True)
    client_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("utilisateurs.id"))
    livreur_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("livreurs.utilisateur_id"))

    adresse_enlevement: Mapped[str] = mapped_column(Text)
    point_enlevement: Mapped[str] = _point()
    adresse_livraison: Mapped[str] = mapped_column(Text)
    point_livraison: Mapped[str] = _point()
    destinataire_nom: Mapped[str | None] = mapped_column(String(120))
    destinataire_telephone: Mapped[str | None] = mapped_column(String(20))

    taille_colis: Mapped[TailleColis] = mapped_column(_enum(TailleColis))
    description_colis: Mapped[str | None] = mapped_column(Text)
    consignes: Mapped[str | None] = mapped_column(Text)
    priorite: Mapped[Priorite] = mapped_column(
        _enum(Priorite), default=Priorite.NORMALE, server_default="normale"
    )

    prix: Mapped[int] = mapped_column(Integer)  # francs CFA
    distance_m: Mapped[int | None] = mapped_column(Integer)
    duree_estimee_s: Mapped[int | None] = mapped_column(Integer)
    mode_paiement: Mapped[ModePaiement] = mapped_column(_enum(ModePaiement))

    etat: Mapped[EtatCommande] = mapped_column(
        _enum(EtatCommande), default=EtatCommande.CREEE, server_default="creee"
    )
    # Preuve de livraison (F-23) : empreinte du code communiqué au destinataire.
    code_remise_hash: Mapped[str | None] = mapped_column(String(64))
    tentatives_attribution: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    rayon_recherche_m: Mapped[int | None] = mapped_column(Integer)

    cree_le: Mapped[datetime] = _horodatage()
    attribuee_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    enlevee_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    livree_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cloturee_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    annulee_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("prix >= 0", name="prix_positif"),
        Index("ix_commandes_client_id_cree_le", "client_id", "cree_le"),
        Index("ix_commandes_livreur_id_etat", "livreur_id", "etat"),
        Index("ix_commandes_etat", "etat"),
        Index("ix_commandes_point_enlevement", "point_enlevement", postgresql_using="gist"),
    )


class Offre(Base):
    """Une proposition d'un livreur lors d'un appel d'offres (Contract Net)."""

    __tablename__ = "offres"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    commande_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("commandes.id", ondelete="CASCADE"))
    livreur_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("livreurs.utilisateur_id"))
    tentative: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    cout: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))  # vide si refus
    eta_s: Mapped[int | None] = mapped_column(Integer)
    resultat: Mapped[ResultatOffre] = mapped_column(
        _enum(ResultatOffre), default=ResultatOffre.PROPOSEE, server_default="proposee"
    )
    motif: Mapped[str | None] = mapped_column(Text)
    cree_le: Mapped[datetime] = _horodatage()

    __table_args__ = (
        UniqueConstraint("commande_id", "livreur_id", "tentative", name="une_offre_par_tour"),
        CheckConstraint("cout IS NULL OR cout >= 0", name="cout_positif"),
        Index("ix_offres_livreur_id", "livreur_id"),
    )


# ----------------------------------------------------------------------------- argent
class Paiement(Base):
    __tablename__ = "paiements"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **_UUID_PK)
    commande_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("commandes.id"))
    mode: Mapped[ModePaiement] = mapped_column(_enum(ModePaiement))
    montant: Mapped[int] = mapped_column(Integer)  # francs CFA
    reference_prestataire: Mapped[str | None] = mapped_column(String(120), unique=True)
    etat: Mapped[EtatPaiement] = mapped_column(
        _enum(EtatPaiement), default=EtatPaiement.EN_ATTENTE, server_default="en_attente"
    )
    cree_le: Mapped[datetime] = _horodatage()
    confirme_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("montant >= 0", name="montant_positif"),
        Index("ix_paiements_commande_id", "commande_id"),
    )


class Facture(Base):
    __tablename__ = "factures"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **_UUID_PK)
    numero: Mapped[str] = mapped_column(String(30), unique=True)  # ex. F-2026-000123
    commande_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("commandes.id"), unique=True)
    montant_livraison: Mapped[int] = mapped_column(Integer)
    montant_supplements: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    montant_total: Mapped[int] = mapped_column(Integer)
    chemin_pdf: Mapped[str | None] = mapped_column(Text)
    emise_le: Mapped[datetime] = _horodatage()

    __table_args__ = (CheckConstraint("montant_total >= 0", name="total_positif"),)


# ----------------------------------------------------------------------------- journal
class Evenement(Base):
    """Journal des événements et des messages du protocole (§ 7.1, supervision)."""

    __tablename__ = "evenements"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    commande_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("commandes.id", ondelete="CASCADE")
    )
    type: Mapped[str] = mapped_column(String(60))
    auteur: Mapped[str] = mapped_column(String(120))  # identifiant d'utilisateur ou JID d'agent
    detail: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    horodatage: Mapped[datetime] = _horodatage()

    __table_args__ = (
        Index("ix_evenements_commande_id_horodatage", "commande_id", "horodatage"),
        Index("ix_evenements_type", "type"),
    )


class Parametre(Base):
    """Réglages modifiables par l'administrateur : tarifs, coefficients du coût, délais (F-50)."""

    __tablename__ = "parametres"

    cle: Mapped[str] = mapped_column(String(60), primary_key=True)
    valeur: Mapped[dict | list | int | float | str] = mapped_column(JSONB)
    description: Mapped[str | None] = mapped_column(Text)
    modifie_le: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    modifie_par: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("utilisateurs.id"))
