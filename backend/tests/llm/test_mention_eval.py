"""The mention judge against real records and the real model. Run with:
uv run --env-file ../.env pytest -m llm tests/llm/test_mention_eval.py

The expected roles were read from the records by hand; where two readings are fair, both are
accepted. Conditions include trials the registry calls mention-only because they register a
narrower name ("Lung Adenocarcinoma"): the judge should see that they study lung cancer.
"""

import os

import httpx
import pytest
from openai import AsyncOpenAI

from cheiron.adapters.outbound.ctgov.client import CtGovTrialSource
from cheiron.adapters.outbound.openai_mentions import OpenAIMentionJudge
from cheiron.application.mentions import explain_mentions
from cheiron.domain.membership import MentionRole as R

pytestmark = [pytest.mark.llm, pytest.mark.anyio]

DRUG = {
    "NCT04003636": {R.STUDIED},  # KEYNOTE-966: pembrolizumab + chemotherapy vs placebo + chemotherapy
    "NCT05910710": {R.STUDIED},  # observational: impact of pembrolizumab on neoadjuvant chemotherapy
    "NCT03772899": {R.GIVEN_ALONGSIDE},  # fecal transplant combined with standard-of-care anti-PD-1
    "NCT07050524": {R.GIVEN_ALONGSIDE},  # omega-3 supplementation during standard immunotherapy
    "NCT04764487": {R.GIVEN_ALONGSIDE},  # web follow-up for patients on axitinib/pembrolizumab
    "NCT05627960": {R.ELIGIBILITY},  # requires prior chemotherapy with a PD-(L)1 agent
    "NCT04698681": {R.ELIGIBILITY, R.GIVEN_ALONGSIDE},  # NGS screening of patients eligible for it
    "NCT02449837": {R.GIVEN_ALONGSIDE, R.ELIGIBILITY},  # circulating tumour cells during radiotherapy
    "NCT02600143": {R.STUDIED, R.GIVEN_ALONGSIDE},  # predicting colitis in patients on checkpoint inhibitors
}


@pytest.fixture
async def judge():
    async with AsyncOpenAI() as client:
        yield OpenAIMentionJudge(client, os.environ.get("OPENAI_MODEL") or "gpt-5.4-mini", reasoning_effort="low")


CONDITION = {
    "NCT03538171": {R.STUDIED},  # exemestane +/- entinostat in HR+ breast cancer
    "NCT07393321": {R.STUDIED},  # NTQ1062 + fulvestrant in HR+/HER2- breast cancer
    "NCT06104709": {R.STUDIED},  # cryoablation; registers "Lung Adenocarcinoma"
    "NCT06234579": {R.STUDIED},  # ALK-positive NSCLC; registers "NSCLC Stage IV"
}


async def _verdicts(judge, expected, names):
    async with httpx.AsyncClient(timeout=60) as http:
        source = CtGovTrialSource(http)
        ids = list(expected)
        return [v for batch in (ids[:5], ids[5:]) if batch for v in await explain_mentions(batch, names, source, judge)]


async def test_drug_roles_match_a_reading_of_the_records(judge) -> None:
    verdicts = await _verdicts(judge, DRUG, ["pembrolizumab", "Pembrolizumab"])

    assert not {v.nct_id: v.role for v in verdicts if v.role not in DRUG[v.nct_id]}
    assert all(v.quote for v in verdicts)


async def test_condition_roles_match_a_reading_of_the_records(judge) -> None:
    verdicts = await _verdicts(judge, CONDITION, ["breast cancer", "lung cancer"])

    assert not {v.nct_id: v.role for v in verdicts if v.role not in CONDITION[v.nct_id]}
    assert all(v.quote for v in verdicts)
