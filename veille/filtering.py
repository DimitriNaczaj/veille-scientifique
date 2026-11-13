import re
from dataclasses import replace

from .models import PublicationPriority


BEHAVIORAL_CONCEPTS = (
    ("comportement", 3, r"\bbehaviou?r(?:al|s)?\b|\bcomportement(?:al|aux|s)?\b"),
    ("normes sociales", 3, r"\bsocial norms?\b|\bnormes? sociales?\b"),
    ("psychologie", 3, r"\bpsycholog(?:y|ical|ie|ique)\b"),
    ("choix et décision", 2, r"\bdecision(?:s| making)?\b|\bchoice(?:s)?\b|\bchoix\b|\bdécision(?:s)?\b"),
    ("intervention", 2, r"\bnudg(?:e|es|ing)\b|\bintervention(?:s)?\b"),
    ("attitudes et motivations", 2, r"\battitudes?\b|\bmotivation(?:s)?\b|\bintentions?\b"),
    ("perception et cognition", 2, r"\bperception(?:s)?\b|\bcogniti(?:on|ve)\b"),
    ("confiance et information", 2, r"\btrust\b|\bmisinformation\b|\bconfiance\b|\bdésinformation\b"),
    ("action collective", 2, r"\bcollective action\b|\baction collective\b"),
    ("participation", 1, r"\bwillingness\b|\bparticipation\b|\bengagement\b"),
    ("ménages et consommateurs", 1, r"\bhouseholds?\b|\bconsumers?\b|\bménages?\b|\bconsommateurs?\b"),
    ("citoyens et opinion", 1, r"\bcitizens?\b|\bvoters?\b|\bpublic opinion\b|\bcitoyens?\b|\bélecteurs?\b"),
    ("bien-être", 1, r"\bwell[ -]being\b|\bsubjective well-being\b|\bbien-être\b"),
)

STRUCTURAL_EXCLUSIONS = (
    (
        "correction éditoriale",
        r"^\s*(?:author|publisher)?\s*(?:correction|corrigendum|erratum)"
        r"(?:\s*:|\s+to\b)",
    ),
    (
        "sommaire de revue",
        r"(?:\bvolume\s+\d+\b.*\bissue\s+\d+\b|^\s*table of contents\b)",
    ),
)

SINGLE_CONCEPT_EXCLUSIONS = (
    (
        "comportement non humain",
        "comportement",
        r"\b(?:mechanical|flexural|mortar|polymer|concrete|alloy|composite|"
        r"rheological|thermal)\b",
    ),
    (
        "comportement non humain",
        "comportement",
        r"\b(?:llm|machine|model|algorithm|robot(?:ic)?)\s+behaviou?r\b",
    ),
    (
        "travail biomédical",
        "comportement",
        r"\b(?:sirna|gene|protein|cellular|molecular|liver-targeted)\b",
    ),
    (
        "décision non humaine",
        "choix et décision",
        r"\b(?:dna|rna|protein|gene|cell(?:ular)?|molecular|pathway|enzyme)\b",
    ),
)

HUMAN_SUBJECT_CONTEXT = (
    r"\b(?:human|people|person|individual|participant|patient|women|men|adult|"
    r"adolescent|child|employee|consumer|citizen|student|farmer|caregiver|"
    r"communit(?:y|ies)|household|user|worker|respondent|volunteer|resident|"
    r"famil(?:y|ies)|ménage|habitant|consommateur)\w*\b"
)

CIRCULAR_TOPIC = (
    r"\b(?:repair(?:s|ed|ing)?|recycl\w*|reus\w*|r[ée]emploi|r[ée]utilis\w*|"
    r"r[ée]par\w*|waste sorting|waste separation|source separation|tri des d[ée]chets|"
    r"second[- ]hand|d['’]occasion|circular econom\w*|[ée]conomie circulaire|"
    r"(?:energy|electricity) (?:sav\w*|conservation|consumption)|"
    r"sobri[ée]t[ée] [ée]nerg[ée]tique|[ée]conomies? d['’][ée]nergie|"
    r"food waste|gaspillage|compost\w*|refill\w*|"
    r"(?:product|clothing|clothes|furniture|tool) (?:sharing|donation)\w*|"
    r"(?:reducing|reduction in) (?:purchases|shopping)|"
    r"r[ée]duction des achats|allongement de la dur[ée]e de vie)\b"
)
CIRCULAR_PRACTICE = (
    r"\b(?:second[- ]hand (?:buying|purchas\w*|shopping|clothing purchas\w*)|"
    r"achats? d['’]occasion|right to repair|droit [àa] la r[ée]paration|"
    r"repair caf[ée]s?|(?:barriers?|motivations?|freins?|obstacles?) "
    r"(?:to|au|aux|à la|à l['’])\s*(?:r[ée]emploi|r[ée]utilis\w*|"
    r"r[ée]par\w*|reus\w*|repair\w*|recycl\w*|waste sorting|"
    r"tri des d[ée]chets|compost\w*|refill\w*))\b"
)
CIRCULAR_TECHNICAL_TITLE = (
    r"\b(?:machine learning (?:forecast|predict)\w*|"
    r"(?:forecast|predict)\w*[^.]{0,70}machine learning|life[- ]cycle assessment|"
    r"optimi[sz]ation|heat exchangers?|sorting machines?|"
    r"taux de rendement|optimisation|analyse du cycle de vie)\b"
)


class BehavioralScienceFilter:
    def assess(self, publication):
        title = (publication.title or "").casefold()
        text = " ".join(
            part for part in (publication.title, publication.abstract) if part
        ).casefold()
        score = 0
        reasons = []
        for label, weight, pattern in BEHAVIORAL_CONCEPTS:
            if re.search(pattern, text, flags=re.IGNORECASE):
                score += weight
                reasons.append(label)

        for label, pattern in STRUCTURAL_EXCLUSIONS:
            if re.search(pattern, title, flags=re.IGNORECASE):
                score = 0
                reasons.append(label)
                break

        if score:
            for label, concept, pattern in SINGLE_CONCEPT_EXCLUSIONS:
                if reasons == [concept] and re.search(
                    pattern, title, flags=re.IGNORECASE
                ) and not re.search(
                    HUMAN_SUBJECT_CONTEXT, text, flags=re.IGNORECASE
                ):
                    score = 0
                    reasons.append(label)
                    break

        if (not reasons or score) and not re.search(CIRCULAR_TECHNICAL_TITLE, title):
            if re.search(CIRCULAR_PRACTICE, text) or (
                re.search(CIRCULAR_TOPIC, text)
                and re.search(HUMAN_SUBJECT_CONTEXT, text)
            ):
                score = max(score, 2)
                reasons.append("pratique circulaire ou sobriété énergétique")

        if score >= 5:
            priority = PublicationPriority.HIGH
        elif score >= 2:
            priority = PublicationPriority.WATCH
        else:
            priority = PublicationPriority.EXCLUDED

        return replace(
            publication,
            relevance_score=score,
            relevance_reasons=tuple(reasons),
            priority=priority,
        )
