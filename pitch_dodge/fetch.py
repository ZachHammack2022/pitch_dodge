"""Download freely licensed recordings (Musopen's and others) from the Internet Archive.

Musopen (musopen.org) records public-domain classical music, but its own
site needs an account for downloads and limits how many you can make, so this
doesn't touch it. Much of Musopen's catalogue is also published on the
Internet Archive, which has a public API meant for exactly this kind of use.

    pitch-dodge fetch                       # 10 Musopen recordings
    pitch-dodge fetch --query "chopin" --limit 5
    pitch-dodge fetch --dry-run             # list what would be downloaded

Only items whose license is public domain or Creative Commons are kept (see
``--allow-unlabeled``). Files go into the game's song library, and every
download is recorded with its source and license in CREDITS.md there.
"""

from __future__ import annotations

import argparse
import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from . import __version__

API_SEARCH = "https://archive.org/advancedsearch.php"
API_METADATA = "https://archive.org/metadata/{identifier}"
DOWNLOAD = "https://archive.org/download/{identifier}/{name}"
DETAILS = "https://archive.org/details/{identifier}"
USER_AGENT = f"pitch-dodge/{__version__} (music fetcher; https://github.com/ZachHammack2022/pitch_dodge)"

DEFAULT_QUERY = "musopen"
# Preferred file formats, best first. MP3s are smallest and play everywhere.
FORMATS = ["VBR MP3", "128Kbps MP3", "MP3", "Ogg Vorbis", "Flac"]

Getter = Callable[[str], bytes]


# ---------------------------------------------------------------- licenses


def license_kind(url: str | None) -> str | None:
    """Classify a license URL: 'public domain', 'CC BY', 'CC BY-SA'..., or None if not free."""
    if not url:
        return None
    u = url.lower()
    if "publicdomain" in u:  # covers CC0 (/publicdomain/zero/) and the PD mark
        return "public domain"
    if "creativecommons.org/licenses/" in u:
        code = u.split("/licenses/")[1].split("/")[0]  # e.g. "by-sa"
        return "CC " + code.upper()
    return None


# ---------------------------------------------------------------- API


def ssl_context() -> ssl.SSLContext:
    """Verify certificates against the operating system's trust store.

    Python normally uses its own bundle of certificates and ignores the macOS
    Keychain / Windows certificate store. On networks that inspect HTTPS (work
    VPNs, corporate proxies, some antivirus) the proxy's certificate is only in
    the OS store, so Python rejects every connection. ``truststore`` makes it
    trust what the browser trusts. ``SSL_CERT_FILE`` still works as an override.
    """
    import os

    if not os.environ.get("SSL_CERT_FILE"):
        try:
            import truststore

            return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        except ImportError:
            pass
    return ssl.create_default_context()


_CONTEXT: ssl.SSLContext | None = None


def http_get(url: str, timeout: float = 60) -> bytes:
    global _CONTEXT
    if _CONTEXT is None:
        _CONTEXT = ssl_context()
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout, context=_CONTEXT) as r:
        return r.read()


def explain_connection_error(exc: urllib.error.URLError) -> str:
    reason = exc.reason
    msg = f"pitch-dodge: couldn't reach archive.org ({reason})"
    if isinstance(reason, ssl.SSLCertVerificationError) or "CERTIFICATE_VERIFY_FAILED" in str(reason):
        msg += (
            "\n\nSomething on your network (a VPN, corporate proxy or antivirus) is intercepting"
            "\nHTTPS with a certificate Python doesn't trust. Fixes, in order:"
            "\n  1. Re-run ./setup.sh so the 'truststore' package is installed; it makes Python"
            "\n     trust the same certificates as your browser."
            "\n  2. Or point Python at your network's root certificate:"
            "\n       SSL_CERT_FILE=/path/to/company-root.pem .venv/bin/pitch-dodge fetch"
            "\n  3. Or try again off the VPN / on another network."
        )
    return msg


def search(query: str, get: Getter, page_size: int = 50, max_pages: int = 20) -> Iterator[dict]:
    """Yield audio items matching ``query``, most downloaded first."""
    q = f"({query}) AND mediatype:(audio)"
    for page in range(1, max_pages + 1):
        params = [
            ("q", q),
            ("fl[]", "identifier"),
            ("fl[]", "title"),
            ("fl[]", "creator"),
            ("fl[]", "licenseurl"),
            ("sort[]", "downloads desc"),
            ("rows", str(page_size)),
            ("page", str(page)),
            ("output", "json"),
        ]
        data = json.loads(get(f"{API_SEARCH}?{urllib.parse.urlencode(params)}"))
        docs = data.get("response", {}).get("docs", [])
        yield from docs
        if len(docs) < page_size:
            return


def _seconds(length) -> float | None:
    """Archive.org gives lengths as '312.45' or '5:12'."""
    if length is None:
        return None
    try:
        s = str(length)
        if ":" in s:
            total = 0.0
            for part in s.split(":"):
                total = total * 60 + float(part)
            return total
        return float(s)
    except ValueError:
        return None


@dataclass(frozen=True)
class Track:
    identifier: str
    name: str  # file name inside the item
    title: str
    creator: str
    license: str
    license_url: str
    seconds: float | None

    @property
    def url(self) -> str:
        return DOWNLOAD.format(identifier=self.identifier, name=urllib.parse.quote(self.name))

    @property
    def page(self) -> str:
        return DETAILS.format(identifier=self.identifier)


def _text(v) -> str:
    if isinstance(v, list):
        return ", ".join(str(x) for x in v)
    return str(v or "")


def pick_tracks(
    metadata: dict,
    min_seconds: float,
    max_seconds: float,
    allow_unlabeled: bool = False,
) -> list[Track]:
    """Choose the audio files worth downloading from one item's metadata.

    Each recording usually exists in several formats; keep the best format of
    each, and only recordings whose length suits a game round.
    """
    meta = metadata.get("metadata", {})
    identifier = meta.get("identifier", "")
    license_url = _text(meta.get("licenseurl"))
    kind = license_kind(license_url)
    if kind is None:
        if not allow_unlabeled:
            return []
        kind = "unlabeled (check the item page)"

    best: dict[str, tuple[int, dict]] = {}
    for f in metadata.get("files", []):
        fmt = f.get("format")
        if fmt not in FORMATS:
            continue
        stem = f["name"].rsplit(".", 1)[0]
        rank = FORMATS.index(fmt)
        if stem not in best or rank < best[stem][0]:
            best[stem] = (rank, f)

    tracks = []
    for _, f in sorted(best.values(), key=lambda rf: rf[1]["name"]):
        secs = _seconds(f.get("length"))
        if secs is not None and not (min_seconds <= secs <= max_seconds):
            continue
        tracks.append(
            Track(
                identifier=identifier,
                name=f["name"],
                title=_text(f.get("title")) or f["name"].rsplit(".", 1)[0],
                creator=_text(f.get("creator") or f.get("artist") or meta.get("creator")),
                license=kind,
                license_url=license_url,
                seconds=secs,
            )
        )
    return tracks


# ---------------------------------------------------------------- download


def target_name(track: Track) -> str | None:
    from .server import safe_filename

    return safe_filename(f"{track.title or Path(track.name).stem}{Path(track.name).suffix}")


def append_credit(credits: Path, track: Track, filename: str) -> None:
    new = not credits.exists()
    with open(credits, "a", encoding="utf-8") as f:
        if new:
            f.write("# Song credits\n\nDownloaded with `pitch-dodge fetch` from the Internet Archive.\n\n")
        who = f" — {track.creator}" if track.creator else ""
        lic = f"[{track.license}]({track.license_url})" if track.license_url else track.license
        f.write(f"- **{filename}**: {track.title}{who}. {lic}. Source: {track.page}\n")


def fetch(
    query: str = DEFAULT_QUERY,
    limit: int = 10,
    dest: Path | None = None,
    min_minutes: float = 1.0,
    max_minutes: float = 8.0,
    per_item: int = 2,
    allow_unlabeled: bool = False,
    dry_run: bool = False,
    delay: float = 1.0,
    get: Getter = http_get,
    log: Callable[[str], None] = print,
) -> list[Path]:
    """Download up to ``limit`` tracks. Returns the paths written (none for a dry run)."""
    from .server import default_library

    dest = dest or default_library()
    if not dry_run:
        dest.mkdir(parents=True, exist_ok=True)
    credits = dest / "CREDITS.md"
    written: list[Path] = []
    found = 0
    skipped_license = 0

    for item in search(query, get):
        if found >= limit:
            break
        identifier = item.get("identifier")
        if not identifier:
            continue
        if not allow_unlabeled and license_kind(_text(item.get("licenseurl"))) is None:
            skipped_license += 1
            continue
        time.sleep(delay)
        try:
            meta = json.loads(get(API_METADATA.format(identifier=urllib.parse.quote(identifier))))
        except (urllib.error.URLError, ValueError) as exc:
            log(f"  ! couldn't read {identifier}: {exc}")
            continue

        tracks = pick_tracks(meta, min_minutes * 60, max_minutes * 60, allow_unlabeled)[:per_item]
        for track in tracks:
            if found >= limit:
                break
            name = target_name(track)
            if name is None:
                continue
            path = dest / name
            mins = f"{track.seconds / 60:.1f} min" if track.seconds else "? min"
            label = f"{track.title} ({mins}, {track.license})"
            if path.exists():
                log(f"  = already have {label}")
                found += 1
                continue
            if dry_run:
                log(f"  - would download {label}\n      {track.url}")
                found += 1
                continue
            log(f"  + {label}")
            time.sleep(delay)
            try:
                data = get(track.url)
            except urllib.error.URLError as exc:
                log(f"  ! download failed: {exc}")
                continue
            tmp = path.with_suffix(path.suffix + ".part")
            tmp.write_bytes(data)
            tmp.replace(path)
            append_credit(credits, track, name)
            written.append(path)
            found += 1

    if found == 0:
        hint = (
            " Try --allow-unlabeled or a different --query." if skipped_license else " Try another --query."
        )
        log(f"Nothing suitable found ({skipped_license} items skipped for having no free license).{hint}")
    elif not dry_run:
        log(f"\nSaved {len(written)} new track(s) to {dest}")
        log(f"Credits are in {credits}. Restart ./play.sh or refresh the page to see them.")
    return written


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="pitch-dodge fetch",
        description="Download freely licensed recordings (Musopen and others) from the Internet Archive.",
    )
    p.add_argument("-q", "--query", default=DEFAULT_QUERY, help=f'search terms (default "{DEFAULT_QUERY}")')
    p.add_argument("-n", "--limit", type=int, default=10, help="how many tracks to get (default 10)")
    p.add_argument("--dest", type=Path, help="folder to save into (default: the game's song library)")
    p.add_argument("--min-minutes", type=float, default=1.0, help="skip shorter tracks (default 1)")
    p.add_argument("--max-minutes", type=float, default=8.0, help="skip longer tracks (default 8)")
    p.add_argument("--per-item", type=int, default=2, help="max tracks from one album/item (default 2)")
    p.add_argument(
        "--allow-unlabeled",
        action="store_true",
        help="also take items with no license field (check their pages yourself)",
    )
    p.add_argument("--dry-run", action="store_true", help="list what would be downloaded")
    return p.parse_args(argv)


def main(argv: list[str]) -> int:
    a = parse_args(argv)
    print(f'Searching the Internet Archive for "{a.query}" ...')
    try:
        fetch(
            query=a.query,
            limit=a.limit,
            dest=a.dest,
            min_minutes=a.min_minutes,
            max_minutes=a.max_minutes,
            per_item=a.per_item,
            allow_unlabeled=a.allow_unlabeled,
            dry_run=a.dry_run,
        )
    except urllib.error.URLError as exc:
        print(explain_connection_error(exc))
        return 1
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0
