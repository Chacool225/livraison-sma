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
- [ ] Sans serveur XMPP : `pytest` → `80 passed, 34 skipped`
- [ ] Avec `spade run --memory` dans un autre terminal : `pytest` → `114 passed`
- [ ] Relancer 3 fois (serveur XMPP relancé avant chaque série) : mêmes résultats, aucun test instable
- [ ] `ruff check .` → `All checks passed!`

## D. Parcours de l'API (page `/docs`, `uvicorn livraison.api.main:app`)

Raccourci automatique : lancer le serveur (commande ci-dessus), créer l'administrateur avec
`python scripts\creer_admin.py "07 00 00 00 00" "Admin"`, puis `python scripts\recette_api.py` : il déroule
toute cette section et affiche OK ou KO pour chaque ligne (`24/24 vérifications réussies.`).
Le test de redémarrage de PostgreSQL reste manuel.

- [ ] `GET /sante` → `{"etat":"ok"}`
- [ ] `python scripts\creer_admin.py "<numéro>" "<nom>"`, connexion avec ce numéro → `GET /moi` : `administrateur`
- [ ] Client : `demander-code` puis `verifier-code` (nouveau numéro) → `GET /moi` : `client`
- [ ] Livreur : inscription avec `"role": "livreur"` → `PUT /livreurs/moi/dossier` → `en_attente`
- [ ] Administrateur : `GET /admin/livreurs` liste le dossier, `POST .../validation` (`valide`) → le livreur voit `valide`
- [ ] Modifier le dossier remet la validation en attente
- [ ] Cas refusés : 5 mauvais codes puis le bon → `429` ; code réutilisé → `400` ; client sur `/admin/livreurs` → `403` ; sans jeton → `401` ; `"role": "administrateur"` à l'inscription → `422`
- [ ] `docker compose restart postgres`, attendre `healthy` : un jeton déjà obtenu fonctionne encore sur `GET /moi`

## D2. Parcours client -> livreur avec les agents (étape 6)
- [ ] `spade run --memory` (terminal 1), puis `python -m livraison.api` (terminal 2) : `GET /sante` → `"agents": true`
- [ ] `python scripts\demo_parcours.py` (terminal 3) → les 7 étapes puis `[OK] Parcours complet réussi`
- [ ] Arrêter `spade run`, relancer l'API : elle démarre (`"agents": false`) et `POST /commandes` répond `503`
- [ ] Dans `/docs`, refaire à la main un tour : commander, voir la proposition côté livreur, accepter, suivre l'état côté client

## D3. Application Flet (étape 7)
- [ ] `pip install "flet[all]==1.1.2"` puis `python scripts\verifier_env.py` → ligne « Interface Flet » en `[OK]`
- [ ] `python -m livraison.interfaces --web` : la page de connexion s'affiche dans le navigateur
- [ ] Connexion avec un nouveau numéro : le code est pré-rempli ; rôle « Livreur » + un nom → espace livreur
- [ ] Livreur : « Mon dossier » → envoyer ; l'administrateur (autre onglet) le valide dans « Dossiers »
- [ ] Livreur : choisir « Plateau », passer « En ligne » ; l'administrateur le voit dans « En ligne »
- [ ] Client (3e onglet) : Plateau → Cocody, « Estimer le prix » puis « Commander » : le code de remise s'affiche
- [ ] Livreur : la proposition apparaît avec un compte à rebours ; « Accepter » ; le client voit son livreur
- [ ] Livreur : « J'ai enlevé le colis », « Je pars livrer », « Colis livré » avec un faux code (refusé), puis le bon
- [ ] Client : l'état passe à « Livrée » ; administrateur, onglet « Commandes » : la commande est « Livrée »
- [ ] Sans livreur en ligne : la commande apparaît dans « Alertes » ; « Relancer la recherche » et « Annuler » fonctionnent
- [ ] Fermer l'onglet du livreur : le serveur ne plante pas

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
