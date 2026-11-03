# 🎵 Pitch Dodge

**Dodge the melody.** Pitch Dodge turns any song into a bullet-dodging game: it
listens to the track, and every time a note lands it fires a projectile from the
left edge of the screen at the height of the current pitch. Low notes come in
low and warm-coloured, high notes come in high and cool. Steer your paddle out
of the way, build a streak, and survive to the end of the song.

![Gameplay](docs/demo.gif)

## Play in your browser (macOS / Linux)

You need Python 3.10 or newer. On a Mac, install it with
[Homebrew](https://brew.sh) (`brew install python@3.12`) or the
[python.org installer](https://www.python.org/downloads/macos/). The
`python3` that comes with Xcode is too old.

```bash
git clone https://github.com/ZachHammack2022/pitch_dodge.git
cd pitch_dodge
./setup.sh     # one time: creates .venv and installs everything
./play.sh      # starts the server and opens http://localhost:8000
```

Press **Space** to play. To play your own music, drag an mp3 / wav / ogg /
flac onto the page. It's copied to `~/.local/share/pitch_dodge/songs`, and you
can also drop files into that folder directly. Stop the server with
**Ctrl+C**.

### Getting free music

`pitch-dodge fetch` downloads freely licensed recordings (by default
[Musopen](https://musopen.org)'s public-domain classical recordings) from the
[Internet Archive](https://archive.org) straight into your song library:

```bash
.venv/bin/pitch-dodge fetch                         # 10 tracks
.venv/bin/pitch-dodge fetch --query "chopin" -n 5   # search for something specific
.venv/bin/pitch-dodge fetch --dry-run               # just list what it would get
```

It only keeps items labelled public domain or Creative Commons, picks tracks
between 1 and 8 minutes long (`--min-minutes` / `--max-minutes`), skips files
you already have, and records each track's source and license in `CREDITS.md`
in the songs folder. It doesn't use musopen.org itself, which needs an account
for downloads and limits how many you can make.

`./play.sh` passes options through to `pitch-dodge serve`:

| Option | |
| --- | --- |
| `--port 8080` | use another port (if 8000 is taken) |
| `--songs ~/Music/some_folder` | also list songs from a folder (repeatable) |
| `--no-browser` | don't open a tab automatically |
| `--host 0.0.0.0` | let other devices on your Wi-Fi play at `http://<your-mac>.local:8000` |

The first time a song is played it's analysed (a few seconds); the result is
cached in `~/.cache/pitch_dodge`, so it's instant after that. High scores are
saved by the server, so they're shared between browsers and with the desktop
version.

## Desktop version

The original pygame window still works:

```bash
.venv/bin/pitch-dodge                        # bundled song
.venv/bin/pitch-dodge my_song.mp3 -d hard
```

## How to play

| Key | Action |
| --- | --- |
| ↑ / ↓ or W / S | move the paddle (on the menu: pick a song) |
| ← / → on the menu | choose difficulty |
| Space / Enter | start |
| P or Esc | pause (R restart, Q back to menu) |
| M | mute |
| R on the results screen | play again |

Switching to another tab or window pauses the game.

- Every note that gets past your paddle without touching it scores **10 points**,
  or **15** for a near miss.
- Every 10 dodges in a row raises your **multiplier** (up to ×8). Getting hit
  resets it.
- A hit costs a **life** and makes you briefly invulnerable. Lose them all and it's
  game over; clear the song for a bonus of 250 per life left.
- Notes speed up and come more often as the song goes on.
- The faint line across the screen is the song's recent melody, the path the
  notes are being fired along.
- Top 5 scores are kept per song and difficulty in
  `~/.local/share/pitch_dodge/scores.json`.

| Difficulty | Lives | Notes | Speed |
| --- | --- | --- | --- |
| easy | 5 | sparse | gentle |
| normal | 3 | follows the beat | ramps up |
| hard | 2 | nearly every onset | fast, steep angles |

![Title screen](docs/title.png)

## Command-line reference

```
pitch-dodge serve [--port N] [--host ADDR] [--songs DIR] [--no-browser] [--no-cache]
pitch-dodge [song] [-d {easy,normal,hard}] [--mute] [--seed N] [--no-cache]
```

In the desktop version, `--seed` makes note angles repeatable (in the browser,
add `?seed=N` to the URL). If no audio device is available the desktop game
runs silently instead of crashing.

## How it works

1. **Analysis** (`pitch_dodge/analysis.py`): the song is loaded with
   [librosa](https://librosa.org/). Pitch is tracked with `piptrack`, quiet frames
   are dropped, gaps are filled, the curve is median-smoothed on a log scale and
   normalised between its 5th and 95th percentiles. Onsets decide when notes are
   fired; RMS loudness drives the background pulse.
2. **Rules** (`pitch_dodge/world.py`): pure Python with no pygame, so it's fully
   unit tested. Notes move in sub-steps so even fast ones can't tunnel through
   the paddle on a slow frame.
3. **Clock** (`pitch_dodge/audio.py`): the game runs on the music's playback
   position, not the wall clock, so the notes stay in sync with what you hear,
   including across pauses.
4. **Drawing** (`pitch_dodge/render.py`) and the **state machine**
   (`pitch_dodge/app.py`): title, playing, paused and results screens.
   Sound effects are synthesised at start-up (`pitch_dodge/sfx.py`).
5. **Browser version**: `pitch_dodge/server.py` is a small standard-library
   HTTP server bound to localhost. It serves the page, the song list, uploads,
   high scores, and each song's analysis as JSON. `pitch_dodge/web/game.js`
   is a port of the rules and drawing to canvas. Its clock is the Web Audio
   playback position, so pausing suspends the music and the game together.
   The rules mirror `world.py`; change both together.

## Development

```bash
pip install -e ".[dev]"
pytest              # runs headless, no audio device needed
ruff check . && ruff format --check .
python tools/record_demo.py   # regenerate the GIF and screenshots in docs/
```

CI runs lint and tests on Linux (Python 3.10, 3.12, 3.13) and macOS for every push.
