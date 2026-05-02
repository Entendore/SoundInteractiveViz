# --- Configuration ---
WIDTH, HEIGHT = 950, 700
FPS = 60
SAMPLE_RATE = 44100
BUFFER_SIZE = 512

# --- Settings Data ---
PRESET_NAMES = ["Ambient Pad", "Psychedelic FM", "Rhythmic Gate", "Binaural Focus"]
VISUAL_NAMES = ["Mandala", "Tunnel", "Lissajous", "Particles"]
COLOR_NAMES = ["Rainbow", "Ocean", "Fire", "Neon", "Monochrome"]
SCALE_NAMES = ["Chromatic (Free)", "Major Scale", "Minor Scale", "Pentatonic"]

# Music Theory Data (Semitone intervals from root)
SCALES = {
    0: [], # Chromatic (no snap)
    1: [0, 2, 4, 5, 7, 9, 11], # Major
    2: [0, 2, 3, 5, 7, 8, 10], # Minor
    3: [0, 2, 4, 7, 9]          # Pentatonic
}

# Menu Options
TRAIL_OPTIONS = [("Long", 15), ("Medium", 35), ("Short", 80)]
RES_OPTIONS = [("Window Size", None), ("720p", (1280, 720)), ("1080p", (1920, 1080))]
DUR_OPTIONS = [("Manual", 0), ("5 sec", 5), ("10 sec", 10), ("30 sec", 30)]