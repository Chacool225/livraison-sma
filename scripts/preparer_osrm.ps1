# Télécharge la carte de la Côte d'Ivoire et prépare les données du moteur d'itinéraires.
# À lancer une seule fois depuis la racine du projet : .\scripts\preparer_osrm.ps1
$ErrorActionPreference = "Stop"
$Dossier = Join-Path (Get-Location) "donnees\osrm"
$Image = "ghcr.io/project-osrm/osrm-backend:latest"
$Url = "https://download.geofabrik.de/africa/ivory-coast-latest.osm.pbf"

New-Item -ItemType Directory -Force -Path $Dossier | Out-Null
$Carte = Join-Path $Dossier "carte.osm.pbf"
if (-not (Test-Path $Carte)) {
    Write-Host ">> Telechargement de la carte..."
    Invoke-WebRequest -Uri $Url -OutFile $Carte
}
Write-Host ">> Extraction (profil voiture)..."
docker run --rm -t -v "${Dossier}:/data" $Image osrm-extract -p /opt/car.lua /data/carte.osm.pbf
if ($LASTEXITCODE -ne 0) { throw "osrm-extract a echoue" }
Write-Host ">> Partition..."
docker run --rm -t -v "${Dossier}:/data" $Image osrm-partition /data/carte.osrm
if ($LASTEXITCODE -ne 0) { throw "osrm-partition a echoue" }
Write-Host ">> Personnalisation..."
docker run --rm -t -v "${Dossier}:/data" $Image osrm-customize /data/carte.osrm
if ($LASTEXITCODE -ne 0) { throw "osrm-customize a echoue" }
Write-Host ">> Termine. Lancez : docker compose --profile itineraires up -d"
