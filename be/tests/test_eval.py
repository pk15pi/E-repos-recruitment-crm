from pathlib import Path

import pytest

from evals.harness import aggregate, filter_violation_rate, score_case

pytestmark = pytest.mark.django_db

ASHA = Path("evals/fixtures/asha.txt").read_text()
SHORT = """
Lata Menon
lata.menon@example.com
Mumbai
Skills
Java, Spring
Experience
Developer, Orbit Systems — Jun 2021 – Dec 2023
"""


def test_extraction_metrics_and_filter_violations(agency):
    report = aggregate(
        [
            score_case(ASHA, ["asha.rao@example.com"], ["Python", "Django", "PostgreSQL"]),
            score_case(SHORT, ["lata.menon@example.com"], ["Java"]),
        ]
    )
    assert report["email_recall"] == 1
    assert report["email_precision"] == 1
    assert report["skill_recall"] >= 0.6
    assert report["hallucination_rate"] == 0
    assert filter_violation_rate(agency["org"]) == 0
