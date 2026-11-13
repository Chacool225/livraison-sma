"""reglages d'attribution : relance et nombre de candidats

Revision ID: 0002
Revises: 0001
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

NOUVEAUX = [
    ("delai_relance_s", 5, "Attente avant de relancer une commande restée sans offre"),
    ("candidats_max", 20, "Nombre maximal de livreurs sollicités par appel d'offres"),
]


def upgrade() -> None:
    requete = sa.text(
        "INSERT INTO parametres (cle, valeur, description) "
        "VALUES (:cle, CAST(:valeur AS jsonb), :description) ON CONFLICT (cle) DO NOTHING"
    )
    for cle, valeur, description in NOUVEAUX:
        op.get_bind().execute(
            requete, {"cle": cle, "valeur": json.dumps(valeur), "description": description}
        )


def downgrade() -> None:
    op.execute("DELETE FROM parametres WHERE cle IN ('delai_relance_s', 'candidats_max')")
