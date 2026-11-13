import httpx
import pytest

from livraison.config import parametres
from livraison.services.itineraire import (
    ErreurItineraire,
    ItineraireAvecRepli,
    ItineraireDroiteLigne,
    ItineraireOSRM,
    creer_itineraire,
)

PLATEAU = (-4.0267, 5.3200)
COCODY = (-3.9870, 5.3600)


def _osrm(handler) -> tuple[ItineraireOSRM, list[httpx.Request]]:
    vues: list[httpx.Request] = []

    def enveloppe(requete: httpx.Request) -> httpx.Response:
        vues.append(requete)
        return handler(requete)

    client = httpx.AsyncClient(transport=httpx.MockTransport(enveloppe))
    return ItineraireOSRM("http://osrm", client=client), vues


def _reponse_ok(duree=600.0):
    return lambda requete: httpx.Response(
        200, json={"code": "Ok", "routes": [{"duration": duree, "distance": 5000.0}]}
    )


async def test_osrm_lit_la_duree_et_envoie_longitude_puis_latitude():
    osrm, vues = _osrm(_reponse_ok(600.0))
    assert await osrm.duree_s(PLATEAU, COCODY, "voiture") == 600.0
    url = str(vues[0].url)
    assert "/route/v1/driving/-4.026700,5.320000;-3.987000,5.360000" in url
    assert "overview=false" in url


async def test_osrm_ajuste_la_duree_selon_le_vehicule():
    osrm, _ = _osrm(_reponse_ok(600.0))
    voiture = await osrm.duree_s(PLATEAU, COCODY, "voiture")
    moto = await osrm.duree_s(PLATEAU, COCODY, "moto")
    velo = await osrm.duree_s(PLATEAU, COCODY, "velo")
    assert moto < voiture < velo
    assert velo == pytest.approx(600 * 25 / 15)


async def test_osrm_met_les_trajets_en_cache():
    osrm, vues = _osrm(_reponse_ok())
    await osrm.duree_s(PLATEAU, COCODY, "voiture")
    await osrm.duree_s(PLATEAU, COCODY, "moto")  # même trajet, autre véhicule : pas de nouvel appel
    assert len(vues) == 1
    await osrm.duree_s(COCODY, PLATEAU, "voiture")  # sens inverse : nouveau trajet
    assert len(vues) == 2


async def test_osrm_cache_borne():
    osrm, vues = _osrm(_reponse_ok())
    osrm._taille_cache = 1
    await osrm.duree_s(PLATEAU, COCODY, "voiture")
    await osrm.duree_s(COCODY, PLATEAU, "voiture")  # évince le premier
    await osrm.duree_s(PLATEAU, COCODY, "voiture")  # doit être recalculé
    assert len(vues) == 3


@pytest.mark.parametrize(
    "reponse",
    [
        httpx.Response(200, json={"code": "NoRoute", "routes": []}),
        httpx.Response(500, text="erreur"),
        httpx.Response(200, text="pas du json"),
    ],
)
async def test_osrm_signale_les_erreurs(reponse):
    osrm, _ = _osrm(lambda requete: reponse)
    with pytest.raises(ErreurItineraire):
        await osrm.duree_s(PLATEAU, COCODY, "voiture")


async def test_osrm_injoignable():
    def injoignable(requete):
        raise httpx.ConnectError("connexion refusée")

    osrm, _ = _osrm(injoignable)
    with pytest.raises(ErreurItineraire):
        await osrm.duree_s(PLATEAU, COCODY, "voiture")


async def test_repli_sur_la_ligne_droite_quand_osrm_tombe():
    def injoignable(requete):
        raise httpx.ConnectError("connexion refusée")

    osrm, _ = _osrm(injoignable)
    itineraire = ItineraireAvecRepli(osrm, ItineraireDroiteLigne())
    duree = await itineraire.duree_s(PLATEAU, COCODY, "moto")
    assert duree == await ItineraireDroiteLigne().duree_s(PLATEAU, COCODY, "moto")
    assert itineraire.nb_replis == 1


async def test_pas_de_repli_quand_osrm_repond():
    osrm, _ = _osrm(_reponse_ok(600.0))
    itineraire = ItineraireAvecRepli(osrm, ItineraireDroiteLigne())
    assert await itineraire.duree_s(PLATEAU, COCODY, "voiture") == 600.0
    assert itineraire.nb_replis == 0


def test_choix_du_moteur_par_la_configuration():
    assert isinstance(creer_itineraire("droite_ligne", parametres.osrm_url), ItineraireDroiteLigne)
    assert isinstance(creer_itineraire("osrm", parametres.osrm_url), ItineraireAvecRepli)
    with pytest.raises(ValueError):
        creer_itineraire("google", parametres.osrm_url)
