"""v2: the trust-weighted vote and the confidence score.

Idea from Med-TAMARA (Wu & Day, IEEE IRI 2025): several judges give a label, each judge's vote counts as much as
its reliability (trust weight), and a confidence score decides when a person should check the answer.
Here the label is the category of the user's question.
"""

import json
import os
from pathlib import Path

HERE = Path(__file__).parent
WEIGHTS_FILE = Path(os.getenv("TRUST_WEIGHTS_FILE") or HERE / "trust_weights.json")   # another file for a repeated run

CATEGORIES = ["route", "cost", "rule", "info", "my_order", "human", "politics", "personal", "off_topic"]
CATEGORY_NAMES = {"route": "找班次、座位", "cost": "費用", "rule": "訂票與乘車規則", "info": "專案資訊",
                  "my_order": "我的訂單", "human": "付款問題、退款、客訴", "politics": "政治",
                  "personal": "個資", "off_topic": "題目外或要求違反規則"}

# The first tool the answer agent chooses tells what it thinks the question is about (judge C).
TOOL_CATEGORY = {"search_routes": "route", "get_route": "route", "calculate_cost": "cost",
                 "search_rules": "rule", "get_project_info": "info", "get_my_order": "my_order",
                 "transfer_to_human": "human"}

JUDGES = {"A": "程式規則", "B": "Embedding 範例比對", "C": "回答 Agent 選的工具"}
DEFAULT_WEIGHTS = {"A": 1.0, "B": 1.0, "C": 1.0}

CONFIDENCE_THRESHOLD = 0.6      # below this, the answer asks the user to confirm with the team
ONE_VOTE_CAP = 0.7              # one judge alone cannot give full agreement
REVIEW_FACTOR = {"passed": 1.0, "fixed_by_code": 0.9, "rewritten": 0.8, "failed": 0.4, "skipped": 0.7}


def load_weights():
    """The trust weights worked out by evaluate.py on the dev questions (equal weights if there is no file)."""
    try:
        data = json.loads(WEIGHTS_FILE.read_text(encoding="utf-8"))
        return {j: float(data["weights"][j]) for j in JUDGES}
    except (OSError, KeyError, ValueError):
        return dict(DEFAULT_WEIGHTS)


def weighted_vote(votes, weights):
    """votes: {"A": "route", "B": "rule", "C": None (no vote)}.
    Returns (winning category or None, agreement 0-1, score of each category)."""
    scores = {}
    for judge, category in votes.items():
        if category:
            scores[category] = scores.get(category, 0.0) + weights.get(judge, 1.0)
    if not scores:
        return None, 0.0, {}
    winner = max(scores, key=scores.get)
    agreement = scores[winner] / sum(scores.values())
    if sum(1 for c in votes.values() if c) == 1:
        agreement = min(agreement, ONE_VOTE_CAP)
    return winner, round(agreement, 3), {c: round(s, 3) for c, s in scores.items()}


def confidence(agreement, review_status):
    """How sure v2 is about this answer: how much the judges agree x how the review went."""
    return round(agreement * REVIEW_FACTOR.get(review_status, 0.7), 3)
