"""High scores, kept per song and difficulty in a small JSON file."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

KEEP = 5


@dataclass(frozen=True)
class Entry:
    score: int
    best_streak: int
    cleared: bool
    date: str


def default_path() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
    return Path(base) / "pitch_dodge" / "scores.json"


class ScoreBoard:
    def __init__(self, path: Path | None = None):
        self.path = path or default_path()
        self._data: dict[str, list[dict]] = {}
        try:
            self._data = json.loads(self.path.read_text())
            if not isinstance(self._data, dict):
                self._data = {}
        except (OSError, ValueError):
            self._data = {}

    @staticmethod
    def key(song: str, difficulty: str) -> str:
        return f"{song}::{difficulty}"

    def top(self, song: str, difficulty: str) -> list[Entry]:
        rows = self._data.get(self.key(song, difficulty), [])
        out = []
        for r in rows:
            try:
                out.append(Entry(**r))
            except TypeError:
                continue
        return out

    def best(self, song: str, difficulty: str) -> int:
        top = self.top(song, difficulty)
        return top[0].score if top else 0

    def submit(self, song: str, difficulty: str, entry: Entry) -> int | None:
        """Record a run. Returns its 1-based rank if it made the table, else None."""
        rows = self.top(song, difficulty) + [entry]
        rows.sort(key=lambda e: e.score, reverse=True)
        rows = rows[:KEEP]
        rank = next((i + 1 for i, e in enumerate(rows) if e is entry), None)
        self._data[self.key(song, difficulty)] = [asdict(e) for e in rows]
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, indent=2))
            tmp.replace(self.path)
        except OSError:
            pass  # scores are nice-to-have
        return rank
