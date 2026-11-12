import uuid

import pytest

from livraison.config import parametres
from livraison.services import securite


@pytest.mark.parametrize(
    ("saisie", "attendu"),
    [
        ("+225 07 00 00 00 00", "+2250700000000"),
        ("07 00 00 00 00", "+2250700000000"),
        ("0700000000", "+2250700000000"),
        ("00225 0700000000", "+2250700000000"),
        ("+33 6 12 34 56 78", "+33612345678"),
        ("(+225) 05-00-00-00-00", "+2250500000000"),
    ],
)
def test_normaliser_telephone(saisie, attendu):
    assert securite.normaliser_telephone(saisie) == attendu


@pytest.mark.parametrize(
    "saisie", ["", "abc", "123", "+0123456789", "070000000", "+22507000000000000"]
)
def test_telephone_invalide(saisie):
    with pytest.raises(ValueError):
        securite.normaliser_telephone(saisie)


def test_code_a_six_chiffres():
    for _ in range(200):
        code = securite.generer_code()
        assert len(code) == 6 and code.isdigit()


def test_empreinte_liee_au_numero_et_au_code():
    a = securite.hacher_code("+2250700000000", "123456")
    assert a == securite.hacher_code("+2250700000000", "123456")
    assert a != securite.hacher_code("+2250700000001", "123456")
    assert a != securite.hacher_code("+2250700000000", "123457")
    assert "123456" not in a


def test_jeton_aller_retour():
    identifiant = uuid.uuid4()
    contenu = securite.lire_jeton(securite.creer_jeton(identifiant, "client"))
    assert contenu["sub"] == str(identifiant)
    assert contenu["role"] == "client"


def test_jeton_expire_ou_falsifie(monkeypatch):
    monkeypatch.setattr(parametres, "jwt_duree_heures", -1)
    with pytest.raises(securite.JetonInvalide):
        securite.lire_jeton(securite.creer_jeton(uuid.uuid4(), "client"))
    monkeypatch.undo()
    jeton = securite.creer_jeton(uuid.uuid4(), "client")
    with pytest.raises(securite.JetonInvalide):
        securite.lire_jeton(jeton[:-2] + "xx")
