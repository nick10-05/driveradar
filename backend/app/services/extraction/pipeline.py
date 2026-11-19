"""The extraction pipeline: extractor → normaliser → audit row (DESIGN §4.1, §4.6, §4.8).

Interview notes:
- AI is never a single point of failure. Whatever the extractor does (disabled, timeout,
  garbage, even an unexpected exception), this returns a result and the admin gets a
  form: pre-filled when the AI worked, empty otherwise.
- Nothing is published here, and no drive is created: the result is a draft for review.
  Publishing stays a separate human step (D9).
- Every attempt is written to extraction_runs, failures included, with latency and token
  counts, so cost and reliability are measurable later.
"""

import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Branch, BranchAlias, ExtractionRun
from app.services.extraction.extractors import Extractor
from app.services.extraction.normaliser import normalise
from app.services.extraction.prompt import PROMPT_VERSION
from app.services.extraction.schema import (
    DraftDrive,
    ExtractionResult,
    ExtractionStatus,
    FieldIssue,
)

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class PipelineOutput:
    run: ExtractionRun
    status: ExtractionStatus
    draft: DraftDrive
    issues: list[FieldIssue]


async def branch_lookup(session: AsyncSession) -> dict[str, str]:
    """Lower-cased code or alias → branch code, from the `branches` + `branch_aliases` tables."""
    lookup = {code.casefold(): code for code in await session.scalars(select(Branch.code))}
    aliases = await session.execute(select(BranchAlias.alias, BranchAlias.branch_code))
    lookup.update({alias.casefold(): code for alias, code in aliases})
    return lookup


async def run_extraction(
    session: AsyncSession,
    extractor: Extractor,
    *,
    raw_text: str,
    provider: str,
    created_by: uuid.UUID,
) -> PipelineOutput:
    started = time.perf_counter()
    try:
        result = await extractor.extract(raw_text)
    except Exception as exc:  # any extractor bug must still fall back to manual entry
        # Type only: an exception message could contain notice text or model output.
        log.error("extractor_crashed", error_type=type(exc).__name__)
        result = ExtractionResult(status="error", error="unexpected")
    latency_ms = round((time.perf_counter() - started) * 1000)

    draft, issues = DraftDrive(), list[FieldIssue]()
    if result.status == "ok" and result.notice is not None:
        draft, issues = normalise(
            result.notice,
            raw_text,
            branch_lookup=await branch_lookup(session),
            now=datetime.now(UTC),
            rejected_fields=result.rejected_fields,
        )

    run = ExtractionRun(
        created_by=created_by,
        raw_text=raw_text,
        provider=provider,
        model=result.model,
        prompt_version=PROMPT_VERSION,
        status=result.status,
        error=result.error,
        output_json=draft.model_dump(mode="json") if result.status == "ok" else None,
        issues=[issue.model_dump() for issue in issues],
        latency_ms=latency_ms,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
    )
    session.add(run)
    await session.commit()
    log.info(
        "extraction_run",
        extraction_run_id=str(run.id),
        status=result.status,
        error=result.error,
        provider=provider,
        model=result.model,
        latency_ms=latency_ms,
        issues=len(issues),
    )
    return PipelineOutput(run=run, status=result.status, draft=draft, issues=issues)
