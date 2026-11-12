"""Outils de sécurité : numéros de téléphone, codes à usage unique, jetons JWT."""

import hashlib
import hmac
import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt

from livraison.config import parametres

_E164 = re.compile(r"^\+[1-9]\d{7,14}$")


class JetonInvalide(Exception):
    """Jeton absent, falsifié ou expiré."""


def normaliser_telephone(brut: str) -> str:
    """Met un numéro au format international E.164 (ex. +2250700000000).

    Acceptés : « +225 07 00 00 00 00 », « 00225 0700000000 », ou un numéro national de
    10 chiffres (« 07 00 00 00 00 »), auquel on ajoute l'indicatif par défaut du pays.
    """
    numero = re.sub(r"[\s.\-()]", "", brut or "")
    if numero.startswith("00"):
        numero = "+" + numero[2:]
    elif not numero.startswith("+") and numero.isdigit() and len(numero) == 10:
        numero = parametres.indicatif_pays_defaut + numero
    if not _E164.match(numero):
        raise ValueError("Numéro de téléphone invalide (format attendu : +2250700000000)")
    return numero


def generer_code() -> str:
    """Code à 6 chiffres, tiré avec un générateur cryptographique."""
    return f"{secrets.randbelow(1_000_000):06d}"


def hacher_code(telephone: str, code: str) -> str:
    """Empreinte du code, liée au numéro : le code lui-même n'est jamais stocké."""
    message = f"{telephone}:{code}".encode()
    return hmac.new(parametres.jwt_secret.encode(), message, hashlib.sha256).hexdigest()


def codes_identiques(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)


def creer_jeton(utilisateur_id: uuid.UUID, role: str) -> str:
    maintenant = datetime.now(UTC)
    contenu = {
        "sub": str(utilisateur_id),
        "role": role,
        "iat": maintenant,
        "exp": maintenant + timedelta(hours=parametres.jwt_duree_heures),
    }
    return jwt.encode(contenu, parametres.jwt_secret, algorithm="HS256")


def lire_jeton(jeton: str) -> dict:
    try:
        return jwt.decode(
            jeton, parametres.jwt_secret, algorithms=["HS256"], options={"require": ["exp", "sub"]}
        )
    except jwt.PyJWTError as erreur:
        raise JetonInvalide(str(erreur)) from erreur
