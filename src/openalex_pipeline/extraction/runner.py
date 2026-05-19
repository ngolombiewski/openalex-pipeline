"""Runner: orchestrates the full extraction job.

Public entry point: run(settings) → RunSummary.

Composes the other modules:
- scan.scan() to determine resume point.
- http.request_page() to fetch each page.
- storage.* to mutate the filesystem.

Holds the year/page loop and the error-handling policy. Catches
CreditsExhausted as a clean stop signal; handles DriftDetected by
discarding the year and retrying once; lets all other errors propagate.
"""

from __future__ import annotations

from openalex_pipeline.extraction.config import Settings
from openalex_pipeline.extraction.types import ResumeTarget, RunSummary, YearOutcome


def run(settings: Settings) -> RunSummary:
    """Execute the full extraction job.

    Top-level flow:

    1. Call scan() to get the ResumePlan.
    2. If plan.recovery is present: call storage.discard_year() for that
       year, then treat plan.target as a fresh start for the same year.
    3. If plan.target is None: log "all complete", return summary with
       stopped_reason="all_complete" and empty year list.
    4. Otherwise, iterate years ascending starting from plan.target.year.
       For each year:
       a. Call _process_year(); append the resulting YearOutcome.
       b. On CreditsExhausted from inside _process_year(): record an
          "in_progress" outcome for the current year if any pages were
          fetched, then return summary with
          stopped_reason="credits_exhausted". Do not re-raise.
       c. On DriftDetected: discard the year via storage.discard_year(),
          call _process_year() again with resume_target=None. If a second
          drift occurs, propagate. Append a "drifted_restarted" outcome
          on success.
    5. After all years processed: return summary with
       stopped_reason="all_complete".

    The resume_target argument to _process_year() is non-None only for
    the first iteration (the actual resume target from scan); for all
    subsequent years it is None (fresh start).

    Args:
        settings: configuration for this run.

    Returns:
        A RunSummary describing what was processed.

    Raises:
        ReconciliationFailed: M7 violation (loud).
        FilterScopeMismatch: M8 violation (loud).
        CorruptedYearState: M4 violation or other unrecoverable state.
        BadRequest: configuration bug (loud).
        HTTPError: transient errors that survived max_retries (loud).
        DriftDetected: only if a year drifts twice in one run.
    """
    ...


# --- Private helpers ---


def _process_year(
    settings: Settings,
    year: int,
    resume_target: ResumeTarget | None,
) -> YearOutcome:
    """Fetch all pages for one year; finalize on completion.

    Two modes:

    - Fresh start (resume_target is None): first response populates
      _META.json via storage.initialize_year(). Subsequent pages walk
      the cursor from the first response onward.

    - Resume (resume_target is not None): the first request uses
      resume_target.next_cursor. The response's meta_count is compared
      against resume_target.existing_meta.expected_count (M6); mismatch
      raises DriftDetected before any disk mutation. If the ordered work IDs
      in the fetched page match the ordered work IDs in the last page file
      already on disk, the runner treats the cursor as stale-by-one (M5) and
      overwrites the last page instead of appending a new page.

    Inner loop, per page:
    1. Call http.request_page() with the current cursor.
    2. On first page of a fresh year: call storage.initialize_year().
    3. On first page of a resumed year: perform M6 drift check.
    4. On resumed years, perform M5 stale-cursor detection before writing
       the first fetched page.
    5. Call storage.write_page() with the records and next_cursor.
    6. If next_cursor is None: break (last page reached).

    After loop: call storage.finalize_year() (which performs M7 and
    writes _SUCCESS on success).

    This function does NOT catch CreditsExhausted — it propagates up to
    run(), which decides the policy. Same for DriftDetected and all
    other ExtractionError subclasses.

    Args:
        settings: configuration.
        year: the publication year to process.
        resume_target: non-None to resume an in-progress year; None for
            a fresh start. When non-None, resume_target.year must equal
            `year` (caller's responsibility to ensure).

    Returns:
        A YearOutcome with status="complete" and pages/records counts
        reflecting work done in this invocation.

    Raises:
        DriftDetected: M6 violation on resume.
        ReconciliationFailed: M7 violation at finalization.
        CreditsExhausted: 429 from the API (propagated; runner handles).
        Any other HTTPError or ExtractionError subclass.
    """
    ...
