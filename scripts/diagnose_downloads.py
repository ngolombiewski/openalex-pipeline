"""
Diagnostic functions for validating OpenAlex CLI download results.

All functions are pure and stateless — no side effects beyond logging.
Intended for interactive use from a notebook.
"""

import os
import re
import time
from collections import Counter
from itertools import combinations
from pathlib import Path

import requests
from loguru import logger


def _build_result(ids: list[str]) -> dict:
    counts = Counter(ids)
    duplicates = [id_ for id_, n in counts.items() if n > 1]
    return {"ids": list(counts.keys()), "count": len(counts), "duplicates": duplicates}


def collect_file_ids(data_dir: Path) -> dict:
    """
    Scan data_dir for files matching W*.json and extract work IDs from filenames.

    Returns:
        {"ids": list[str], "count": int, "duplicates": list[str]}
    """
    ids = [f.stem for f in Path(data_dir).glob("W*.json")]
    logger.debug(f"collect_file_ids: found {len(ids)} files in {data_dir}")
    return _build_result(ids)


def collect_checkpoint_ids(checkpoint_path: Path) -> dict:
    """
    Parse .openalex-checkpoint.json and extract completed_work_ids.

    Returns:
        {"ids": list[str], "count": int, "duplicates": list[str]}
    """
    import json

    data = json.loads(Path(checkpoint_path).read_text())
    ids = data.get("completed_work_ids", [])
    logger.debug(f"collect_checkpoint_ids: {len(ids)} IDs in {checkpoint_path}")
    return _build_result(ids)


def collect_failed_ids_from_log(log_path: Path) -> dict:
    """
    Parse openalex-download.log and extract work IDs from WARNING/ERROR lines.

    Returns:
        {"ids": list[str], "count": int, "duplicates": list[str]}
    """
    work_id_pattern = re.compile(r"W\d+")
    error_levels = {"WARNING", "ERROR"}
    ids = []

    for line in Path(log_path).read_text().splitlines():
        # Lines look like: "2026-04-17 21:45:09 - WARNING - Failed to fetch ..."
        parts = line.split(" - ", maxsplit=2)
        if len(parts) >= 2 and parts[1].strip() in error_levels:
            ids.extend(work_id_pattern.findall(line))

    logger.debug(f"collect_failed_ids_from_log: {len(ids)} IDs from {log_path}")
    return _build_result(ids)


def fetch_api_ids(
    filter_str: str,
    api_key: str = os.getenv("OPENALEX_API_KEY"),
    delay: float = 0.1,
) -> dict:
    """
    Fetch all work IDs from the OpenAlex API for the given filter using cursor pagination.

    Args:
        filter_str: OpenAlex filter string, e.g. "topics.id:T10320,publication_year:2012"
        api_key:    OpenAlex API key (defaults to OPENALEX_API_KEY env var)
        delay:      Seconds to sleep between pages to avoid 429s

    Returns:
        {"ids": list[str], "count": int, "declared_total": int, "duplicates": list[str]}
    """
    base_url = "https://api.openalex.org/works"
    cursor = "*"
    all_ids: list[str] = []
    declared_total: int = 0
    page = 0

    while True:
        params = {
            "filter": filter_str,
            "api_key": api_key,
            "cursor": cursor,
            "per_page": 200,
            "select": "id",
        }

        response = requests.get(base_url, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()

        if page == 0:
            declared_total = data["meta"]["count"]
            logger.info(f"fetch_api_ids: API declares {declared_total} total results")

        results = data.get("results", [])
        if not results:
            break

        page_ids = [r["id"].split("/")[-1] for r in results]
        all_ids.extend(page_ids)
        page += 1

        logger.info(f"fetch_api_ids: page {page} — fetched {len(page_ids)}, running total {len(all_ids)}")

        cursor = data["meta"].get("next_cursor")
        if not cursor:
            break

        time.sleep(delay)

    result = _build_result(all_ids)
    result["declared_total"] = declared_total
    return result


def compare_sources(*named_sources: tuple[str, dict]) -> dict:
    """
    Compare any number of (name, result_dict) pairs pairwise.

    For each pair (A, B) computes:
        - only_in_a: IDs in A not in B
        - only_in_b: IDs in B not in A
        - intersection_count: number of IDs in both

    Returns a dict keyed by (name_a, name_b) tuples.
    """
    comparisons = {}

    for (name_a, result_a), (name_b, result_b) in combinations(named_sources, 2):
        set_a = set(result_a["ids"])
        set_b = set(result_b["ids"])

        only_in_a = sorted(set_a - set_b)
        only_in_b = sorted(set_b - set_a)
        intersection = set_a & set_b

        logger.info(
            f"compare_sources: ({name_a} vs {name_b}) — "
            f"only_in_{name_a}={len(only_in_a)}, "
            f"only_in_{name_b}={len(only_in_b)}, "
            f"intersection={len(intersection)}"
        )

        comparisons[(name_a, name_b)] = {
            "only_in_a": only_in_a,
            "only_in_b": only_in_b,
            "intersection_count": len(intersection),
        }

    return comparisons
