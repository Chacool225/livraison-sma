"""reglages de surveillance du signal GPS

Revision ID: 0003
Revises: 0002
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

NOUVEAUX = [
    ("perte_signal_s", 120, "Sans position depuis ce délai, le livreur est jugé injoignable"),
    (
        "controle_gps_intervalle_s",
        15,
        "Fréquence de la vérification des positions des courses en cours",
    ),
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
    op.execute(
        "DELETE FROM parametres WHERE cle IN ('perte_signal_s', 'controle_gps_intervalle_s')"
    )
