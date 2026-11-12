"""Logique des comptes : codes de vérification, connexion, dossier livreur, validation."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from livraison.config import parametres
from livraison.db.modeles import (
    CodeVerification,
    Evenement,
    Livreur,
    Role,
    StatutCompte,
    StatutValidation,
    Utilisateur,
)
from livraison.services import securite
from livraison.services.sms import envoyer_sms


class ErreurMetier(Exception):
    """Erreur attendue, traduite en réponse HTTP par l'API."""

    def __init__(self, statut_http: int, message: str):
        super().__init__(message)
        self.statut_http = statut_http
        self.message = message


async def demander_code(session: AsyncSession, telephone_brut: str) -> str:
    """Crée un code, l'« envoie » par SMS et le renvoie (l'API ne l'expose qu'en mode dev)."""
    try:
        telephone = securite.normaliser_telephone(telephone_brut)
    except ValueError as erreur:
        raise ErreurMetier(422, str(erreur)) from erreur

    maintenant = datetime.now(UTC)
    recents = await session.scalar(
        select(func.count())
        .select_from(CodeVerification)
        .where(
            CodeVerification.telephone == telephone,
            CodeVerification.cree_le > maintenant - timedelta(minutes=10),
        )
    )
    if recents >= parametres.codes_max_par_10_min:
        raise ErreurMetier(429, "Trop de demandes de code. Réessayez dans quelques minutes.")

    code = securite.generer_code()
    session.add(
        CodeVerification(
            telephone=telephone,
            code_hash=securite.hacher_code(telephone, code),
            expire_le=maintenant + timedelta(minutes=parametres.code_validite_minutes),
        )
    )
    await session.commit()
    await envoyer_sms(telephone, f"Votre code de vérification Livraison SMA : {code}")
    return code


async def verifier_code(
    session: AsyncSession, telephone_brut: str, code: str, role: Role, nom: str | None
) -> tuple[Utilisateur, str]:
    """Vérifie le code ; crée le compte à la première connexion ; renvoie (utilisateur, jeton)."""
    try:
        telephone = securite.normaliser_telephone(telephone_brut)
    except ValueError as erreur:
        raise ErreurMetier(422, str(erreur)) from erreur

    maintenant = datetime.now(UTC)
    enregistrement = await session.scalar(
        select(CodeVerification)
        .where(
            CodeVerification.telephone == telephone,
            CodeVerification.utilise.is_(False),
            CodeVerification.expire_le > maintenant,
        )
        .order_by(CodeVerification.cree_le.desc(), CodeVerification.id.desc())
        .limit(1)
        .with_for_update()
    )
    if enregistrement is None:
        raise ErreurMetier(400, "Code invalide ou expiré.")
    if enregistrement.tentatives >= parametres.code_tentatives_max:
        raise ErreurMetier(429, "Trop de tentatives. Demandez un nouveau code.")

    enregistrement.tentatives += 1
    if not securite.codes_identiques(
        enregistrement.code_hash, securite.hacher_code(telephone, code)
    ):
        await session.commit()  # on conserve le compte des tentatives
        raise ErreurMetier(400, "Code invalide ou expiré.")
    enregistrement.utilise = True

    utilisateur = await session.scalar(
        select(Utilisateur).where(Utilisateur.telephone == telephone)
    )
    if utilisateur is None:
        utilisateur = Utilisateur(telephone=telephone, nom=nom, role=role)
        session.add(utilisateur)
    elif utilisateur.statut == StatutCompte.SUSPENDU:
        await session.commit()
        raise ErreurMetier(403, "Compte suspendu.")
    utilisateur.derniere_connexion = maintenant
    await session.commit()
    return utilisateur, securite.creer_jeton(utilisateur.id, utilisateur.role.value)


async def enregistrer_dossier_livreur(
    session: AsyncSession, utilisateur: Utilisateur, donnees: dict
) -> Livreur:
    """Crée ou met à jour le dossier ; toute modification remet la validation en attente."""
    livreur = await session.get(Livreur, utilisateur.id)
    if livreur is None:
        livreur = Livreur(utilisateur_id=utilisateur.id, **donnees)
        session.add(livreur)
    else:
        for champ, valeur in donnees.items():
            setattr(livreur, champ, valeur)
        livreur.statut_validation = StatutValidation.EN_ATTENTE
        livreur.valide_par = None
        livreur.valide_le = None
        livreur.en_ligne = False
    await session.commit()
    return livreur


async def decider_validation(
    session: AsyncSession, administrateur: Utilisateur, livreur_id: uuid.UUID, decision: str
) -> Livreur:
    livreur = await session.get(Livreur, livreur_id)
    if livreur is None:
        raise ErreurMetier(404, "Dossier livreur introuvable.")
    livreur.statut_validation = StatutValidation(decision)
    livreur.valide_par = administrateur.id
    livreur.valide_le = datetime.now(UTC)
    if decision != StatutValidation.VALIDE.value:
        livreur.en_ligne = False
    session.add(
        Evenement(
            type=f"livreur_{decision}",
            auteur=str(administrateur.id),
            detail={"livreur_id": str(livreur_id)},
        )
    )
    await session.commit()
    return livreur
