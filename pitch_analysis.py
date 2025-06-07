import librosa
import numpy as np

def extract_pitch_track(y, sr):
    pitches, magnitudes = librosa.piptrack(y=y, sr=sr, fmin=50.0, fmax=2000.0)
    pitch_track = []
    for i in range(pitches.shape[1]):
        index = magnitudes[:, i].argmax()
        pitch = pitches[index, i]
        pitch_track.append(pitch if pitch > 0 else None)

    valid_pitches = [p for p in pitch_track if p]
    min_pitch = min(valid_pitches)
    max_pitch = max(valid_pitches)

    return pitch_track, min_pitch, max_pitch