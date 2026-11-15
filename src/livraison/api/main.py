"""Serveur applicatif. Lancement : uvicorn livraison.api.main:app --reload"""

import asyncio
import contextlib
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from livraison.agents.flotte import Flotte
from livraison.api.routes import auth, commandes, courses, livreurs
from livraison.config import parametres
from livraison.db.session import fabrique_sessions
from livraison.services.comptes import ErreurMetier
from livraison.services.itineraire import creer_itineraire

journal = logging.getLogger("livraison.api")
SECRET_PAR_DEFAUT = "changez-moi"
DELAI_DEMARRAGE_AGENTS_S = 20


async def _xmpp_joignable() -> bool:
    """Test rapide : inutile d'attendre des délais de connexion si le serveur n'est pas lancé."""
    try:
        _, ecriture = await asyncio.wait_for(
            asyncio.open_connection(parametres.xmpp_host, parametres.xmpp_port), timeout=2
        )
    except (OSError, TimeoutError):
        return False
    ecriture.close()
    return True


async def _demarrer_flotte() -> Flotte | None:
    """Démarre les agents. Si le serveur XMPP est injoignable, l'API démarre quand même (comptes,
    lectures) mais sans attribution de courses : les routes concernées répondent 503."""
    if sys.platform == "win32" and not isinstance(
        asyncio.get_running_loop(), asyncio.SelectorEventLoop
    ):
        journal.warning(
            "Boucle d'événements non testée avec les agents : lancer l'API avec "
            "`python -m livraison.api` (ou `uvicorn ... --reload`)."
        )
    if not await _xmpp_joignable():
        journal.error(
            "Serveur XMPP injoignable (%s:%s) : lancer `spade run --memory`. "
            "L'API démarre sans attribution de courses.",
            parametres.xmpp_host,
            parametres.xmpp_port,
        )
        return None
    flotte = Flotte(
        fabrique_sessions(),
        itineraire=creer_itineraire(parametres.itineraire, parametres.osrm_url),
    )
    try:
        await asyncio.wait_for(flotte.demarrer(), timeout=DELAI_DEMARRAGE_AGENTS_S)
    except Exception:  # noqa: BLE001 - XMPP absent, délai dépassé... : on continue sans agents
        journal.exception(
            "Agents non démarrés : le serveur XMPP tourne-t-il ? (spade run). "
            "L'API continue sans attribution de courses."
        )
        with contextlib.suppress(Exception):
            await asyncio.shield(flotte.arreter())
        return None
    journal.info("Agents démarrés (annuaire et dispatcher)")
    return flotte


@asynccontextmanager
async def cycle_de_vie(app: FastAPI):
    if parametres.environnement != "dev" and parametres.jwt_secret.startswith(SECRET_PAR_DEFAUT):
        raise RuntimeError("JWT_SECRET doit être changé avant de quitter l'environnement « dev ».")
    app.state.flotte = await _demarrer_flotte() if parametres.agents_actifs else None
    yield
    if app.state.flotte is not None:
        await app.state.flotte.arreter()


app = FastAPI(title="Livraison SMA", version="0.3.0", lifespan=cycle_de_vie)
app.include_router(auth.router)
app.include_router(livreurs.router)
app.include_router(courses.router)
app.include_router(commandes.router)


@app.exception_handler(ErreurMetier)
async def traduire_erreur_metier(_: Request, erreur: ErreurMetier) -> JSONResponse:
    return JSONResponse(status_code=erreur.statut_http, content={"detail": erreur.message})


@app.get("/sante")
async def sante(request: Request) -> dict:
    """Point de contrôle : le serveur répond, et les agents tournent-ils ?"""
    return {"etat": "ok", "agents": getattr(request.app.state, "flotte", None) is not None}
