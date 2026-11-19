"""Eval CLI: run the golden set through the configured extractor + normaliser (DESIGN §4.9).

    DATABASE_URL=... LLM_PROVIDER=... uv run python -m evals.run

Run by hand only, never in CI (CI never calls a real LLM). Writes a Markdown report to
evals/results/<date>-<provider>-<model>-<prompt_version>.md, to be committed with any
prompt or model change so the README's numbers have a source.

Interview notes:
- It runs the same Extractor and normalise() the API uses, so the score measures the real
  pipeline, not a copy. It skips run_extraction() only because that writes audit rows
  owned by an admin; evals shouldn't fill the production audit log.
- Each notice carries its own `as_of` date, passed as "today" to the prompt and as `now`
  to the normaliser. Without that, year-less dates ("2 Dec") and the past-deadline check
  would give different answers depending on when the eval runs.
- Branch codes come from the real `branches` / `branch_aliases` tables (DATABASE_URL),
  so alias coverage is measured too: a missing alias shows up as a missed branch.
"""

import asyncio
import json
import os
import re
import ssl
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from datetime import time as dtime
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import LlmSettings, normalize_database_url
from app.schemas.drive import IST
from app.services.extraction.evidence import quote_in_text
from app.services.extraction.extractors import Extractor, build_extractor
from app.services.extraction.normaliser import normalise
from app.services.extraction.pipeline import branch_lookup
from app.services.extraction.prompt import PROMPT_VERSION
from app.services.extraction.schema import DraftDrive, ExtractionResult
from evals.metrics import FIELDS, OUTCOMES, CaseRun, Summary, score_case, summarise

EVALS_DIR = Path(__file__).parent
GOLDEN_DIR = EVALS_DIR / "golden"
RESULTS_DIR = EVALS_DIR / "results"


@dataclass(frozen=True, slots=True)
class Case:
    id: str
    synthetic: bool
    as_of: date
    raw_text: str
    expected: Mapping[str, Any]


class GoldenFileError(ValueError):
    pass


def load_cases(directory: Path = GOLDEN_DIR) -> list[Case]:
    cases = []
    for path in sorted(directory.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        missing = set(FIELDS) - set(data.get("expected", {}))
        if missing:
            raise GoldenFileError(f"{path.name}: expected is missing {sorted(missing)}")
        cases.append(
            Case(
                id=data["id"],
                synthetic=bool(data["synthetic"]),
                as_of=date.fromisoformat(data["as_of"]),
                raw_text=data["raw_text"],
                expected=data["expected"],
            )
        )
    return cases


def as_of_now(day: date) -> datetime:
    """Noon IST on the notice's as_of day, as the normaliser's `now`."""
    return datetime.combine(day, dtime(12, 0), IST).astimezone(UTC)


async def evaluate(
    cases: Sequence[Case],
    make_extractor: Callable[[date], Extractor],
    lookup: Mapping[str, str],
) -> list[CaseRun]:
    runs = []
    for case in cases:
        extractor = make_extractor(case.as_of)
        started = time.perf_counter()
        try:
            result = await extractor.extract(case.raw_text)
        except Exception:  # same fallback as the API: a crash is just an "error" run
            result = ExtractionResult(status="error", error="unexpected")
        latency_ms = round((time.perf_counter() - started) * 1000)

        draft, checked, passed = DraftDrive(), 0, 0
        if result.status == "ok" and result.notice is not None:
            draft, _issues = normalise(
                result.notice,
                case.raw_text,
                branch_lookup=lookup,
                now=as_of_now(case.as_of),
                rejected_fields=result.rejected_fields,
            )
            quotes = [q for q in result.notice.evidence.values() if q]
            checked = len(quotes)
            passed = sum(quote_in_text(q, case.raw_text) for q in quotes)

        runs.append(
            CaseRun(
                case_id=case.id,
                status=result.status,
                latency_ms=latency_ms,
                fields=score_case(case.expected, draft),
                evidence_checked=checked,
                evidence_passed=passed,
                error=result.error,
            )
        )
    return runs


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def render(
    summary: Summary,
    runs: Sequence[CaseRun],
    cases: Sequence[Case],
    *,
    provider: str,
    model: str | None,
    run_date: date,
) -> str:
    synthetic = sum(c.synthetic for c in cases)
    statuses = ", ".join(f"{k} {v}" for k, v in sorted(summary.statuses.items()))
    latency = summary.mean_latency_ms
    lines = [
        f"# Eval: {provider} / {model or '-'} / prompt {PROMPT_VERSION}",
        "",
        f"- Date: {run_date.isoformat()}",
        f"- Notices: {summary.cases} ({synthetic} synthetic, {summary.cases - synthetic} real)",
        f"- Extractor status: {statuses}",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Stated fields extracted exactly | {_pct(summary.stated_accuracy)} |",
        f"| Unstated fields invented (hallucination) | {_pct(summary.hallucination_rate)} |",
        f"| Branch precision / recall | {_pct(summary.branch_precision)} / "
        f"{_pct(summary.branch_recall)} |",
        f"| Evidence quotes found in notice | {_pct(summary.evidence_pass_rate)} "
        f"({summary.evidence_passed}/{summary.evidence_checked}) |",
        f"| Invalid output rate | {_pct(summary.invalid_rate)} |",
        f"| Mean latency | {'n/a' if latency is None else f'{latency:.0f} ms'} |",
        "",
        "## Per field",
        "",
        "| Field | " + " | ".join(OUTCOMES) + " |",
        "|---|" + "---|" * len(OUTCOMES),
    ]
    for name in FIELDS:
        counts = summary.per_field[name]
        lines.append(f"| {name} | " + " | ".join(str(counts[o]) for o in OUTCOMES) + " |")

    lines += ["", "## Errors", ""]
    bad = ("missed", "wrong", "hallucinated")
    errors = [(run, r) for run in runs for r in run.fields if r.outcome in bad]
    if not errors:
        lines.append("None.")
    for run, r in errors:
        lines.append(
            f"- `{run.case_id}` {r.field}: {r.outcome}, expected `{r.expected}`, got `{r.actual}`"
        )
    if synthetic:
        lines += [
            "",
            "_Synthetic notices are hand-written to exercise specific rules; they are not "
            "real notices, and scores on them are not a claim about real-world accuracy._",
        ]
    return "\n".join(lines) + "\n"


def result_path(provider: str, model: str | None, run_date: date) -> Path:
    slug = re.sub(r"[^A-Za-z0-9._]+", "-", f"{provider}-{model or 'none'}").strip("-")
    return RESULTS_DIR / f"{run_date.isoformat()}-{slug}-{PROMPT_VERSION}.md"


async def load_branch_lookup(database_url: str) -> dict[str, str]:
    url, ssl_required = normalize_database_url(database_url)
    connect_args = {"ssl": ssl.create_default_context()} if ssl_required else {}
    engine = create_async_engine(url, connect_args=connect_args)
    try:
        async with AsyncSession(engine) as session:
            return await branch_lookup(session)
    finally:
        await engine.dispose()


async def main() -> Path:  # pragma: no cover - needs a DB and (maybe) a real provider
    settings = LlmSettings()
    lookup = await load_branch_lookup(os.environ["DATABASE_URL"])
    cases = load_cases()
    async with httpx.AsyncClient() as client:
        runs = await evaluate(
            cases, lambda day: build_extractor(settings, client, today=lambda: day), lookup
        )
    today = datetime.now(IST).date()
    report = render(
        summarise(runs),
        runs,
        cases,
        provider=settings.llm_provider,
        model=settings.llm_model,
        run_date=today,
    )
    path = result_path(settings.llm_provider, settings.llm_model, today)
    path.parent.mkdir(exist_ok=True)
    path.write_text(report, encoding="utf-8")
    return path


if __name__ == "__main__":  # pragma: no cover - thin CLI wrapper
    if "DATABASE_URL" not in os.environ:
        sys.exit("usage: DATABASE_URL=... [LLM_*=...] python -m evals.run")
    print(f"Wrote {asyncio.run(main())}")
