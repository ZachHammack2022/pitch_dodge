"""The browser rules (web/rules.js) must play a chart exactly like world.py.

Runs the same chart and the same scripted input through both and compares
scores, counts and the sequence of events. Skipped if Node isn't installed.
"""

import json
import math
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
from helpers import make_song

from pitch_dodge.chart import build_chart
from pitch_dodge.config import DIFFICULTIES, HEIGHT, TOP_MARGIN
from pitch_dodge.world import World

NODE = shutil.which("node")
RUNNER = Path(__file__).parent / "js" / "run_world.js"

pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")


def song():
    """A synthetic song with melody, sustains (holds), loud and quiet parts, and drums."""
    return make_song(
        duration=40,
        beats=np.arange(0.5, 40, 0.5),
        pitch=lambda t: 0.5 + 0.35 * math.sin(t * 0.9) if (t % 8) < 6 else 0.3,
        energy=lambda t: 0.2 if t < 10 else 0.8,
        # Melody notes every half beat for 6 s, then one sustained note for 2 s.
        harmonic=lambda t: 1.0 if ((t % 8) < 6 and (t % 0.5) < 0.05) or 6 <= (t % 8) < 6.05 else 0.0,
        percussive=lambda t: 1.0 if (t % 1.0) < 0.05 else 0.1,
    )


def inputs(chart, kind):
    """Scripted play: uneven frame times, keys for a while, then a wandering pointer."""
    rng = np.random.default_rng(3)
    t = -chart.count_in
    out = []
    while t < chart.duration + 3:
        dt = float(rng.choice([1 / 144, 1 / 60, 1 / 30, 1 / 20]))
        t += dt
        if kind == "keys":
            direction = [-1, 0, 1][int(t * 1.7) % 3]
            target = None
        else:
            direction = 0
            target = TOP_MARGIN + (HEIGHT - TOP_MARGIN) * (0.5 + 0.45 * math.sin(t * 1.3))
        out.append([t, dt, direction, target])
    return out


def run_python(chart, difficulty, script):
    w = World(chart, difficulty)
    events = []
    for t, dt, direction, target in script:
        events += [[e.kind, e.value or 0] for e in w.update(t, dt, direction, target)]
    return {
        "score": w.score,
        "caught": w.caught,
        "perfect": w.perfect,
        "missed": w.missed,
        "hits": w.hits,
        "holds": w.holds,
        "holds_completed": w.holds_completed,
        "lives": w.lives,
        "over": w.over,
        "cleared": w.cleared,
        "paddle_y": round(w.paddle.y, 3),
        "events": events,
    }


def run_js(chart, difficulty, script, tmp_path):
    data = {
        "chart": {**chart.to_json(), "lives": difficulty.lives, "paddle_height": difficulty.paddle_height},
        "inputs": script,
    }
    f = tmp_path / "input.json"
    f.write_text(json.dumps(data))
    out = subprocess.run([NODE, str(RUNNER), str(f)], capture_output=True, text=True, check=True, timeout=60)
    return json.loads(out.stdout)


@pytest.mark.parametrize("name", ["easy", "normal", "hard"])
@pytest.mark.parametrize("control", ["keys", "pointer"])
def test_browser_rules_match_python(name, control, tmp_path):
    d = DIFFICULTIES[name]
    chart = build_chart(song(), d)
    # JSON rounds note times and pitches; play the rounded chart on both sides.
    from pitch_dodge.chart import Chart, ChartNote

    rounded = chart.to_json()
    chart = Chart(
        notes=[ChartNote(**n) for n in rounded["notes"]],
        beats=rounded["beats"],
        duration=chart.duration,
        speed=chart.speed,
        travel_time=chart.travel_time,
        count_in=chart.count_in,
    )
    script = inputs(chart, control)
    py = run_python(chart, d, script)
    js = run_js(chart, d, script, tmp_path)

    assert any(n.duration > 0 for n in chart.notes), "test song should produce holds"
    assert any(n.kind == "hazard" for n in chart.notes), "test song should produce hazards"
    assert py["caught"] + py["missed"] > 20
    assert [e[0] for e in js["events"]] == [e[0] for e in py["events"]]
    assert js == py
