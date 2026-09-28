"""Fixed, precomputed real-city comparison replays for the system demo."""

from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path
from typing import Any

from maps_demo.engine import (
    POLICIES,
    STAGES,
    available_orders,
    run_demo,
    steps_from_frame,
)
from mpcs.config import DatasetSplit
from mpcs.experiments.Presets import dataset_preset

PRESET_ROOT = Path(__file__).resolve().parent.parent / "output" / "presets"
PRESETS = {
    "chengdu": {"label": "Chengdu · 08:00–09:00", "vehicles": 300,
                "start": "08:00", "end": "09:00"},
    "shanghai": {"label": "Shanghai · 09:00–10:00", "vehicles": 100,
                 "start": "09:00", "end": "10:00"},
}
CHUNK_FRAMES = 10


def preset_settings(name: str) -> dict[str, Any]:
    spec = PRESETS[name]
    base = dataset_preset(name, output_root=Path("output/maps-demo"))
    return {
        "dataset": name, "platforms": 4, "seed": 11,
        "primary_platform": "P1", "split": "test",
        "window_start": spec["start"], "window_end": spec["end"],
        "sources": {platform: base.dataset.source_files_for_platform(platform, DatasetSplit.TEST)[0]
                    for platform in base.platform_ids},
        "pickups_per_platform": "all", "dropoffs_per_platform": "all",
        "vehicles_per_platform": spec["vehicles"], "step_size_s": 20,
        "service_radius_km": 10.0, "deadline_s": 720,
        "sharing_rate": 0.3, "mode": "comparison", "algorithms": list(POLICIES),
        "preset": name,
    }


def _write_gzip(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    with gzip.open(temporary, "wt", encoding="utf-8", compresslevel=3) as stream:
        json.dump(value, stream, ensure_ascii=False, separators=(",", ":"))
    temporary.replace(path)


def _read_gzip(path: Path) -> Any:
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return json.load(stream)


class _FrameWriter:
    def __init__(self, root: Path, algorithm: str):
        self.root = root
        self.algorithm = algorithm
        self.buffer: list[dict[str, Any]] = []
        self.files: list[str] = []
        self.frame_count = 0

    def append(self, frame: dict[str, Any]) -> None:
        self.buffer.append(frame)
        self.frame_count += 1
        if len(self.buffer) == CHUNK_FRAMES:
            self.flush()

    def flush(self) -> None:
        if not self.buffer:
            return
        filename = f"{self.algorithm}/frames-{len(self.files):04d}.json.gz"
        _write_gzip(self.root / filename, self.buffer)
        self.files.append(filename)
        self.buffer = []


class PresetSteps:
    """Read one batch chunk at a time while preserving the normal step interface."""

    def __init__(self, root: Path, files: list[str], frame_count: int):
        self.root = root
        self.files = files
        self.frame_count = frame_count
        self._cached_chunk = -1
        self._frames: list[dict[str, Any]] = []

    def __len__(self) -> int:
        return self.frame_count * len(STAGES)

    def __getitem__(self, index: int) -> dict[str, Any]:
        if index < 0:
            index += len(self)
        if not 0 <= index < len(self):
            raise IndexError(index)
        frame_index, stage_index = divmod(index, len(STAGES))
        chunk_index, within_chunk = divmod(frame_index, CHUNK_FRAMES)
        if chunk_index != self._cached_chunk:
            self._frames = _read_gzip(self.root / self.files[chunk_index])
            self._cached_chunk = chunk_index
        return steps_from_frame(self._frames[within_chunk])[stage_index]

    def __iter__(self):
        for index in range(len(self)):
            yield self[index]


def generate_preset(name: str, root: Path = PRESET_ROOT) -> Path:
    settings = preset_settings(name)
    directory = root / name
    manifest_path = directory / "manifest.json.gz"
    if manifest_path.exists():
        manifest = _read_gzip(manifest_path)
        if manifest["settings"] != settings:
            raise ValueError(f"Existing {name} preset uses different settings")
    else:
        manifest = {"settings": settings, "counts": available_orders(settings), "runs": {}}
    for algorithm in POLICIES:
        if algorithm in manifest["runs"]:
            print(f"{name} · {algorithm}: already computed", flush=True)
            continue
        writer = _FrameWriter(directory, algorithm)
        print(f"{name} · {algorithm}: starting", flush=True)
        last_percent = -1

        def progress(percent: float, label: str, method: str = algorithm) -> None:
            nonlocal last_percent
            displayed = int(percent)
            if displayed > last_percent:
                print(f"{name} · {method}: {displayed}% · {label}", flush=True)
                last_percent = displayed

        run = run_demo({**settings, "algorithm": algorithm}, progress=progress,
                       batch_sink=writer.append)
        writer.flush()
        if not (directory / "shared.json.gz").exists():
            _write_gzip(directory / "shared.json.gz", {
                "catalog": run["catalog"], "geography": run["geography"],
            })
        manifest["runs"][algorithm] = {
            "meta": run["meta"], "batches": run["batches"],
            "summary": run["summary"], "frame_count": writer.frame_count,
            "files": writer.files,
        }
        _write_gzip(manifest_path, manifest)
        print(f"{name} · {algorithm}: saved {writer.frame_count} frames", flush=True)
    return manifest_path


def load_preset(name: str, root: Path = PRESET_ROOT) -> dict[str, Any]:
    directory = root / name
    manifest = _read_gzip(directory / "manifest.json.gz")
    if set(manifest["runs"]) != set(POLICIES):
        raise ValueError(f"{name} preset is still being computed")
    shared = _read_gzip(directory / "shared.json.gz")
    return {
        "settings": manifest["settings"], "counts": manifest["counts"],
        "catalog": shared["catalog"], "geography": shared["geography"],
        "runs": {algorithm: {
            **{key: value for key, value in run.items() if key not in {"files", "frame_count"}},
            "meta": {**run["meta"], "source": "replay"},
            "steps": PresetSteps(directory, run["files"], run["frame_count"]),
        } for algorithm, run in manifest["runs"].items()},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate fixed MAPS comparison presets")
    parser.add_argument("preset", choices=[*PRESETS, "all"])
    args = parser.parse_args()
    for name in PRESETS if args.preset == "all" else (args.preset,):
        generate_preset(name)


if __name__ == "__main__":
    main()
