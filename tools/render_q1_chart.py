"""Render the Q1 chart (AI's share of CS works) as standalone SVG.

Reads the committed gold extract at assets/q1_ai_share_by_year.csv and writes a
light and a dark variant next to it. README pairs them in a <picture> element so
the chart follows the reader's theme.

Deliberately stdlib-only: one static chart does not justify a plotting
dependency, and hand-emitted SVG keeps the output diffable and crisp.

    uv run python tools/render_q1_chart.py

The partial publication year is drawn dashed with a hollow endpoint and an
explicit annotation. That distinction is required of every Q1 consumer, so it
is a property of the renderer, not of the caller.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "assets"
DATA = ASSETS / "q1_ai_share_by_year.csv"

# Charted range. Earlier years are real but narrate nothing: the series is flat
# from 1950 to the late 1970s, and stretching the axis there flattens the
# dip-and-surge that is the actual result.
YEAR_MIN = 1980

W, H = 920, 460
PAD_L, PAD_R, PAD_T, PAD_B = 62, 150, 64, 52
Y_MIN, Y_MAX = 0.20, 0.58


@dataclass(frozen=True)
class Theme:
    name: str
    surface: str
    text_primary: str
    text_secondary: str
    text_muted: str
    grid: str
    axis: str
    strict: str
    broad: str


LIGHT = Theme(
    name="light",
    surface="#fcfcfb",
    text_primary="#0b0b0b",
    text_secondary="#52514e",
    text_muted="#6f6e6a",
    grid="#e6e5e1",
    axis="#c8c7c2",
    strict="#2a78d6",
    broad="#eb6834",
)

DARK = Theme(
    name="dark",
    surface="#1a1a19",
    text_primary="#ffffff",
    text_secondary="#c3c2b7",
    text_muted="#96958c",
    grid="#2e2e2c",
    axis="#44443f",
    strict="#3987e5",
    broad="#d95926",
)


def load() -> tuple[list[tuple[int, float]], list[tuple[int, float]], int]:
    """Return (strict, broad, partial_year) series sorted by year."""
    strict: list[tuple[int, float]] = []
    broad: list[tuple[int, float]] = []
    partial_year = 0
    with DATA.open() as fh:
        for row in csv.DictReader(fh):
            year = int(row["publication_year"])
            if year < YEAR_MIN:
                continue
            if row["is_partial_year"] == "true":
                partial_year = max(partial_year, year)
            target = strict if row["variant"] == "strict" else broad
            target.append((year, float(row["share"])))
    strict.sort()
    broad.sort()
    if not strict or not broad:
        raise ValueError(f"no rows at or after {YEAR_MIN} in {DATA}")
    return strict, broad, partial_year


def render(theme: Theme, strict, broad, partial_year: int) -> str:
    years = [y for y, _ in strict]
    x0, x1 = years[0], years[-1]

    def sx(year: float) -> float:
        return PAD_L + (year - x0) / (x1 - x0) * (W - PAD_L - PAD_R)

    def sy(share: float) -> float:
        span = (share - Y_MIN) / (Y_MAX - Y_MIN)
        return H - PAD_B - span * (H - PAD_T - PAD_B)

    def path(points: list[tuple[int, float]]) -> str:
        return " ".join(
            f"{'M' if i == 0 else 'L'}{sx(y):.1f} {sy(v):.1f}"
            for i, (y, v) in enumerate(points)
        )

    out: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
        f'width="{W}" height="{H}" font-family="-apple-system,BlinkMacSystemFont,'
        f'\'Segoe UI\',Helvetica,Arial,sans-serif" role="img" '
        f'aria-label="AI share of computer science works by publication year, '
        f'{x0} to {x1}">',
        f'<rect width="{W}" height="{H}" fill="{theme.surface}"/>',
    ]

    # Title block.
    out.append(
        f'<text x="{PAD_L}" y="32" fill="{theme.text_primary}" font-size="19" '
        f'font-weight="600">AI\'s share of computer science output</text>'
    )
    out.append(
        f'<text x="{PAD_L}" y="52" fill="{theme.text_secondary}" font-size="13">'
        f"Share of CS works classified as AI, by publication year</text>"
    )

    # Horizontal grid + y labels. Recessive: grid sits under the marks.
    tick = Y_MIN
    while tick <= Y_MAX + 1e-9:
        y = sy(tick)
        out.append(
            f'<line x1="{PAD_L}" y1="{y:.1f}" x2="{W - PAD_R}" y2="{y:.1f}" '
            f'stroke="{theme.grid}" stroke-width="1"/>'
        )
        out.append(
            f'<text x="{PAD_L - 10}" y="{y + 4:.1f}" fill="{theme.text_muted}" '
            f'font-size="12" text-anchor="end">{tick * 100:.0f}%</text>'
        )
        tick += 0.10

    # X axis line + decade ticks.
    base = sy(Y_MIN)
    out.append(
        f'<line x1="{PAD_L}" y1="{base:.1f}" x2="{W - PAD_R}" y2="{base:.1f}" '
        f'stroke="{theme.axis}" stroke-width="1"/>'
    )
    for year in range(1980, x1 + 1, 10):
        out.append(
            f'<text x="{sx(year):.1f}" y="{base + 22:.1f}" fill="{theme.text_muted}" '
            f'font-size="12" text-anchor="middle">{year}</text>'
        )

    # Series. Complete years solid; the partial year continues as a dashed
    # segment so it is never read as a settled data point.
    for points, color, label in (
        (broad, theme.broad, "AI broad"),
        (strict, theme.strict, "AI strict"),
    ):
        complete = [p for p in points if p[0] != partial_year]
        out.append(
            f'<path d="{path(complete)}" fill="none" stroke="{color}" '
            f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'
        )
        if partial_year and points[-1][0] == partial_year:
            tail = points[-2:]
            out.append(
                f'<path d="{path(tail)}" fill="none" stroke="{color}" '
                f'stroke-width="2" stroke-dasharray="3 4" stroke-linecap="round"/>'
            )
            py, pv = points[-1]
            out.append(
                f'<circle cx="{sx(py):.1f}" cy="{sy(pv):.1f}" r="4" '
                f'fill="{theme.surface}" stroke="{color}" stroke-width="2"/>'
            )

        # Direct label at the line end. Text wears an ink token; the swatch
        # carries identity.
        end_year, end_val = complete[-1]
        ly = sy(end_val)
        out.append(
            f'<line x1="{sx(end_year) + 8:.1f}" y1="{ly:.1f}" '
            f'x2="{sx(end_year) + 20:.1f}" y2="{ly:.1f}" stroke="{color}" '
            f'stroke-width="2" stroke-linecap="round"/>'
        )
        out.append(
            f'<text x="{sx(end_year) + 26:.1f}" y="{ly - 2:.1f}" '
            f'fill="{theme.text_primary}" font-size="13" font-weight="600">'
            f"{label}</text>"
        )
        out.append(
            f'<text x="{sx(end_year) + 26:.1f}" y="{ly + 14:.1f}" '
            f'fill="{theme.text_secondary}" font-size="12">'
            f"{end_val * 100:.0f}% in {end_year}</text>"
        )

    # Partial-year note, anchored under the hollow endpoint.
    if partial_year:
        out.append(
            f'<text x="{W - PAD_R:.1f}" y="{H - 14}" fill="{theme.text_muted}" '
            f'font-size="11" text-anchor="end">'
            f"Dashed: {partial_year} is a partial year</text>"
        )

    # Legend. Present because identity must never rest on color alone.
    lx = PAD_L
    for color, label in (
        (theme.strict, "AI strict (subfield 1702)"),
        (theme.broad, "AI broad (1702 + CV/PR 1707)"),
    ):
        out.append(
            f'<line x1="{lx}" y1="{H - 18}" x2="{lx + 16}" y2="{H - 18}" '
            f'stroke="{color}" stroke-width="2" stroke-linecap="round"/>'
        )
        out.append(
            f'<text x="{lx + 22}" y="{H - 14}" fill="{theme.text_secondary}" '
            f'font-size="12">{label}</text>'
        )
        lx += 24 + len(label) * 6.4

    out.append("</svg>")
    return "\n".join(out)


def main() -> None:
    strict, broad, partial_year = load()
    for theme in (LIGHT, DARK):
        path = ASSETS / f"q1-ai-share-{theme.name}.svg"
        path.write_text(render(theme, strict, broad, partial_year) + "\n")
        print(f"wrote {path.relative_to(Path.cwd())}")


if __name__ == "__main__":
    main()
