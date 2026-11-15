"""Démarrage du serveur : sans serveur XMPP, l'API démarre quand même (sans les agents)."""

import time

from livraison.agents.flotte import Flotte
from livraison.api.main import _demarrer_flotte, app, cycle_de_vie
from livraison.config import parametres


async def test_l_api_demarre_sans_agents_si_xmpp_est_injoignable(monkeypatch):
    async def echec(self):
        raise ConnectionRefusedError("serveur XMPP absent")

    monkeypatch.setattr(Flotte, "demarrer", echec)
    assert await _demarrer_flotte() is None  # pas d'exception : l'API reste utilisable


async def test_agents_desactives_par_la_configuration(monkeypatch):
    monkeypatch.setattr(parametres, "agents_actifs", False)
    async with cycle_de_vie(app):
        assert app.state.flotte is None


async def test_serveur_xmpp_absent_demarrage_immediat(monkeypatch):
    monkeypatch.setattr(parametres, "xmpp_port", 1)  # personne n'écoute sur ce port
    debut = time.monotonic()
    assert await _demarrer_flotte() is None
    assert time.monotonic() - debut < 5  # pas d'attente de plusieurs dizaines de secondes
