"""Recompute only Chengdu RL-CAPA against the saved comparison workload."""

from __future__ import annotations

import json

from maps_demo.engine import run_demo
from maps_demo.presets import (
    PRESET_ROOT,
    _FrameWriter,
    _read_gzip,
    _write_gzip,
    preset_settings,
)
from scripts.verify_preset_experiments import verify


def _metrics(run: dict) -> dict:
    summary = run["summary"]
    return {key: summary[key] for key in (
        "profit", "assignment_rate", "assigned", "local_count", "cross_count", "bpt_s",
    )}


def main() -> None:
    directory = PRESET_ROOT / "chengdu"
    manifest_path = directory / "manifest.json.gz"
    manifest = _read_gzip(manifest_path)
    if manifest["settings"] != preset_settings("chengdu"):
        raise ValueError("Chengdu preset settings changed")
    previous = manifest["runs"]["rl-capa"]
    if previous["files"][0].startswith("rl-capa-recomputed/"):
        raise ValueError("Chengdu RL-CAPA has already been recomputed")

    writer = _FrameWriter(directory, "rl-capa-recomputed")
    last_percent = -1

    def progress(percent: float, label: str) -> None:
        nonlocal last_percent
        current = int(percent)
        if current > last_percent:
            print(f"Chengdu RL-CAPA: {current}% · {label}", flush=True)
            last_percent = current

    run = run_demo({**manifest["settings"], "algorithm": "rl-capa"},
                   progress=progress, batch_sink=writer.append)
    writer.flush()
    shared = _read_gzip(directory / "shared.json.gz")
    assert run["catalog"] == shared["catalog"]
    assert run["geography"] == shared["geography"]
    assert writer.frame_count == previous["frame_count"]
    assert (_read_gzip(directory / writer.files[0])[0]["before"]
            == _read_gzip(directory / previous["files"][0])[0]["before"])

    manifest["runs"]["rl-capa"] = {
        "meta": run["meta"], "batches": run["batches"], "summary": run["summary"],
        "frame_count": writer.frame_count, "files": writer.files,
    }
    _write_gzip(manifest_path, manifest)
    (PRESET_ROOT / "verification.json").unlink(missing_ok=True)
    verify()
    comparison = {"previous": _metrics(previous), "recomputed": _metrics(run)}
    (directory / "rl-capa-comparison.json").write_text(
        json.dumps(comparison, indent=2), encoding="utf-8")
    print(json.dumps(comparison, indent=2), flush=True)


if __name__ == "__main__":
    main()
