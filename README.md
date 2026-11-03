# 🎵 Pitch Dodge

**Dodge the melody.** Pitch Dodge turns any song into a bullet-dodging game: it
listens to the track, and every time a note lands it fires a projectile from the
left edge of the screen at the height of the current pitch. Low notes come in
low and warm-coloured, high notes come in high and cool. Steer your paddle out
of the way, build a streak, and survive to the end of the song.

![Gameplay](docs/demo.gif)

## Quick start

```bash
pip install -r requirements.txt
python -m pitch_dodge                      # plays the bundled track
python -m pitch_dodge path/to/song.mp3     # or any wav / mp3 / ogg / flac
```

Or install it as a command:

```bash
pip install -e .
pitch-dodge my_song.mp3 --difficulty hard
```

The first time you play a song it's analysed (a few seconds); the result is
cached in `~/.cache/pitch_dodge`, so later runs start instantly.

## How to play

| Key | Action |
| --- | --- |
| ↑ / ↓ or W / S | move the paddle |
| ← / → on the title screen | choose difficulty |
| Space / Enter | start |
| P or Esc | pause (R restart, Q back to menu) |
| M | mute |
| R on the results screen | play again |

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

## Command-line options

```
pitch-dodge [song] [-d {easy,normal,hard}] [--mute] [--seed N] [--no-cache]
```

`--seed` makes note angles repeatable. If no audio device is available the game
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

## Development

```bash
pip install -e ".[dev]"
pytest              # 40 tests, runs headless
ruff check . && ruff format --check .
python tools/record_demo.py   # regenerate the GIF and screenshots in docs/
```

CI runs lint and tests on Python 3.10, 3.12 and 3.13 for every push.
