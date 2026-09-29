"""Refresh the fixed replays for the target algorithms with changed batch rules."""

from __future__ import annotations

import json
from datetime import datetime

from maps_demo.engine import run_demo
from maps_demo.presets import (
    PRESET_ROOT,
    PRESETS,
    _FrameWriter,
    _read_gzip,
    _write_gzip,
    preset_settings,
)
from scripts.verify_preset_experiments import verify

ALGORITHMS = {
    "rl-capa": "rl-capa-six-batch",
    "greedy": "greedy-fare-batch",
}
STATUS_PATH = PRESET_ROOT / "update_status.json"


def _status(**values) -> None:
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps({
        "updated_at": datetime.now().astimezone().isoformat(), **values,
    }, indent=2), encoding="utf-8")


def main() -> None:
    completed: list[str] = []
    try:
        for city in PRESETS:
            directory = PRESET_ROOT / city
            manifest_path = directory / "manifest.json.gz"
            manifest = _read_gzip(manifest_path)
            if manifest["settings"] != preset_settings(city):
                raise ValueError(f"{city} preset settings changed")
            shared = _read_gzip(directory / "shared.json.gz")
            for algorithm, folder in ALGORITHMS.items():
                previous = manifest["runs"].get(algorithm)
                if previous is not None and previous["files"][0].startswith(f"{folder}/"):
                    completed.append(f"{city}/{algorithm}")
                    continue
                reference = next(iter(manifest["runs"].values()))
                writer = _FrameWriter(directory, folder)
                last_percent = -1

                def progress(percent: float, label: str,
                             city_name: str = city, method: str = algorithm) -> None:
                    nonlocal last_percent
                    current = int(percent)
                    if current > last_percent:
                        _status(state="running", city=city_name, algorithm=method,
                                percent=current, label=label, completed=completed)
                        print(f"{city_name} · {method}: {current}% · {label}", flush=True)
                        last_percent = current

                progress(0, "Preparing scenario")
                run = run_demo({**manifest["settings"], "algorithm": algorithm},
                               progress=progress, batch_sink=writer.append)
                writer.flush()
                if run["catalog"] != shared["catalog"] or run["geography"] != shared["geography"]:
                    raise ValueError(f"{city}/{algorithm} changed the comparison scenario")
                if writer.frame_count != reference["frame_count"]:
                    raise ValueError(f"{city}/{algorithm} changed the batch count")
                initial = _read_gzip(directory / writer.files[0])[0]["before"]
                earlier = _read_gzip(directory / reference["files"][0])[0]["before"]
                if initial != earlier:
                    raise ValueError(f"{city}/{algorithm} changed the initial world")
                manifest["runs"][algorithm] = {
                    "meta": run["meta"], "batches": run["batches"],
                    "summary": run["summary"], "frame_count": writer.frame_count,
                    "files": writer.files,
                }
                manifest["runs"] = {
                    name: manifest["runs"][name]
                    for name in manifest["settings"]["algorithms"]
                    if name in manifest["runs"]
                }
                _write_gzip(manifest_path, manifest)
                completed.append(f"{city}/{algorithm}")
                _status(state="running", city=city, algorithm=algorithm,
                        percent=100, label="Saved", completed=completed)
                print(f"{city} · {algorithm}: saved {writer.frame_count} frames", flush=True)
        report = verify()
        _status(state="complete", completed=completed,
                verified_cities=list(report["cities"]))
        print("All affected presets verified", flush=True)
    except Exception as error:
        _status(state="failed", completed=completed, error=str(error))
        raise


if __name__ == "__main__":
    main()
