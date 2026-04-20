#!/usr/bin/env python3
"""
Fetch the full topic hierarchy for a given OpenAlex field and save to docs/.

Usage:
    python scripts/fetch_topic_hierarchy.py "Computer Science"
    python scripts/fetch_topic_hierarchy.py 17
"""

import json
import os
import sys
from pathlib import Path

import requests

BASE_URL = "https://api.openalex.org"
DOCS_DIR = Path(__file__).parent.parent / "docs"


def fetch_all(session: requests.Session, endpoint: str, params: dict) -> list[dict]:
    """Fetch all pages for an endpoint, handling pagination transparently."""
    params = {**params, "per_page": 200, "page": 1}
    collected = []

    while True:
        response = session.get(f"{BASE_URL}/{endpoint}", params=params)
        response.raise_for_status()
        data = response.json()

        collected.extend(data["results"])

        if len(collected) >= data["meta"]["count"]:
            break

        params["page"] += 1

    return collected


def resolve_field(session: requests.Session, field_input: str) -> dict:
    """Resolve a field name or numeric ID to {id, display_name}."""
    # If numeric, fetch directly
    if field_input.isdigit():
        response = session.get(f"{BASE_URL}/fields/{field_input}")
        response.raise_for_status()
        data = response.json()
        return {"id": data["id"], "display_name": data["display_name"]}

    # Otherwise search by name
    response = session.get(
        f"{BASE_URL}/fields", params={"search": field_input, "per_page": 5}
    )
    response.raise_for_status()
    results = response.json()["results"]

    if not results:
        raise ValueError(f"No field found for: {field_input!r}")

    # Prefer exact match, fall back to first result
    for r in results:
        if r["display_name"].lower() == field_input.lower():
            return {"id": r["id"], "display_name": r["display_name"]}

    return {"id": results[0]["id"], "display_name": results[0]["display_name"]}


def build_hierarchy(field: dict, topics: list[dict]) -> dict:
    """Assemble the field/subfield/topic hierarchy from a flat topic list."""
    subfields: dict[str, dict] = {}

    for topic in topics:
        sf = topic["subfield"]
        sf_id = sf["id"]

        if sf_id not in subfields:
            subfields[sf_id] = {
                "id": sf_id,
                "display_name": sf["display_name"],
                "topics": [],
            }

        subfields[sf_id]["topics"].append(
            {
                "id": topic["id"],
                "display_name": topic["display_name"],
                "description": topic.get("description"),
            }
        )

    return {
        "field": field,
        "subfields": list(subfields.values()),
    }


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python fetch_topic_hierarchy.py <field_name_or_id>")
        sys.exit(1)

    field_input = sys.argv[1]
    api_key = os.getenv("OPENALEX_API_KEY")

    session_params = {"api-key": api_key} if api_key else {}

    with requests.Session() as session:
        # Attach API key to every request via params
        session.params = session_params  # type: ignore[assignment]

        print(f"Resolving field: {field_input!r}")
        field = resolve_field(session, field_input)
        print(f"  → {field['display_name']} ({field['id']})")

        # Extract numeric ID for filter (OpenAlex IDs are URLs like .../fields/17)
        field_numeric_id = field["id"].split("/")[-1]

        print("Fetching topics...")
        topics = fetch_all(
            session, "topics", {"filter": f"field.id:{field_numeric_id}"}
        )
        print(f"  → {len(topics)} topics fetched")

        hierarchy = build_hierarchy(field, topics)

        subfield_count = len(hierarchy["subfields"])
        print(f"  → {subfield_count} subfields assembled")

        DOCS_DIR.mkdir(exist_ok=True)
        slug = field["display_name"].lower().replace(" ", "-")
        output_path = DOCS_DIR / f"{slug}-topic-hierarchy.json"

        with open(output_path, "w") as f:
            json.dump(hierarchy, f, indent=2)

        print(f"Saved → {output_path}")


if __name__ == "__main__":
    main()
