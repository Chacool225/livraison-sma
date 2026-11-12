#!/usr/bin/env bash
# Télécharge la carte de la Côte d'Ivoire et prépare les données du moteur d'itinéraires.
# À lancer une seule fois depuis la racine du projet : bash scripts/preparer_osrm.sh
set -euo pipefail
DOSSIER="$(pwd)/donnees/osrm"
IMAGE="ghcr.io/project-osrm/osrm-backend:latest"
URL="https://download.geofabrik.de/africa/ivory-coast-latest.osm.pbf"

mkdir -p "$DOSSIER"
if [ ! -f "$DOSSIER/carte.osm.pbf" ]; then
  echo ">> Téléchargement de la carte..."
  curl -L --fail -o "$DOSSIER/carte.osm.pbf" "$URL"
fi
echo ">> Extraction (profil voiture)..."
docker run --rm -t -v "$DOSSIER:/data" "$IMAGE" osrm-extract -p /opt/car.lua /data/carte.osm.pbf
echo ">> Partition..."
docker run --rm -t -v "$DOSSIER:/data" "$IMAGE" osrm-partition /data/carte.osrm
echo ">> Personnalisation..."
docker run --rm -t -v "$DOSSIER:/data" "$IMAGE" osrm-customize /data/carte.osrm
echo ">> Terminé. Lancez : docker compose --profile itineraires up -d"
