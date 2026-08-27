"""Comparaison de titres, pour valider une recherche bibliographique.

Une recherche par titre peut renvoyer un article voisin. Rattacher le résumé
d’un autre article serait pire que n’en rattacher aucun : tout résultat est
donc recomparé au titre demandé.
"""
import re
from difflib import SequenceMatcher

MINIMUM_RATIO = 0.90
MINIMUM_LENGTH = 25
MAXIMUM_WORDS = 24


def comparable(title):
    """Réduit un titre à ses mots, pour comparer deux graphies."""
    return " ".join(re.sub(r"[^0-9a-z]+", " ", str(title or "").casefold()).split())


def searchable(title):
    """Titre réduit aux mots, utilisable dans une requête d’API."""
    if not title or len(str(title).strip()) < MINIMUM_LENGTH:
        return None
    words = comparable(title).split()[:MAXIMUM_WORDS]
    return " ".join(words) or None


def same_work(wanted, found):
    if not wanted or not found:
        return False
    ratio = SequenceMatcher(None, comparable(wanted), comparable(found)).ratio()
    return ratio >= MINIMUM_RATIO
