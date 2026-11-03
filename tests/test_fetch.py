"""The music fetcher, against canned archive.org responses (no network)."""

import json
import urllib.parse

import pytest

from pitch_dodge.fetch import fetch, license_kind, pick_tracks

PD = "http://creativecommons.org/publicdomain/mark/1.0/"
CC0 = "https://creativecommons.org/publicdomain/zero/1.0/"
BY = "https://creativecommons.org/licenses/by/4.0/"
NC = "https://creativecommons.org/licenses/by-nc/3.0/"


@pytest.mark.parametrize(
    "url,kind",
    [
        (PD, "public domain"),
        (CC0, "public domain"),
        (BY, "CC BY"),
        (NC, "CC BY-NC"),
        ("https://example.com/all-rights-reserved", None),
        ("", None),
        (None, None),
    ],
)
def test_license_kind(url, kind):
    assert license_kind(url) == kind


def item(identifier, license_url, files):
    return {
        "metadata": {"identifier": identifier, "licenseurl": license_url, "creator": "Musopen"},
        "files": files,
    }


NOCTURNE_FILES = [
    {"name": "Nocturne.flac", "format": "Flac", "length": "300.0", "title": "Nocturne Op. 9 No. 2"},
    {"name": "Nocturne.mp3", "format": "VBR MP3", "length": "300.0", "title": "Nocturne Op. 9 No. 2"},
    {"name": "Nocturne.ogg", "format": "Ogg Vorbis", "length": "300.0"},
    {"name": "Etude.mp3", "format": "VBR MP3", "length": "2:10", "title": "Etude"},
    {"name": "Sonata.mp3", "format": "VBR MP3", "length": "1500", "title": "Sonata (too long)"},
    {"name": "Jingle.mp3", "format": "VBR MP3", "length": "20", "title": "Jingle (too short)"},
    {"name": "cover.jpg", "format": "JPEG"},
]


def test_pick_tracks_prefers_mp3_and_filters_length():
    tracks = pick_tracks(item("chopin", PD, NOCTURNE_FILES), min_seconds=60, max_seconds=480)
    assert [t.name for t in tracks] == ["Etude.mp3", "Nocturne.mp3"]
    assert tracks[0].seconds == 130
    assert tracks[1].license == "public domain"
    assert tracks[1].url == "https://archive.org/download/chopin/Nocturne.mp3"


def test_pick_tracks_skips_unlicensed_unless_allowed():
    meta = item("mystery", "", NOCTURNE_FILES)
    assert pick_tracks(meta, 60, 480) == []
    assert len(pick_tracks(meta, 60, 480, allow_unlabeled=True)) == 2


class FakeArchive:
    def __init__(self, items):
        self.items = {i["metadata"]["identifier"]: i for i in items}
        self.requests = []

    def __call__(self, url):
        self.requests.append(url)
        parsed = urllib.parse.urlparse(url)
        if parsed.path == "/advancedsearch.php":
            docs = [
                {"identifier": k, "licenseurl": v["metadata"]["licenseurl"], "title": k}
                for k, v in self.items.items()
            ]
            return json.dumps({"response": {"docs": docs}}).encode()
        if parsed.path.startswith("/metadata/"):
            return json.dumps(self.items[parsed.path.split("/")[-1]]).encode()
        if parsed.path.startswith("/download/"):
            return b"ID3fake-mp3-bytes"
        raise AssertionError(url)


def test_fetch_downloads_and_writes_credits(tmp_path):
    archive = FakeArchive(
        [
            item("chopin", PD, NOCTURNE_FILES),
            item("secret", "", [{"name": "x.mp3", "format": "VBR MP3", "length": "200"}]),
            item(
                "bach",
                BY,
                [{"name": "Prelude.mp3", "format": "VBR MP3", "length": "150", "title": "Prelude"}],
            ),
        ]
    )
    out = fetch(limit=3, dest=tmp_path, delay=0, get=archive, log=lambda s: None)

    assert sorted(p.name for p in out) == ["Etude.mp3", "Nocturne_Op_9_No_2.mp3", "Prelude.mp3"]
    assert (tmp_path / "Prelude.mp3").read_bytes() == b"ID3fake-mp3-bytes"
    assert not any("secret" in u for u in archive.requests)  # unlicensed item never fetched
    credits = (tmp_path / "CREDITS.md").read_text()
    assert "Prelude" in credits and "CC BY" in credits and "https://archive.org/details/bach" in credits
    assert "public domain" in credits

    # Running again downloads nothing new.
    again = fetch(limit=3, dest=tmp_path, delay=0, get=archive, log=lambda s: None)
    assert again == []


def test_fetch_respects_limit_and_dry_run(tmp_path):
    archive = FakeArchive([item("chopin", PD, NOCTURNE_FILES)])
    lines = []
    out = fetch(limit=1, dest=tmp_path / "songs", dry_run=True, delay=0, get=archive, log=lines.append)
    assert out == []
    assert not (tmp_path / "songs").exists()
    assert sum("would download" in line for line in lines) == 1


def test_fetch_reports_when_nothing_found(tmp_path):
    archive = FakeArchive([item("secret", "", NOCTURNE_FILES)])
    lines = []
    fetch(limit=5, dest=tmp_path, delay=0, get=archive, log=lines.append)
    assert "--allow-unlabeled" in lines[-1]
