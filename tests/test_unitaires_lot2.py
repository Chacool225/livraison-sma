import itertools

import pytest

from livraison.agents.agent_livreur import Course, LivreurAgent
from livraison.db.modeles import EtatCommande as E
from livraison.modele.cout import cout_offre
from livraison.modele.etats import TRANSITIONS, TransitionInterdite, verifier_transition
from livraison.modele.geo import distance_m
from livraison.services.itineraire import ItineraireDroiteLigne

PLATEAU = (-4.0267, 5.3200)
COCODY = (-3.9870, 5.3600)


def test_distance_connue():
    assert distance_m(PLATEAU, PLATEAU) == 0
    assert 5500 < distance_m(PLATEAU, COCODY) < 6500
    assert distance_m(PLATEAU, COCODY) == pytest.approx(distance_m(COCODY, PLATEAU))


def test_cout_offre_formule_du_cahier_des_charges():
    # 10 min vers l'enlèvement + 2 min de détour + 3 x 2 courses en cours = 18
    assert cout_offre(600, 120, 2, 3) == 18.0
    assert cout_offre(0, 0, 0, 3) == 0.0
    assert cout_offre(90, 0, 0, 3) == 1.5


async def test_itineraire_selon_le_vehicule():
    it = ItineraireDroiteLigne()
    velo = await it.duree_s(PLATEAU, COCODY, "velo")
    moto = await it.duree_s(PLATEAU, COCODY, "moto")
    assert velo > moto > 0
    assert await it.duree_s(PLATEAU, PLATEAU, "moto") == 0


def test_cycle_de_vie_nominal():
    chemin = [
        E.CREEE,
        E.VALIDEE,
        E.EN_RECHERCHE,
        E.ATTRIBUEE,
        E.ENLEVEE,
        E.EN_LIVRAISON,
        E.LIVREE,
        E.CLOTUREE,
    ]
    for actuel, suivant in itertools.pairwise(chemin):
        verifier_transition(actuel, suivant)


@pytest.mark.parametrize(
    ("actuel", "suivant"),
    [
        (E.CREEE, E.LIVREE),
        (E.LIVREE, E.EN_RECHERCHE),
        (E.ANNULEE, E.VALIDEE),
        (E.ENLEVEE, E.EN_RECHERCHE),
    ],
)
def test_transitions_interdites(actuel, suivant):
    with pytest.raises(TransitionInterdite):
        verifier_transition(actuel, suivant)


def test_tous_les_etats_ont_une_regle():
    assert set(TRANSITIONS) == set(E)


# --------------------------------------------------------------------------- agent livreur isolé

A_ = (-4.0250, 5.3210)


class Horloge:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _livreur(**options):
    horloge = options.pop("horloge", Horloge())
    agent = LivreurAgent(
        "x@localhost",
        "mdp",
        livreur_id="L1",
        annuaire_jid="an@localhost",
        dispatcher_jid="di@localhost",
        position=A_,
        horloge=horloge,
        **options,
    )
    agent.en_ligne = True
    return agent, horloge


def test_motifs_de_refus():
    agent, horloge = _livreur(capacite=1, taille_max="petit")
    base = (PLATEAU, "petit", 3000, 60)
    assert agent.motif_de_refus(*base) is None
    assert agent.motif_de_refus(PLATEAU, "moyen", 3000, 60) == "colis_trop_grand"
    assert agent.motif_de_refus(COCODY, "petit", 3000, 60) == "hors_zone"
    horloge.t += 61
    assert agent.motif_de_refus(*base) == "position_trop_ancienne"
    horloge.t -= 61
    agent.reservations["autre"] = horloge()
    assert agent.motif_de_refus(*base) == "sature"
    agent.en_ligne = False
    assert agent.motif_de_refus(*base) == "hors_ligne"


async def test_cout_sans_course_en_cours():
    agent, _ = _livreur()
    cout, eta = await agent.calculer_offre(PLATEAU, 3)
    assert cout == round(eta / 60, 2) and eta > 0  # pas de détour, pas de charge


async def test_cout_avec_course_en_cours_sur_le_chemin():
    agent, _ = _livreur()
    sur_le_chemin = (-4.0100, 5.3300)  # entre le livreur et la prochaine étape, colinéaire
    agent.courses["c1"] = Course(
        "c1", sur_le_chemin, COCODY, etat="enlevee"
    )  # prochain arrêt : COCODY
    cout_vide, _ = await _livreur()[0].calculer_offre(PLATEAU, 3)
    cout, _ = await agent.calculer_offre(PLATEAU, 3)
    assert cout >= cout_vide + 3  # au moins la pénalité de charge (3 x 1 course)


def test_une_proposition_reserve_la_place():
    agent, horloge = _livreur(capacite=2)
    agent.courses["c1"] = Course("c1", PLATEAU, COCODY)
    assert agent.motif_de_refus(PLATEAU, "petit", 3000, 60) is None
    agent.reservations["c2"] = horloge()
    assert agent.motif_de_refus(PLATEAU, "petit", 3000, 60) == "sature"
