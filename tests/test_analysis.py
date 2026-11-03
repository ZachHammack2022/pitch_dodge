import numpy as np
import pytest

from pitch_dodge.analysis import (
    SAMPLE_RATE,
    SongAnalysis,
    _forward_fill,
    analyse_file,
    analyse_signal,
    normalise_energy,
    normalise_pitch,
)


def sweep(f0, f1, seconds, sr=SAMPLE_RATE):
    t = np.arange(int(seconds * sr)) / sr
    freq = f0 * (f1 / f0) ** (t / seconds)  # exponential sweep
    phase = 2 * np.pi * np.cumsum(freq) / sr
    return (0.5 * np.sin(phase)).astype(np.float32)


def test_forward_fill_fills_gaps_and_leading_nans():
    out = _forward_fill(np.array([np.nan, 2.0, np.nan, np.nan, 5.0, np.nan]), fallback=0)
    assert out.tolist() == [2.0, 2.0, 2.0, 2.0, 5.0, 5.0]


def test_forward_fill_all_nan_uses_fallback():
    assert _forward_fill(np.array([np.nan, np.nan]), fallback=7).tolist() == [7, 7]


def test_normalise_pitch_is_gap_free_and_in_range():
    hz = np.array([np.nan, 100, 200, np.nan, 400, 0, 800, np.nan] * 10, dtype=float)
    out = normalise_pitch(hz, smooth_frames=1)
    assert not np.isnan(out).any()
    assert out.min() >= 0 and out.max() <= 1


def test_normalise_pitch_uses_log_scale():
    # 100 -> 200 -> 400 Hz are equal steps on a log scale.
    hz = np.repeat([100.0, 200.0, 400.0], 50)
    out = normalise_pitch(hz, smooth_frames=1)
    low, mid, high = out[0], out[75], out[-1]
    assert mid - low == pytest.approx(high - mid, abs=1e-6)


@pytest.mark.parametrize("hz", [np.full(20, np.nan), np.full(20, 440.0), np.zeros(20)])
def test_normalise_pitch_degenerate_inputs_centre(hz):
    assert np.allclose(normalise_pitch(hz), 0.5)


def test_normalise_energy():
    assert normalise_energy(np.zeros(5)).tolist() == [0] * 5
    out = normalise_energy(np.linspace(0, 1, 100))
    assert out.min() == 0 and out.max() == 1


def test_rising_sweep_gives_rising_pitch():
    song = analyse_signal(sweep(110, 880, 4.0))
    third = len(song.pitch) // 3
    assert song.pitch[:third].mean() < song.pitch[third : 2 * third].mean() < song.pitch[2 * third :].mean()
    assert song.duration == pytest.approx(4.0, abs=0.01)
    assert len(song.energy) == len(song.pitch)


def test_onsets_found_for_clicks():
    sr = SAMPLE_RATE
    y = np.zeros(sr * 3, dtype=np.float32)
    for t in (0.5, 1.0, 1.5, 2.0, 2.5):
        i = int(t * sr)
        y[i : i + 400] = np.sin(np.arange(400) * 0.3) * np.exp(-np.arange(400) / 80)
    song = analyse_signal(y)
    assert len(song.onsets) >= 4
    assert np.all(np.diff(song.onsets) > 0)


def test_too_short_raises():
    with pytest.raises(ValueError):
        analyse_signal(np.zeros(100, dtype=np.float32))


def test_lookup_clamps_out_of_range_times():
    song = SongAnalysis(np.array([0.1, 0.9]), np.array([0.0, 1.0]), np.array([]), 0.5, 1.0)
    assert song.pitch_at(-5) == pytest.approx(0.1)
    assert song.pitch_at(99) == pytest.approx(0.9)
    assert song.energy_at(0.6) == pytest.approx(1.0)


def test_analyse_file_caches(tmp_path, monkeypatch):
    import soundfile as sf

    monkeypatch.delenv("PITCH_DODGE_NO_CACHE", raising=False)
    wav = tmp_path / "tone.wav"
    sf.write(wav, sweep(220, 440, 1.5), SAMPLE_RATE)
    cache = tmp_path / "cache"

    first = analyse_file(wav, cache_dir=cache)
    assert len(list(cache.glob("*.npz"))) == 1

    import pitch_dodge.analysis as mod

    monkeypatch.setattr(mod, "analyse_signal", lambda *a, **k: pytest.fail("should use cache"))
    second = analyse_file(wav, cache_dir=cache)
    assert np.array_equal(first.pitch, second.pitch)
    assert second.duration == pytest.approx(first.duration)


def test_analyse_file_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        analyse_file(tmp_path / "nope.wav")
