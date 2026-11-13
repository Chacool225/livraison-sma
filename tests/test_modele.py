import pytest
from geoalchemy2.elements import WKTElement
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from livraison.db.modeles import Commande, ModePaiement, Parametre, Role, TailleColis, Utilisateur


async def test_parametres_de_depart(session):
    valeurs = {p.cle: p.valeur for p in await session.scalars(select(Parametre))}
    assert len(valeurs) == 11
    assert valeurs["penalite_charge"] == 3
    assert valeurs["delai_confirmation_s"] == 30
    assert valeurs["delai_relance_s"] == 5
    assert valeurs["candidats_max"] == 20


async def test_commande_avec_coordonnees_et_numero(session):
    client = Utilisateur(telephone="+2250700000001", role=Role.CLIENT)
    session.add(client)
    await session.flush()
    plateau = WKTElement("POINT(-4.0267 5.3200)", srid=4326)  # longitude latitude
    cocody = WKTElement("POINT(-3.9870 5.3600)", srid=4326)
    commande = Commande(
        client_id=client.id,
        adresse_enlevement="Plateau",
        point_enlevement=plateau,
        adresse_livraison="Cocody",
        point_livraison=cocody,
        taille_colis=TailleColis.PETIT,
        prix=1500,
        mode_paiement=ModePaiement.ESPECES,
    )
    session.add(commande)
    await session.commit()

    assert commande.numero >= 1000
    distance = await session.scalar(
        select(func.ST_Distance(Commande.point_enlevement, Commande.point_livraison))
    )
    assert 4000 < distance < 8000  # mètres, ordre de grandeur Plateau -> Cocody


async def test_une_valeur_hors_liste_est_refusee_par_la_base(session):
    with pytest.raises(IntegrityError):
        await session.execute(
            text(
                "INSERT INTO utilisateurs (telephone, role, statut) VALUES ('+2250700000002', 'pirate', 'actif')"
            )
        )
