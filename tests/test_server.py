"""Exercise the localhost server over real HTTP."""

import json
import threading
import urllib.error
import urllib.request

import numpy as np
import pytest
import soundfile as sf

from pitch_dodge.scores import ScoreBoard
from pitch_dodge.server import make_server, safe_filename


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    srv = make_server(port=0, library_dir=tmp_path / "library", scores=ScoreBoard(tmp_path / "scores.json"))
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def get(url):
    with urllib.request.urlopen(url) as r:
        return r.status, r.headers.get("Content-Type"), r.read()


def post(url, body, headers=None):
    req = urllib.request.Request(url, data=body, headers=headers or {}, method="POST")
    with urllib.request.urlopen(req) as r:
        return r.status, json.loads(r.read())


def status_of(fn, *args):
    try:
        return fn(*args)[0]
    except urllib.error.HTTPError as e:
        return e.code


def wav_bytes(tmp_path):
    sr = 22050
    t = np.arange(sr * 2) / sr
    path = tmp_path / "upload.wav"
    sf.write(path, (0.4 * np.sin(2 * np.pi * 330 * t)).astype(np.float32), sr)
    return path.read_bytes()


def test_serves_the_game(server):
    status, ctype, body = get(server + "/")
    assert status == 200 and ctype.startswith("text/html")
    assert b"game.js" in body
    assert get(server + "/game.js")[1].startswith("text/javascript")
    assert get(server + "/style.css")[1].startswith("text/css")


def test_lists_bundled_song(server):
    songs = json.loads(get(server + "/api/songs")[2])["songs"]
    bundled = next(s for s in songs if s["file"] == "jungle_waves.mp3")
    assert bundled["name"] == "jungle waves" and bundled["bundled"] is True


def test_audio_endpoint(server):
    status, ctype, body = get(server + "/api/songs/jungle_waves.mp3/audio")
    assert status == 200 and ctype == "audio/mpeg" and len(body) > 100_000


def test_upload_then_analyse(server, tmp_path):
    data = wav_bytes(tmp_path)
    status, res = post(server + "/api/songs", data, {"X-Filename": "My%20Song!.wav"})
    assert status == 201 and res == {"file": "My_Song.wav", "name": "My Song"}
    # Same bytes again: no duplicate.
    assert post(server + "/api/songs", data, {"X-Filename": "My Song!.wav"})[1]["file"] == "My_Song.wav"

    songs = json.loads(get(server + "/api/songs")[2])["songs"]
    assert any(s["file"] == "My_Song.wav" and not s["bundled"] for s in songs)

    analysis = json.loads(get(server + "/api/songs/My_Song.wav/analysis")[2])
    assert analysis["duration"] == pytest.approx(2.0, abs=0.01)
    assert len(analysis["pitch"]) == len(analysis["energy"]) > 0
    assert all(0 <= v <= 1 for v in analysis["pitch"])


def test_rejects_bad_uploads(server):
    assert status_of(post, server + "/api/songs", b"hello", {"X-Filename": "notes.txt"}) == 400
    assert status_of(post, server + "/api/songs", b"", {"X-Filename": "a.mp3"}) == 400


def test_unanalysable_upload_reports_error(server):
    post(server + "/api/songs", b"not really audio", {"X-Filename": "junk.wav"})
    assert status_of(get, server + "/api/songs/junk.wav/analysis") == 422


@pytest.mark.parametrize(
    "path",
    ["/api/songs/nope.mp3/audio", "/api/songs/..%2Fserver.py/audio", "/%2e%2e/server.py", "/api/nothing"],
)
def test_not_found_and_no_traversal(server, path):
    assert status_of(get, server + path) == 404


def test_scores_roundtrip(server):
    url = server + "/api/scores"
    body = {"song": "jungle waves", "difficulty": "hard", "score": 500, "best_streak": 12, "cleared": True}
    status, res = post(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
    assert status == 200 and res["rank"] == 1
    top = json.loads(get(url + "?song=jungle%20waves&difficulty=hard")[2])["top"]
    assert top[0]["score"] == 500 and top[0]["cleared"] is True
    bad = dict(body, difficulty="impossible")
    assert status_of(post, url, json.dumps(bad).encode()) == 400


@pytest.mark.parametrize(
    "name,expected",
    [
        ("song.MP3", "song.mp3"),
        ("../../etc/evil.wav", "evil.wav"),
        ("C:\\Music\\a b.flac", "a_b.flac"),
        ("!!!.ogg", "song.ogg"),
        ("virus.exe", None),
        ("noext", None),
    ],
)
def test_safe_filename(name, expected):
    assert safe_filename(name) == expected


def test_status_and_background_analysis(tmp_path, monkeypatch):
    import time

    from pitch_dodge.server import SongLibrary

    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    lib = tmp_path / "library"
    lib.mkdir()
    (lib / "tone.wav").write_bytes(wav_bytes(tmp_path))
    srv = make_server(port=0, library_dir=lib, scores=ScoreBoard(tmp_path / "s.json"), background=True)
    library = srv.RequestHandlerClass.library
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        # The bundled song is long, so check our short one: queued/analysing, then ready.
        deadline = time.time() + 120
        seen = set()
        while time.time() < deadline:
            st = json.loads(get(base + "/api/songs/tone.wav/status")[2])
            seen.add(st["state"])
            if st["state"] == "ready":
                break
            time.sleep(0.05)
        assert st == {"state": "ready", "progress": 1.0}
        songs = json.loads(get(base + "/api/songs")[2])["songs"]
        assert next(s for s in songs if s["file"] == "tone.wav")["status"] == "ready"
        assert isinstance(library, SongLibrary)
        assert status_of(get, base + "/api/songs/nope.wav/status") == 404
    finally:
        srv.shutdown()
        srv.server_close()


def test_progress_is_reported_during_analysis(tmp_path, monkeypatch):
    from pitch_dodge.server import SongLibrary

    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    lib = tmp_path / "library"
    lib.mkdir()
    (lib / "tone.wav").write_bytes(wav_bytes(tmp_path))
    library = SongLibrary(lib)
    seen = []
    orig = library._set

    def spy(filename, **st):
        if "progress" in st:
            seen.append(st["progress"])
        orig(filename, **st)

    library._set = spy
    library.analyse(lib / "tone.wav")
    assert seen == sorted(seen) and seen[0] == 0.0 and seen[-1] == 1.0 and len(seen) > 4
    assert library.status("tone.wav")["state"] == "ready"
