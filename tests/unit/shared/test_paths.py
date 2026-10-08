"""Deep artifact paths must round-trip without changing persisted identities."""

import shutil
from pathlib import Path

from benchmarks.picobench.artifacts import ArtifactStore
from benchmarks.picobench.schema import ExperimentRef
from pico.shared.paths import native_path


def test_deep_artifact_round_trip(tmp_path: Path):
    nested = tmp_path / "nested"
    path = nested.joinpath(*["segment-" + "x" * 56 for _ in range(4)], "record.json")
    store = ArtifactStore(ExperimentRef("path-regression", tmp_path))
    record = {"plan_digest": "fixture", "message": "路径完整"}
    try:
        store.append_immutable(path, record)
        store.append_immutable(path, record)
        assert store.read_if_valid(path, plan_digest="fixture") == record
        store.write_summary(path, {**record, "updated": True})
        assert store.read_json(path)["updated"] is True
    finally:
        shutil.rmtree(native_path(nested, force=True))
