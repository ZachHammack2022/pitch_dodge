"""Kept so `python game.py [song]` still works. Prefer `python -m pitch_dodge`."""

from pitch_dodge.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
