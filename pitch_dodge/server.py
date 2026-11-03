"""Serve the browser version of the game on localhost.

The browser can't run librosa, so the server does the audio analysis and hands
the game a small JSON description of each song (pitch curve, onsets, loudness)
plus the audio file itself. Everything else, drawing, input, playback and
rules, happens in the page (``pitch_dodge/web``).

Endpoints:

    GET  /                          the game
    GET  /api/songs                 songs in the bundled and library folders
    POST /api/songs                 upload a song (raw body, X-Filename header)
    GET  /api/songs/<file>/analysis pitch / energy / onsets as JSON
    GET  /api/songs/<file>/audio    the audio file
    GET  /api/scores?song=&difficulty=
    POST /api/scores                {song, difficulty, score, best_streak, cleared}
"""

from __future__ import annotations

import datetime as dt
import json
import mimetypes
import os
import re
import threading
from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .analysis import analyse_file
from .scores import Entry, ScoreBoard
from .world import DIFFICULTIES

PACKAGE_DIR = Path(__file__).resolve().parent
WEB_DIR = PACKAGE_DIR / "web"
BUNDLED_SONGS = PACKAGE_DIR / "assets" / "songs"
AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".flac"}
MAX_UPLOAD_BYTES = 200 * 1024 * 1024
STATIC_TYPES = {".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml"}


def default_library() -> Path:
    """The ``songs/`` folder that every song is loaded from and saved to.

    Normally ``songs/`` at the top of the project (next to ``play.sh``), so it's
    easy to find, add files to, and share. ``PITCH_DODGE_SONGS`` overrides it.
    If the package was installed somewhere without the project around it, it
    falls back to ``./songs`` in the current directory.
    """
    override = os.environ.get("PITCH_DODGE_SONGS")
    if override:
        return Path(override).expanduser()
    project = PACKAGE_DIR.parent
    if (project / "pyproject.toml").is_file():
        return project / "songs"
    return Path.cwd() / "songs"


def legacy_library() -> Path:
    """Where songs were saved before the project-level ``songs/`` folder existed."""
    base = os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
    return Path(base) / "pitch_dodge" / "songs"


def display_name(filename: str) -> str:
    """Same naming as the desktop game, so high scores are shared."""
    return Path(filename).stem.replace("_", " ")


def safe_filename(name: str) -> str | None:
    """Reduce an uploaded file name to something safe to store, or None if unusable."""
    name = Path(name.replace("\\", "/")).name
    stem, ext = os.path.splitext(name)
    ext = ext.lower()
    if ext not in AUDIO_EXTENSIONS:
        return None
    stem = re.sub(r"[^\w\- ]+", "", stem).strip().replace(" ", "_")[:80]
    return f"{stem or 'song'}{ext}"


class SongLibrary:
    """Songs from the bundled folder plus a writable library folder."""

    def __init__(self, library_dir: Path, extra_dirs: list[Path] | None = None):
        self.library_dir = library_dir
        self.dirs = [*(extra_dirs or []), library_dir, BUNDLED_SONGS]
        self._analysis_lock = threading.Lock()

    def songs(self) -> list[dict]:
        seen: dict[str, dict] = {}
        for d in self.dirs:
            if not d.is_dir():
                continue
            for p in sorted(d.iterdir()):
                if p.suffix.lower() in AUDIO_EXTENSIONS and p.is_file() and p.name not in seen:
                    seen[p.name] = {
                        "file": p.name,
                        "name": display_name(p.name),
                        "bundled": d == BUNDLED_SONGS,
                    }
        return sorted(seen.values(), key=lambda s: s["name"].lower())

    def find(self, filename: str) -> Path | None:
        if not filename or "/" in filename or "\\" in filename or filename.startswith("."):
            return None
        for d in self.dirs:
            p = d / filename
            if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS:
                return p
        return None

    def analysis(self, path: Path) -> dict:
        with self._analysis_lock:  # one at a time; the cache makes repeats instant
            song = analyse_file(path)
        return {
            "pitch": [round(float(v), 3) for v in song.pitch],
            "energy": [round(float(v), 3) for v in song.energy],
            "onsets": [round(float(v), 4) for v in song.onsets],
            "hop_seconds": song.hop_seconds,
            "duration": song.duration,
        }

    def add(self, filename: str, data: bytes) -> str:
        name = safe_filename(filename)
        if name is None:
            raise ValueError(f"Unsupported file type; use one of {', '.join(sorted(AUDIO_EXTENSIONS))}")
        self.library_dir.mkdir(parents=True, exist_ok=True)
        target = self.library_dir / name
        stem, ext = os.path.splitext(name)
        n = 2
        while target.exists():
            if target.read_bytes() == data:
                return target.name  # same song uploaded again
            target = self.library_dir / f"{stem}_{n}{ext}"
            n += 1
        target.write_bytes(data)
        return target.name


def make_handler(library: SongLibrary, scores: ScoreBoard):
    scores_lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        server_version = "PitchDodge"

        def log_message(self, fmt, *args):  # quieter than the default
            if os.environ.get("PITCH_DODGE_VERBOSE"):
                super().log_message(fmt, *args)

        # ---------------------------------------------------- responses

        def _send(self, status: int, body: bytes, content_type: str, cache: bool = False) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "max-age=3600" if cache else "no-store")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, data, status: int = 200) -> None:
            self._send(status, json.dumps(data).encode(), "application/json")

        def _error(self, status: int, message: str) -> None:
            self._json({"error": message}, status)

        def _body(self) -> bytes | None:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_UPLOAD_BYTES:
                self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "File too large")
                return None
            return self.rfile.read(length)

        # ---------------------------------------------------- routes

        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            url = urlparse(self.path)
            parts = [unquote(p) for p in url.path.split("/") if p]

            if not parts or parts == ["index.html"]:
                return self._static("index.html")
            if parts[0] != "api":
                return self._static("/".join(parts))
            if parts == ["api", "songs"]:
                return self._json({"songs": library.songs()})
            if len(parts) == 4 and parts[:2] == ["api", "songs"] and parts[3] in ("analysis", "audio"):
                path = library.find(parts[2])
                if path is None:
                    return self._error(HTTPStatus.NOT_FOUND, "No such song")
                if parts[3] == "audio":
                    ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                    return self._send(200, path.read_bytes(), ctype, cache=True)
                try:
                    return self._json(library.analysis(path))
                except Exception as exc:  # bad/corrupt audio
                    return self._error(HTTPStatus.UNPROCESSABLE_ENTITY, f"Couldn't analyse song: {exc}")
            if parts == ["api", "scores"]:
                q = parse_qs(url.query)
                song = q.get("song", [""])[0]
                diff = q.get("difficulty", ["normal"])[0]
                return self._json({"top": [asdict(e) for e in scores.top(song, diff)]})
            return self._error(HTTPStatus.NOT_FOUND, "Not found")

        def do_POST(self):
            path = urlparse(self.path).path.rstrip("/")
            if path == "/api/songs":
                filename = unquote(self.headers.get("X-Filename", ""))
                data = self._body()
                if data is None:
                    return
                if not data:
                    return self._error(HTTPStatus.BAD_REQUEST, "Empty upload")
                try:
                    name = library.add(filename, data)
                except ValueError as exc:
                    return self._error(HTTPStatus.BAD_REQUEST, str(exc))
                return self._json({"file": name, "name": display_name(name)}, HTTPStatus.CREATED)

            if path == "/api/scores":
                data = self._body()
                if data is None:
                    return
                try:
                    req = json.loads(data)
                    song = str(req["song"])[:200]
                    diff = str(req["difficulty"])
                    if diff not in DIFFICULTIES:
                        raise ValueError("bad difficulty")
                    entry = Entry(
                        score=max(0, int(req["score"])),
                        best_streak=max(0, int(req.get("best_streak", 0))),
                        cleared=bool(req.get("cleared", False)),
                        date=dt.date.today().isoformat(),
                    )
                except (ValueError, KeyError, TypeError):
                    return self._error(HTTPStatus.BAD_REQUEST, "Bad score")
                with scores_lock:
                    rank = scores.submit(song, diff, entry)
                    top = [asdict(e) for e in scores.top(song, diff)]
                return self._json({"rank": rank, "top": top})

            return self._error(HTTPStatus.NOT_FOUND, "Not found")

        def _static(self, rel: str):
            target = (WEB_DIR / rel).resolve()
            if WEB_DIR.resolve() not in target.parents or not target.is_file():
                return self._error(HTTPStatus.NOT_FOUND, "Not found")
            ctype = STATIC_TYPES.get(target.suffix, "application/octet-stream")
            self._send(200, target.read_bytes(), f"{ctype}; charset=utf-8")

    return Handler


def make_server(
    host: str = "127.0.0.1",
    port: int = 8000,
    library_dir: Path | None = None,
    extra_dirs: list[Path] | None = None,
    scores: ScoreBoard | None = None,
) -> ThreadingHTTPServer:
    library = SongLibrary(library_dir or default_library(), extra_dirs)
    server = ThreadingHTTPServer((host, port), make_handler(library, scores or ScoreBoard()))
    server.daemon_threads = True
    return server


def serve(
    host: str = "127.0.0.1",
    port: int = 8000,
    open_browser: bool = True,
    extra_dirs: list[Path] | None = None,
) -> None:
    try:
        server = make_server(host, port, extra_dirs=extra_dirs)
    except OSError as exc:
        msg = f"pitch-dodge: can't listen on {host}:{port} ({exc}). Try --port {port + 1}."
        raise SystemExit(msg) from exc
    shown_host = "localhost" if host in ("127.0.0.1", "0.0.0.0", "") else host
    url = f"http://{shown_host}:{server.server_address[1]}/"
    print(f"Pitch Dodge is running at {url}")
    print(f"Songs are loaded from {default_library()}")
    print("Add more by dropping files in there or dragging them onto the page.")
    old = legacy_library()
    if old.is_dir() and any(p.suffix.lower() in AUDIO_EXTENSIONS for p in old.iterdir()):
        print(f"Note: you have songs in the old folder {old}; move them with `pitch-dodge import-songs`.")
    print("Press Ctrl+C to stop.")
    if open_browser:
        import webbrowser

        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
