"""Entry point for `python -m openalex_pipeline.extraction`.

Wires Settings → run(); translates the returned RunSummary into an exit code.
"""

from __future__ import annotations

import sys


def main() -> int:
    """Load settings, execute the run, return an exit code.

    Returns:
        0 if the run completed cleanly (all years done) or stopped cleanly
            on credit exhaustion. Non-zero on any uncaught ExtractionError.

    Note:
        Uncaught exceptions are NOT swallowed here; they propagate to the
        interpreter so the traceback is visible. The non-zero exit code
        comes from the interpreter's default exception handling.
    """
    ...


if __name__ == "__main__":
    sys.exit(main())
