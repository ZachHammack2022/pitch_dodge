from audio_utils import load_audio
from pitch_analysis import extract_pitch_track
from game_loop import run_game
import sys
import os

DEFAULT_AUDIO_PATH = "music_files/jungle_waves.mp3"

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(f"No audio file provided. Using default: {DEFAULT_AUDIO_PATH}")
        audio_path = DEFAULT_AUDIO_PATH
    else:
        audio_path = sys.argv[1]

    if not os.path.exists(audio_path):
        print(f"Error: File not found: {audio_path}")
        sys.exit(1)

    y, sr, wav_path = load_audio(audio_path)

    print("Analyzing audio...")
    pitch_track, min_pitch, max_pitch = extract_pitch_track(y, sr)

    run_game(y, sr, wav_path, pitch_track, min_pitch, max_pitch)
