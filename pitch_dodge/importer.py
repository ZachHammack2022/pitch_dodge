"""Move or copy audio files into the project's ``songs/`` folder.

pitch-dodge import-songs                 # move songs from the old ~/.local/share folder
pitch-dodge import-songs ~/Downloads/x   # copy songs from any folder (or files)
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from .server import AUDIO_EXTENSIONS, default_library, legacy_library, safe_filename

CREDITS = "CREDITS.md"


def _same_file(a: Path, b: Path) -> bool:
    return a.stat().st_size == b.stat().st_size and a.read_bytes() == b.read_bytes()


def _merge_credits(src: Path, dest: Path) -> None:
    """Append credit lines from ``src`` that ``dest`` doesn't already have."""
    if not src.is_file():
        return
    new_lines = [line for line in src.read_text(encoding="utf-8").splitlines() if line.startswith("- ")]
    existing = dest.read_text(encoding="utf-8") if dest.exists() else ""
    missing = [line for line in new_lines if line not in existing]
    if not missing:
        return
    with open(dest, "a", encoding="utf-8") as f:
        if not existing:
            f.write("# Song credits\n\n")
        f.write("\n".join(missing) + "\n")


def import_songs(
    sources: list[Path], dest: Path | None = None, move: bool = False, log=print
) -> tuple[int, int]:
    """Bring audio files into ``dest``. Returns (imported, skipped)."""
    dest = dest or default_library()
    dest.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []
    credit_files: list[Path] = []
    for src in sources:
        src = src.expanduser()
        if src.is_dir():
            files += sorted(p for p in src.iterdir() if p.suffix.lower() in AUDIO_EXTENSIONS and p.is_file())
            credit_files.append(src / CREDITS)
        elif src.is_file():
            files.append(src)
        else:
            log(f"  ! not found: {src}")

    imported = skipped = 0
    for f in files:
        name = safe_filename(f.name)
        if name is None:
            log(f"  ! skipping {f.name} (not mp3/wav/ogg/flac)")
            skipped += 1
            continue
        target = dest / name
        if target.resolve() == f.resolve():
            skipped += 1
            continue
        duplicate = next(
            (p for p in dest.iterdir() if p.suffix.lower() in AUDIO_EXTENSIONS and _same_file(f, p)), None
        )
        if duplicate is not None:
            if move:
                f.unlink()
            log(f"  = already have {f.name} (as {duplicate.name})")
            skipped += 1
            continue
        if target.exists():
            stem, ext = target.stem, target.suffix
            n = 2
            while target.exists():
                target = dest / f"{stem}_{n}{ext}"
                n += 1
        if move:
            shutil.move(str(f), target)
        else:
            shutil.copy2(f, target)
        log(f"  {'moved' if move else 'copied'} {f.name} -> {target.name}")
        imported += 1

    for c in credit_files:
        _merge_credits(c, dest / CREDITS)
        if move and c.is_file() and not any(p.suffix.lower() in AUDIO_EXTENSIONS for p in c.parent.iterdir()):
            c.unlink()  # nothing left for it to describe
    return imported, skipped


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(
        prog="pitch-dodge import-songs",
        description="Put audio files into the project's songs/ folder so the game loads them.",
    )
    p.add_argument(
        "sources",
        nargs="*",
        type=Path,
        help="folders or files to import (default: the old ~/.local/share/pitch_dodge/songs folder)",
    )
    group = p.add_mutually_exclusive_group()
    group.add_argument("--move", action="store_true", help="move instead of copy")
    group.add_argument("--copy", action="store_true", help="copy instead of move")
    a = p.parse_args(argv)

    if a.sources:
        sources, move = a.sources, a.move  # other folders: copy unless told to move
    else:
        sources, move = [legacy_library()], not a.copy  # old library: move unless told to copy
        if not sources[0].is_dir():
            print(f"Nothing to import: {sources[0]} doesn't exist.")
            return 0

    dest = default_library()
    imported, skipped = import_songs(sources, dest, move=move)
    print(f"\n{imported} song(s) added to {dest}" + (f" ({skipped} skipped)" if skipped else ""))
    print("Refresh the game page to see them.")
    return 0
