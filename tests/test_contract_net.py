"""Test d'intégration : nécessite le serveur XMPP (`spade run`). Ignoré s'il est absent."""

import socket

import pytest

from livraison.agents import scenario_tp
from livraison.config import parametres


def _serveur_xmpp_actif() -> bool:
    try:
        with socket.create_connection((parametres.xmpp_host, parametres.xmpp_port), timeout=1):
            return True
    except OSError:
        return False


@pytest.mark.skipif(not _serveur_xmpp_actif(), reason="serveur XMPP absent (lancer : spade run)")
async def test_scenario_tp_avec_agents():
    assert await scenario_tp.main()
