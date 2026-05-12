"""Scan logic: read the output directory at startup, produce a ResumePlan.

Pure with respect to side effects: scan() performs no writes. It walks
year directories ascending, validates filter consistency for completed
years (M8), and identifies the resume target.

The algorithm exploits the ascending-year invariant: at any natural stop,
there is exactly one "in progress or untouched" year, with everything
before it complete and everything after it untouched. The scan returns
as soon as it identifies that year.
"""

from __future__ import annotations

from extraction.config import Settings
from extraction.types import ResumePlan


def scan(settings: Settings) -> ResumePlan:
    """Walk year directories ascending; produce a ResumePlan.

    Algorithm (per docs/extraction-design.md § Module Structure):

    For each year in settings.resolved_year_range(), ascending:

    1. Directory absent or empty → this is the resume target (fresh start).
       Return immediately.

    2. _SUCCESS present:
       - Read _META.json, verify filter matches settings.filter (M8).
         Mismatch → raise FilterScopeMismatch.
       - Add year to completed_years, continue.

    3. In progress (_META.json present, no _SUCCESS):
       - Verify M3: _CURSOR present. If missing, auto-recover by
         discarding the year and treating as fresh start.
       - Read _META.json, verify filter matches settings.filter (M8).
         Mismatch → raise FilterScopeMismatch.
       - Verify M4: page numbering is contiguous (delegated to
         storage.count_pages_on_disk, which raises CorruptedYearState
         on gaps).
       - This is the resume target. Return with existing_meta populated.

    4. Other inconsistent states (M2 violations, etc.):
       - Orphan page files without _META.json: auto-recover (delete
         orphans, treat as fresh start).
       - Orphan _META.json without page files: auto-recover (delete
         _META.json, treat as fresh start).
       - Otherwise: raise CorruptedYearState.

    If all years in range complete: target=None.

    Args:
        settings: provides output_dir, filter, year_range.

    Returns:
        A ResumePlan. If target is None, the runner has nothing to do.

    Raises:
        FilterScopeMismatch: M8 violation in any encountered year.
        CorruptedYearState: M4 violation, or other unrecoverable corruption.
    """
    ...
