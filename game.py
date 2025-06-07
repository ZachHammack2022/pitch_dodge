from audio_utils import load_audio
from pitch_analysis import extract_pitch_track
from game_loop import run_game
import sys

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python game.py <audiofile.mp3 or .wav>")
        sys.exit(1)

    audio_path = sys.argv[1]
    y, sr, wav_path = load_audio(audio_path)

    print("Analyzing audio...")
    pitch_track, min_pitch, max_pitch = extract_pitch_track(y, sr)

    run_game(y, sr, wav_path, pitch_track, min_pitch, max_pitch)
