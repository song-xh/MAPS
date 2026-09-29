"""Summarize completed preset algorithms for the scheduled progress check."""

from __future__ import annotations

import gzip
import json

from maps_demo.engine import POLICIES
from maps_demo.presets import PRESET_ROOT, PRESETS


def main() -> None:
    complete = True
    parts = []
    for city in PRESETS:
        path = PRESET_ROOT / city / "manifest.json.gz"
        if path.exists():
            with gzip.open(path, "rt", encoding="utf-8") as stream:
                saved = json.load(stream)["runs"]
                finished = [name for name in POLICIES if name in saved]
        else:
            finished = []
        active = next((name for name in POLICIES if name not in finished), None)
        saved_frames = (len(list((PRESET_ROOT / city / active).glob("frames-*.json.gz"))) * 10
                        if active else 216)
        parts.append(f"{city}: {len(finished)}/{len(POLICIES)} algorithms; "
                     f"{active or 'complete'} {min(saved_frames, 216)}/216 saved frames")
        complete &= set(finished) == set(POLICIES)
    print("; ".join(parts))
    raise SystemExit(0 if complete else 2)


if __name__ == "__main__":
    main()
