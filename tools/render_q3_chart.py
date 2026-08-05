"""Render the Q3 citation reach/concentration scatter plot as standalone SVG.

Reads the committed 2020-cohort, citation-age-5 gold extract at
assets/q3_citation_concentration_2020_age5.csv and writes light and dark variants
next to it. README pairs them in a <picture> element so the chart follows the
reader's theme.

The input contract is one row for each of the 11 classified CS subfields, all
at publication_year=2020 and citation_age=5. ``zero_share`` is the x coordinate
and ``gini_cited_only`` is the y coordinate. The renderer rejects any other
slice rather than silently producing a differently scoped figure.

Deliberately stdlib-only: one static chart does not justify a plotting
dependency, and hand-emitted SVG keeps the output diffable and crisp.

    uv run python tools/render_q3_chart.py
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from html import escape
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "assets"
DATA = ASSETS / "q3_citation_concentration_2020_age5.csv"

EXPECTED_IDS = {str(subfield_id) for subfield_id in range(1702, 1713)}
EXPECTED_COLUMNS = {
    "publication_year",
    "citation_age",
    "subfield_id",
    "subfield_display_name",
    "zero_share",
    "gini",
    "gini_cited_only",
}

W, H = 960, 560
PAD_L, PAD_R, PAD_T, PAD_B = 78, 42, 82, 78
X_MIN, X_MAX = 0.32, 0.70
Y_MIN, Y_MAX = 0.62, 0.78


@dataclass(frozen=True)
class Theme:
    name: str
    surface: str
    text_primary: str
    text_secondary: str
    text_muted: str
    grid: str
    axis: str
    neutral: str
    ai: str
    cv: str
    contrast: str


LIGHT = Theme(
    name="light",
    surface="#fcfcfb",
    text_primary="#0b0b0b",
    text_secondary="#52514e",
    text_muted="#6f6e6a",
    grid="#e6e5e1",
    axis="#c8c7c2",
    neutral="#8b8a86",
    ai="#2a78d6",
    cv="#e45e2b",
    contrast="#7259b5",
)

DARK = Theme(
    name="dark",
    surface="#1a1a19",
    text_primary="#ffffff",
    text_secondary="#c3c2b7",
    text_muted="#96958c",
    grid="#2e2e2c",
    axis="#44443f",
    neutral="#85847d",
    ai="#4b96ed",
    cv="#ef7545",
    contrast="#a58cdd",
)


@dataclass(frozen=True)
class Point:
    publication_year: int
    citation_age: int
    subfield_id: str
    name: str
    zero_share: float
    gini: float
    gini_cited_only: float


def load() -> list[Point]:
    """Load and validate the pinned 2020-cohort, five-year subfield slice."""
    with DATA.open(newline="") as fh:
        reader = csv.DictReader(fh)
        if set(reader.fieldnames or ()) != EXPECTED_COLUMNS:
            raise ValueError(f"unexpected columns in {DATA}")
        points = [
            Point(
                publication_year=int(row["publication_year"]),
                citation_age=int(row["citation_age"]),
                subfield_id=row["subfield_id"],
                name=row["subfield_display_name"],
                zero_share=float(row["zero_share"]),
                gini=float(row["gini"]),
                gini_cited_only=float(row["gini_cited_only"]),
            )
            for row in reader
        ]

    if len(points) != 11 or {point.subfield_id for point in points} != EXPECTED_IDS:
        raise ValueError(f"expected exactly the 11 classified CS subfields in {DATA}")
    if {point.publication_year for point in points} != {2020}:
        raise ValueError(f"expected only publication_year=2020 in {DATA}")
    if {point.citation_age for point in points} != {5}:
        raise ValueError(f"expected only citation_age=5 in {DATA}")
    return points


LABELS = {
    "1702": ("Artificial Intelligence", 10, -13, "start", True),
    "1703": ("Theory & mathematics", 10, -12, "start", False),
    "1704": ("Computer Graphics", -10, -13, "end", True),
    "1705": ("Networks", 10, 19, "start", False),
    "1706": ("CS applications", -10, 20, "end", False),
    "1707": ("Computer Vision / PR", 10, -13, "start", True),
    "1708": ("Hardware", 10, 20, "start", False),
    "1709": ("Human-computer interaction", 10, 20, "start", False),
    "1710": ("Information Systems", 10, -13, "start", True),
    "1711": ("Signal processing", -10, -13, "end", False),
    "1712": ("Software", -10, 20, "end", False),
}


def render(theme: Theme, points: list[Point]) -> str:
    """Return a standalone, accessible SVG for a validated Q3 slice."""

    def sx(value: float) -> float:
        return PAD_L + (value - X_MIN) / (X_MAX - X_MIN) * (W - PAD_L - PAD_R)

    def sy(value: float) -> float:
        span = (value - Y_MIN) / (Y_MAX - Y_MIN)
        return H - PAD_B - span * (H - PAD_T - PAD_B)

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
        f'width="{W}" height="{H}" font-family="-apple-system,BlinkMacSystemFont,'
        f'\'Segoe UI\',Helvetica,Arial,sans-serif" role="img" '
        'aria-labelledby="title desc">',
        '<title id="title">Citation reach and inequality across 2020 computer science subfields</title>',
        '<desc id="desc">Scatter plot of the share of papers uncited after five complete years against citation inequality among cited papers. Artificial Intelligence and Computer Vision combine low uncited shares with high cited-only Gini coefficients.</desc>',
        f'<rect width="{W}" height="{H}" fill="{theme.surface}"/>',
        f'<text x="{PAD_L}" y="31" fill="{theme.text_primary}" font-size="19" '
        'font-weight="600">Citation reach and inequality move independently</text>',
        f'<text x="{PAD_L}" y="53" fill="{theme.text_secondary}" font-size="13">'
        "2020 computer science subfields · citations received in years 1–5 after publication</text>",
    ]

    for tick in (0.64, 0.68, 0.72, 0.76):
        y = sy(tick)
        out.append(
            f'<line x1="{PAD_L}" y1="{y:.1f}" x2="{W - PAD_R}" y2="{y:.1f}" '
            f'stroke="{theme.grid}" stroke-width="1"/>'
        )
        out.append(
            f'<text x="{PAD_L - 11}" y="{y + 4:.1f}" fill="{theme.text_muted}" '
            f'font-size="12" text-anchor="end">{tick:.2f}</text>'
        )

    base = H - PAD_B
    out.append(
        f'<line x1="{PAD_L}" y1="{base}" x2="{W - PAD_R}" y2="{base}" '
        f'stroke="{theme.axis}" stroke-width="1"/>'
    )
    for tick in (0.35, 0.45, 0.55, 0.65):
        x = sx(tick)
        out.append(
            f'<text x="{x:.1f}" y="{base + 22}" fill="{theme.text_muted}" '
            f'font-size="12" text-anchor="middle">{tick:.0%}</text>'
        )

    out.extend(
        [
            f'<text x="{(PAD_L + W - PAD_R) / 2:.1f}" y="{H - 28}" '
            f'fill="{theme.text_secondary}" font-size="13" text-anchor="middle">'
            "Share uncited after five years</text>",
            f'<text x="{PAD_L}" y="{H - 9}" fill="{theme.text_muted}" '
            'font-size="12">← more papers reached</text>',
            f'<text x="20" y="{(PAD_T + base) / 2:.1f}" fill="{theme.text_secondary}" '
            'font-size="13" text-anchor="middle" '
            f'transform="rotate(-90 20 {(PAD_T + base) / 2:.1f})">'
            "Cited-only Gini · winnings more concentrated ↑</text>",
        ]
    )

    for point in sorted(points, key=lambda item: item.subfield_id):
        label, dx, dy, anchor, show_value = LABELS[point.subfield_id]
        if point.subfield_id == "1702":
            color, radius = theme.ai, 6
        elif point.subfield_id == "1707":
            color, radius = theme.cv, 6
        elif point.subfield_id in {"1704", "1710"}:
            color, radius = theme.contrast, 5
        else:
            color, radius = theme.neutral, 4
        x, y = sx(point.zero_share), sy(point.gini_cited_only)
        out.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius}" fill="{color}" '
            f'stroke="{theme.surface}" stroke-width="2"/>'
        )
        weight = "600" if point.subfield_id in {"1702", "1707"} else "500"
        out.append(
            f'<text x="{x + dx:.1f}" y="{y + dy:.1f}" fill="{theme.text_primary}" '
            f'font-size="12" font-weight="{weight}" text-anchor="{anchor}">'
            f"{escape(label)}</text>"
        )
        if show_value:
            second_dy = dy + (15 if dy < 0 else -15)
            out.append(
                f'<text x="{x + dx:.1f}" y="{y + second_dy:.1f}" '
                f'fill="{theme.text_muted}" font-size="11" text-anchor="{anchor}">'
                f"{point.zero_share:.0%} uncited · {point.gini_cited_only:.3f} Gini</text>"
            )

    out.append("</svg>")
    return "\n".join(out)


def main() -> None:
    points = load()
    for theme in (LIGHT, DARK):
        path = ASSETS / f"q3-citation-concentration-{theme.name}.svg"
        path.write_text(render(theme, points) + "\n")
        print(f"wrote {path.relative_to(Path.cwd())}")


if __name__ == "__main__":
    main()
