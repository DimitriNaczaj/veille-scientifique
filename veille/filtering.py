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


class BehavioralScienceFilter:
    def assess(self, publication):
        text = " ".join(
            part for part in (publication.title, publication.abstract) if part
        ).casefold()
        score = 0
        reasons = []
        for label, weight, pattern in BEHAVIORAL_CONCEPTS:
            if re.search(pattern, text, flags=re.IGNORECASE):
                score += weight
                reasons.append(label)

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
