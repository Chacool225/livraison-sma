# Livraison SMA — préparation de l'environnement

Plateforme de livraison urbaine à allocation par appel d'offres (Contract Net), en Python.
Ce guide installe l'environnement de développement de A à Z sur **Windows 11**, **Ubuntu** ou **Debian**.

À la fin, vous aurez : Python et ses bibliothèques (SPADE, FastAPI, Flet…), PostgreSQL/PostGIS et Redis dans Docker, un serveur XMPP pour les agents, et en option le moteur d'itinéraires avec la carte de la Côte d'Ivoire.

## Sommaire

1. Prérequis
2. Installer les outils de base (Git, Python, Docker)
3. Récupérer le projet
4. Environnement Python
5. Configuration
6. Démarrer les services Docker
7. Moteur d'itinéraires (optionnel au début)
8. Serveur XMPP et test des agents
9. Vérification complète
10. Tester l'API et l'interface
11. Application Android (plus tard)
12. Utilisation quotidienne
13. Dépannage

## 1. Prérequis

| Élément | Minimum |
|---|---|
| Mémoire | 8 Go (16 Go conseillés avec le moteur d'itinéraires) |
| Disque libre | 10 Go |
| Système | Windows 11, Ubuntu 22.04 ou plus, Debian 12 ou plus |
| Droits | Compte administrateur (Windows) ou `sudo` (Linux) |
| Réseau | Connexion Internet pour les téléchargements |

Versions utilisées pour valider ce squelette : Python 3.13, SPADE 4.1, Flet 1.0, FastAPI 0.142. Python 3.11 ou plus convient.

## 2. Installer les outils de base

### Windows 11

Ouvrir **PowerShell en tant qu'administrateur**.

```powershell
# WSL 2, nécessaire à Docker Desktop (redémarrer l'ordinateur ensuite)
wsl --install

# Git, Python et Docker Desktop
winget install --id Git.Git -e
winget install --id Python.Python.3.13 -e
winget install --id Docker.DockerDesktop -e
```

Après le redémarrage : lancer **Docker Desktop** une première fois et attendre l'indication « Engine running ». Puis, dans un **nouveau** PowerShell (non administrateur), autoriser l'activation des environnements Python :

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

### Ubuntu

```bash
sudo apt update
sudo apt install -y git curl ca-certificates python3 python3-venv python3-pip

# Docker (dépôt officiel)
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# Utiliser Docker sans sudo (se déconnecter puis se reconnecter ensuite)
sudo usermod -aG docker $USER
```

Sur Ubuntu 22.04, Python est en version 3.10, trop ancienne. Installer une version plus récente, puis utiliser `python3.12` à la place de `python3` à l'étape 4 :

```bash
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt install -y python3.12 python3.12-venv
```

### Debian

Identique à Ubuntu, avec `debian` à la place de `ubuntu` dans les deux adresses du dépôt Docker :

```bash
sudo apt update
sudo apt install -y git curl ca-certificates python3 python3-venv python3-pip

sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

sudo usermod -aG docker $USER
```

Si `sudo` n'est pas installé sur Debian : `su -`, puis `apt install sudo && usermod -aG sudo votre_nom`, et se reconnecter.

### Contrôle (les trois systèmes)

```bash
git --version
python --version        # python3 --version sous Linux
docker --version
docker compose version
docker run --rm hello-world
```

## 3. Récupérer le projet

Décompresser l'archive `livraison-sma.zip` à l'emplacement de votre choix, sans espace ni accent dans le chemin (par exemple `C:\projets\livraison-sma` ou `~/projets/livraison-sma`), puis initialiser le dépôt Git :

```bash
cd livraison-sma
git init
git add .
git commit -m "Squelette initial"
```

Toutes les commandes qui suivent se lancent **depuis ce dossier**.

## 4. Environnement Python

### Windows 11

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
pip install -e .
```

### Ubuntu et Debian

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
pip install -e .
```

L'invite de commande commence alors par `(.venv)`. Il faut **réactiver l'environnement à chaque nouveau terminal** (ligne `Activate.ps1` ou `source`).

Premier contrôle, qui ne demande aucun service :

```bash
pytest
```

Résultat attendu : `3 passed`. Ces tests rejouent le scénario des six colis du TP JADE.

## 5. Configuration

```powershell
# Windows
Copy-Item .env.example .env
```

```bash
# Linux
cp .env.example .env
```

Ouvrir `.env` et remplacer les trois valeurs `changez-moi` (mot de passe PostgreSQL, mot de passe des agents, secret JWT). Le fichier `.env` n'est jamais versionné ; chaque membre de l'équipe a le sien.

## 6. Démarrer les services Docker

```bash
docker compose up -d
docker compose ps
```

Les services `postgres` et `redis` doivent afficher l'état `healthy` après quelques secondes.

| Service | Adresse | Rôle |
|---|---|---|
| PostgreSQL + PostGIS | `localhost:5432` | Comptes, commandes, paiements, données géographiques |
| Redis | `localhost:6379` | Dernières positions GPS, sessions |

Les ports ne sont ouverts que sur la machine locale. Si vous modifiez le mot de passe PostgreSQL après le premier démarrage, il faut recréer la base : `docker compose down -v` (efface les données), puis `docker compose up -d`.

## 7. Moteur d'itinéraires (optionnel au début)

Cette étape télécharge la carte OpenStreetMap de la Côte d'Ivoire (fournie par Geofabrik) et prépare les données d'OSRM. Elle prend plusieurs minutes et n'est nécessaire qu'à partir du lot 2 ; vous pouvez y revenir plus tard.

```powershell
# Windows
.\scripts\preparer_osrm.ps1
```

```bash
# Linux
bash scripts/preparer_osrm.sh
```

Puis démarrer le service :

```bash
docker compose --profile itineraires up -d
```

Test : l'adresse suivante doit renvoyer un itinéraire Plateau → Cocody au format JSON.

```
http://localhost:5000/route/v1/driving/-4.0197,5.3236;-3.9870,5.3480?overview=false
```

Notes :

- OSRM attend les coordonnées dans l'ordre **longitude, latitude**.
- Le profil préparé est celui de la voiture. Les profils moto et vélo seront ajoutés au lot 2.
- Pour le géocodage (adresse → coordonnées), le service public Nominatim suffit en développement, à raison d'une requête par seconde au maximum. Un serveur dédié sera à prévoir pour la production.

## 8. Serveur XMPP et test des agents

SPADE fournit un serveur XMPP de développement. Le lancer dans un **terminal dédié** (environnement activé) et le laisser ouvert :

```bash
spade run
```

Dans un **second terminal** (environnement activé) :

```bash
python -m livraison.agents.ping_pong
```

Résultat attendu :

```
ping -> ping #1
pong a reçu « ping #1 » de ping
ping <- « pong #1 »
...
OK : les agents communiquent.
```

C'est l'équivalent SPADE des agents Ping et Pong du TP : `PeriodicBehaviour` remplace `TickerBehaviour`, la métadonnée `performative` remplace la performative ACL, et `Template` remplace `MessageTemplate`.

Les comptes des agents sont créés automatiquement au premier lancement et enregistrés dans le fichier `server.db`. Pour repartir de zéro : `spade run --purge`.

## 9. Vérification complète

Avec Docker démarré et `spade run` ouvert :

```bash
python scripts/verifier_env.py
```

Résultat attendu :

```
[OK] Python >= 3.11 (3.13.x)
[OK] Bibliothèque spade (4.1.x)
...
[OK] PostgreSQL + PostGIS (PostGIS 3.4)
[OK] Redis
[OK] Serveur XMPP (localhost:5222)
[--] Moteur d'itinéraires (optionnel) ...

Environnement prêt.
```

Une ligne `[KO]` indique ce qui reste à corriger. La ligne `[--]` du moteur d'itinéraires est normale tant que l'étape 7 n'a pas été faite.

## 10. Tester l'API et l'interface

Serveur applicatif :

```bash
uvicorn livraison.api.main:app --reload
```

Ouvrir `http://127.0.0.1:8000/sante` (réponse `{"etat":"ok"}`) et `http://127.0.0.1:8000/docs` (documentation interactive).

Interface Flet :

```bash
flet run src/livraison/interfaces/demo.py          # fenêtre de bureau
flet run --web src/livraison/interfaces/demo.py    # dans le navigateur
```

Sous Linux, la fenêtre de bureau peut demander des bibliothèques système supplémentaires (le message d'erreur les nomme) ; la version `--web` fonctionne sans elles.

## 11. Application Android (plus tard)

La construction de l'application du livreur (`flet build apk`) demande en plus le SDK Flutter, un JDK et le SDK Android. C'est une installation lourde, à faire au lot 3 sur un seul poste. D'ici là, l'application se teste sur un vrai téléphone avec l'application **Flet** du Play Store : lancer `flet run --android` et scanner le code QR affiché (téléphone et ordinateur sur le même réseau Wi-Fi).

## 12. Utilisation quotidienne

| Action | Commande |
|---|---|
| Activer l'environnement (Windows) | `.\.venv\Scripts\Activate.ps1` |
| Activer l'environnement (Linux) | `source .venv/bin/activate` |
| Démarrer les services | `docker compose up -d` |
| Arrêter les services | `docker compose stop` |
| Voir les journaux d'un service | `docker compose logs -f postgres` |
| Serveur XMPP | `spade run` |
| API | `uvicorn livraison.api.main:app --reload` |
| Tests | `pytest` |
| Qualité du code | `ruff check .` puis `ruff format .` |
| Console SQL | `docker compose exec postgres psql -U livraison` |

### Arborescence

```
livraison-sma/
├── docker-compose.yml        services PostgreSQL/PostGIS, Redis, OSRM
├── .env.example              modèle de configuration
├── requirements.txt          dépendances de l'application
├── requirements-dev.txt      + outils de test et de qualité
├── pyproject.toml            configuration du paquet, de pytest et de ruff
├── scripts/
│   ├── verifier_env.py       contrôle de l'environnement
│   └── preparer_osrm.*       préparation de la carte
├── donnees/osrm/             données cartographiques (non versionnées)
├── src/livraison/
│   ├── config.py             lecture du fichier .env
│   ├── agents/               agents SPADE (ping_pong.py pour l'instant)
│   ├── api/                  serveur FastAPI
│   ├── modele/               règles métier (cout.py)
│   ├── services/             tarification, itinéraires, paiement (à venir)
│   └── interfaces/           applications Flet
└── tests/
```

## 13. Dépannage

| Symptôme | Cause probable et solution |
|---|---|
| `Activate.ps1 cannot be loaded` (Windows) | Lancer `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`. |
| `python` ouvre le Microsoft Store (Windows) | Utiliser `py`, ou désactiver les « alias d'exécution d'application » pour Python dans les paramètres Windows. |
| `permission denied` sur `docker` (Linux) | Se déconnecter puis se reconnecter après `usermod -aG docker $USER`. |
| `port is already allocated` sur 5432 | Un PostgreSQL local occupe le port : mettre `POSTGRES_PORT=5433` dans `.env`, puis `docker compose up -d`. |
| `password authentication failed` | Le mot de passe a changé après la création de la base : `docker compose down -v`, puis `docker compose up -d`. |
| `ModuleNotFoundError: livraison` | Environnement non activé, ou `pip install -e .` non exécuté. |
| Ping/Pong : « aucune réponse » | `spade run` n'est pas lancé, ou le port 5222 est bloqué par un pare-feu. |
| Docker Desktop ne démarre pas (Windows) | Vérifier que la virtualisation est activée dans le BIOS et relancer `wsl --update`. |
| OSRM s'arrête pendant la préparation | Mémoire insuffisante : augmenter la mémoire allouée à Docker (Docker Desktop → Settings → Resources). |

## Étape 3 : base de données et comptes

Cette étape ajoute le modèle de données (10 tables PostgreSQL/PostGIS), les migrations Alembic et
l'authentification par téléphone (code SMS + jeton JWT, quatre rôles).

```powershell
docker compose up -d                 # PostgreSQL et Redis doivent être « healthy »
alembic upgrade head                 # crée les tables dans la base « livraison »
python scripts\creer_admin.py "07 00 00 00 00" "Votre nom"   # premier administrateur
uvicorn livraison.api.main:app --reload
```

Ouvrir http://127.0.0.1:8000/docs : la documentation interactive de l'API.

- **Connexion** : `POST /auth/demander-code` puis `POST /auth/verifier-code`. En mode
  `ENVIRONNEMENT=dev`, le code est renvoyé dans la réponse (aucun vrai SMS n'est envoyé).
  Pour tester dans `/docs`, cliquer sur « Authorize » et coller le jeton reçu.
- **Rôles** : on s'inscrit comme `client` ou `livreur`. Les rôles `repartiteur` et `administrateur`
  se donnent uniquement avec `scripts\creer_admin.py`.
- **Livreur** : `PUT /livreurs/moi/dossier`, puis l'administrateur valide avec
  `POST /admin/livreurs/{id}/validation`.
- **Tests** : `pytest`. Ceux de la base utilisent une base séparée, `livraison_test`, recréée à
  chaque session ; ils sont ignorés si PostgreSQL ne tourne pas.
- **Faire évoluer le modèle** : modifier `src/livraison/db/modeles.py`, puis
  `alembic revision --autogenerate -m "description"`, relire le fichier généré, et
  `alembic upgrade head`.
