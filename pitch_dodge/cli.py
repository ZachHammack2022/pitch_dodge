"""Command-line entry point.

pitch-dodge serve [--port 8000]       play in your browser on localhost
pitch-dodge [song] [--difficulty ...]  play in a desktop window
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__
from .world import DIFFICULTIES

DEFAULT_SONG = Path(__file__).resolve().parent / "assets" / "songs" / "jungle_waves.mp3"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="pitch-dodge",
        description="Dodge projectiles fired by the melody of any song. "
        "Run `pitch-dodge serve` to play in your browser instead.",
    )
    parser.add_argument(
        "song",
        nargs="?",
        default=str(DEFAULT_SONG),
        help="audio file to play (wav, mp3, ogg, flac...); defaults to the bundled track",
    )
    parser.add_argument(
        "-d", "--difficulty", choices=list(DIFFICULTIES), default="normal", help="starting difficulty"
    )
    parser.add_argument("--mute", action="store_true", help="play without sound")
    parser.add_argument("--seed", type=int, help="random seed, for repeatable runs")
    parser.add_argument("--no-cache", action="store_true", help="re-analyse the song even if cached")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser.parse_args(argv)


def parse_serve_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="pitch-dodge serve",
        description="Serve the browser version of Pitch Dodge on localhost.",
    )
    parser.add_argument("-p", "--port", type=int, default=8000, help="port to listen on (default 8000)")
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="address to bind; use 0.0.0.0 to let other devices on your network play",
    )
    parser.add_argument("--no-browser", action="store_true", help="don't open a browser tab")
    parser.add_argument(
        "--songs", action="append", type=Path, default=[], metavar="DIR", help="extra folder of songs"
    )
    parser.add_argument("--no-cache", action="store_true", help="re-analyse songs even if cached")
    return parser.parse_args(argv)


def serve_main(argv: list[str]) -> int:
    args = parse_serve_args(argv)
    if args.no_cache:
        os.environ["PITCH_DODGE_NO_CACHE"] = "1"
    from .server import serve

    serve(args.host, args.port, open_browser=not args.no_browser, extra_dirs=args.songs)
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "serve":
        return serve_main(argv[1:])
    if argv and argv[0] == "fetch":
        from .fetch import main as fetch_main

        return fetch_main(argv[1:])
    args = parse_args(argv)
    if not Path(args.song).is_file():
        print(f"pitch-dodge: file not found: {args.song}", file=sys.stderr)
        return 1
    if args.no_cache:
        os.environ["PITCH_DODGE_NO_CACHE"] = "1"
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

    from .app import App  # imported late so --help is instant

    try:
        App(args.song, difficulty=args.difficulty, mute=args.mute, seed=args.seed).run()
    except KeyboardInterrupt:
        pass
    except ValueError as exc:  # e.g. a song too short to play
        print(f"pitch-dodge: {exc}", file=sys.stderr)
        return 1
    return 0
