import os
import tempfile
import atexit
from pydub import AudioSegment
import librosa

_temp_file_path = None

def convert_mp3_to_wav(mp3_path):
    global _temp_file_path
    temp_wav = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    _temp_file_path = temp_wav.name
    sound = AudioSegment.from_mp3(mp3_path)
    sound.export(temp_wav.name, format="wav")
    return temp_wav.name

def load_audio(path):
    if path.endswith('.mp3'):
        wav_path = convert_mp3_to_wav(path)
    elif path.endswith('.wav'):
        wav_path = path
    else:
        raise ValueError("Unsupported file format: must be .mp3 or .wav")

    y, sr = librosa.load(wav_path, sr=None)
    return y, sr, wav_path

@atexit.register
def cleanup_temp_file():
    global _temp_file_path
    if _temp_file_path and os.path.exists(_temp_file_path):
        os.remove(_temp_file_path)
