from __future__ import annotations

from pathlib import Path

from openalex_pipeline.orchestration.config import load_config


def test_load_config_derives_local_paths_from_data_root(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    data_root = tmp_path / "data"
    monkeypatch.setenv("OPENALEX_API_KEY", "k")
    monkeypatch.setenv("OPENALEX_FILTER", "primary_topic.field.id:17")
    monkeypatch.setenv("OPENALEX_START_YEAR", "1980")
    monkeypatch.setenv("OPENALEX_END_YEAR", "1982")
    monkeypatch.setenv("OPENALEX_DATA_ROOT", str(data_root))
    monkeypatch.setenv("OPENALEX_DATA_DIR", str(tmp_path / "wrong-extract"))
    monkeypatch.setenv("OPENALEX_GCS_BUCKET", "bucket")
    monkeypatch.setenv("OPENALEX_GCP_PROJECT", "project")

    config = load_config()

    assert config.data_root == data_root
    assert config.extract_root == data_root / "extract"
    assert config.bronze_root == data_root / "bronze"
    assert config.settings.data_root == data_root
    assert config.settings.data_dir == data_root / "extract"
    assert config.years == [1980, 1981, 1982]
