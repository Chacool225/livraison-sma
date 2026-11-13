# Recette : liste de vérification

À faire sur une **copie neuve** de la branche (`git clone -b <branche> ... livraison-sma-recette`),
Docker Desktop lancé et les ports 5433, 6390, 5222, 9090, 8000 libres. Cocher chaque ligne.

## A. Installation depuis zéro
- [ ] `py -3.13 -m venv .venv`, activation, `pip install -r requirements-dev.txt`, `pip install -e .`
- [ ] `pip uninstall -y winloop` puis `python -c "import winloop"` → `ModuleNotFoundError`
- [ ] `.env` créé depuis `.env.example` : mots de passe, `JWT_SECRET` long (≥ 32 caractères), ports (`POSTGRES_PORT`, `REDIS_PORT`), `127.0.0.1` partout
- [ ] `python scripts\verifier_env.py` → `Environnement prêt.` (la ligne OSRM `[--]` est acceptable)

## B. Infrastructure et base de données
- [ ] `docker compose up -d` puis `docker compose ps` → `postgres` et `redis` en `healthy`
- [ ] `alembic upgrade head` → migrations 0001, 0002, 0003 appliquées
- [ ] `alembic current` → `0003 (head)`
- [ ] `alembic check` → `No new upgrade operations detected.`
- [ ] Tables : `docker compose exec postgres psql -U <POSTGRES_USER> -d <POSTGRES_DB> -c "\dt"` → 10 tables métier + `alembic_version` + `spatial_ref_sys`
- [ ] Réglages : `... -c "select count(*) from parametres;"` → `13`
- [ ] Réversibilité (base neuve seulement) : `alembic downgrade base` puis `alembic upgrade head`, sans erreur

## C. Tests automatiques
- [ ] Sans serveur XMPP : `pytest` → `60 passed, 17 skipped`
- [ ] Avec `spade run --memory` dans un autre terminal : `pytest` → `77 passed`
- [ ] Relancer 3 fois (serveur XMPP relancé avant chaque série) : mêmes résultats, aucun test instable
- [ ] `ruff check .` → `All checks passed!`

## D. Parcours de l'API (page `/docs`, `uvicorn livraison.api.main:app`)
- [ ] `GET /sante` → `{"etat":"ok"}`
- [ ] `python scripts\creer_admin.py "<numéro>" "<nom>"`, connexion avec ce numéro → `GET /moi` : `administrateur`
- [ ] Client : `demander-code` puis `verifier-code` (nouveau numéro) → `GET /moi` : `client`
- [ ] Livreur : inscription avec `"role": "livreur"` → `PUT /livreurs/moi/dossier` → `en_attente`
- [ ] Administrateur : `GET /admin/livreurs` liste le dossier, `POST .../validation` (`valide`) → le livreur voit `valide`
- [ ] Modifier le dossier remet la validation en attente
- [ ] Cas refusés : 5 mauvais codes puis le bon → `429` ; code réutilisé → `400` ; client sur `/admin/livreurs` → `403` ; sans jeton → `401` ; `"role": "administrateur"` à l'inscription → `422`
- [ ] `docker compose restart postgres`, attendre `healthy` : un jeton déjà obtenu fonctionne encore sur `GET /moi`

## E. Agents
- [ ] `spade run --memory`, puis `python -m livraison.agents.scenario_tp` → `OK : même attribution que le TP.`

## F. Moteur d'itinéraires OSRM (étape 5)
- [ ] `.\scripts\preparer_osrm.ps1` (téléchargement de la carte : long, une seule fois)
- [ ] `docker compose --profile itineraires up -d`
- [ ] `python scripts\verifier_osrm.py` → `[OK] OSRM répond avec des durées cohérentes.`
- [ ] `docker compose stop osrm` puis `python scripts\verifier_osrm.py` → `[KO]` explicite (le repli automatique est couvert par les tests)

## G. Dépôt Git
- [ ] `git status` propre
- [ ] `git ls-files | Select-String "\.env$|\.log$|\.db$"` → aucune ligne
- [ ] `git grep -n -i "motdepasse"` → aucune ligne
