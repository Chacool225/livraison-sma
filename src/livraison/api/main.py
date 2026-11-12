"""Serveur applicatif. Lancement : uvicorn livraison.api.main:app --reload"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from livraison.api.routes import auth, livreurs
from livraison.config import parametres
from livraison.services.comptes import ErreurMetier

SECRET_PAR_DEFAUT = "changez-moi"


@asynccontextmanager
async def cycle_de_vie(_: FastAPI):
    if parametres.environnement != "dev" and parametres.jwt_secret.startswith(SECRET_PAR_DEFAUT):
        raise RuntimeError("JWT_SECRET doit être changé avant de quitter l'environnement « dev ».")
    yield


app = FastAPI(title="Livraison SMA", version="0.2.0", lifespan=cycle_de_vie)
app.include_router(auth.router)
app.include_router(livreurs.router)


@app.exception_handler(ErreurMetier)
async def traduire_erreur_metier(_: Request, erreur: ErreurMetier) -> JSONResponse:
    return JSONResponse(status_code=erreur.statut_http, content={"detail": erreur.message})


@app.get("/sante")
async def sante() -> dict:
    """Point de contrôle utilisé pour vérifier que le serveur répond."""
    return {"etat": "ok"}
