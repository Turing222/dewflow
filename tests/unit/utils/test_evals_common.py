"""Evals common loader unit tests.

职责：验证 evals.common.load_samples 的 JSONL 解析和校验行为；边界：使用 tmp_path 本地文件，不访问真实存储；副作用：无。
"""

from pathlib import Path
from subprocess import SubprocessError

import pytest

from evals.common import build_run_metadata, dataset_hash, git_commit, load_samples


def test_load_samples_supports_v1_fields_returns_samples(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text(
        (
            '{"id":"case-1","query":"hello","kb_id":null,'
            '"category":"fact","retrieval_mode":"hybrid",'
            '"expected_chunk_ids":["c1"],"expected_keywords":["kw"],'
            '"expected_plan":{"should_use_rag":true,"retrieval_mode":"hybrid"},'
            '"reference_answer":"ref","must_refuse":true,'
            '"notes":"note"}\n'
        ),
        encoding="utf-8",
    )

    samples = load_samples(dataset)

    assert len(samples) == 1
    sample = samples[0]
    assert sample.id == "case-1"
    assert sample.category == "fact"
    assert sample.retrieval_mode == "hybrid"
    assert sample.expected_chunk_ids == ["c1"]
    assert sample.expected_keywords == ["kw"]
    assert sample.expected_plan == {"should_use_rag": True, "retrieval_mode": "hybrid"}
    assert sample.reference_answer == "ref"
    assert sample.must_refuse is True
    assert sample.notes == "note"


def test_load_samples_raises_on_invalid_retrieval_mode(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text(
        '{"query":"hello","retrieval_mode":"bm25"}\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="retrieval_mode"):
        load_samples(dataset)


def test_load_samples_raises_on_invalid_expected_plan(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text(
        '{"query":"hello","expected_plan":["bad"]}\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="expected_plan"):
        load_samples(dataset)


@pytest.mark.parametrize(
    "payload",
    [
        '{"query":"hello","expected_plan":{"should_use_rag":"yes"}}\n',
        '{"query":"hello","expected_plan":{"use_rerank":1}}\n',
    ],
)
def test_load_samples_raises_on_non_bool_expected_plan_flags(
    tmp_path: Path,
    payload: str,
) -> None:
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text(payload, encoding="utf-8")

    with pytest.raises(ValueError, match="expected_plan"):
        load_samples(dataset)


def test_load_samples_raises_on_invalid_expected_plan_retrieval_mode(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text(
        '{"query":"hello","expected_plan":{"retrieval_mode":"bm25"}}\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="expected_plan.retrieval_mode"):
        load_samples(dataset)


def test_dataset_hash_is_stable_for_same_file(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text('{"query":"hello"}\n', encoding="utf-8")

    assert dataset_hash(dataset) == dataset_hash(dataset)


def test_build_run_metadata_includes_required_fields(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text('{"query":"hello"}\n', encoding="utf-8")

    metadata = build_run_metadata(
        kind="planner",
        dataset_path=dataset,
        config={"cli_args": {"output": "report.json"}},
    )

    assert metadata["kind"] == "planner"
    assert metadata["dataset_path"] == str(dataset)
    assert metadata["dataset_hash"] == dataset_hash(dataset)
    assert metadata["created_at"].endswith("Z")
    assert metadata["config"]["cli_args"]["output"] == "report.json"


def test_git_commit_returns_none_when_git_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_error(*args: object, **kwargs: object) -> None:
        raise SubprocessError("git failed")

    monkeypatch.setattr("evals.common.subprocess.run", raise_error)

    assert git_commit() is None
