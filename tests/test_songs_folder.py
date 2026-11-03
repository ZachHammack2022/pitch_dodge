from pathlib import Path

from pitch_dodge import server
from pitch_dodge.importer import import_songs


def test_default_library_is_project_songs_folder(monkeypatch):
    monkeypatch.delenv("PITCH_DODGE_SONGS", raising=False)
    project = Path(server.__file__).resolve().parent.parent
    assert server.default_library() == project / "songs"


def test_default_library_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("PITCH_DODGE_SONGS", str(tmp_path / "mine"))
    assert server.default_library() == tmp_path / "mine"


def test_songs_folder_is_listed(monkeypatch, tmp_path):
    lib = tmp_path / "songs"
    lib.mkdir()
    (lib / "my_tune.mp3").write_bytes(b"x")
    (lib / "CREDITS.md").write_text("credits")
    names = [s["file"] for s in server.SongLibrary(lib).songs()]
    assert "my_tune.mp3" in names and "jungle_waves.mp3" in names and "CREDITS.md" not in names


def test_import_moves_files_and_credits(tmp_path):
    old = tmp_path / "old"
    old.mkdir()
    (old / "a.mp3").write_bytes(b"aaa")
    (old / "b c.ogg").write_bytes(b"bbb")
    (old / "notes.txt").write_text("ignore me")
    (old / "CREDITS.md").write_text("# Song credits\n\n- **a.mp3**: A. public domain.\n")
    dest = tmp_path / "songs"

    imported, skipped = import_songs([old], dest, move=True, log=lambda s: None)

    assert (imported, skipped) == (2, 0)
    assert sorted(p.name for p in dest.iterdir()) == ["CREDITS.md", "a.mp3", "b_c.ogg"]
    assert not (old / "a.mp3").exists() and not (old / "CREDITS.md").exists()
    assert (old / "notes.txt").exists()
    assert "- **a.mp3**: A. public domain." in (dest / "CREDITS.md").read_text()


def test_import_copies_and_handles_duplicates(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "song.mp3").write_bytes(b"one")
    dest = tmp_path / "songs"
    dest.mkdir()
    (dest / "song.mp3").write_bytes(b"different")

    assert import_songs([src], dest, log=lambda s: None) == (1, 0)
    assert (src / "song.mp3").exists()  # copy leaves the original
    assert (dest / "song_2.mp3").read_bytes() == b"one"
    # Same file again: recognised, not duplicated.
    assert import_songs([src], dest, log=lambda s: None) == (0, 1)


def test_import_single_files_and_missing(tmp_path):
    f = tmp_path / "x.wav"
    f.write_bytes(b"w")
    lines = []
    imported, _ = import_songs([f, tmp_path / "nope"], tmp_path / "songs", log=lines.append)
    assert imported == 1 and any("not found" in line for line in lines)
