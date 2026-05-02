import subprocess
import os
import math

def get_ffmpeg_exe():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return "ffmpeg"

def note_to_freq(note):
    return 440.0 * (2.0 ** ((note - 69) / 12.0))