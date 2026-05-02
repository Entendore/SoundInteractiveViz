import pygame
import numpy as np
import pyaudio
import colorsys
import math
import random
import subprocess
import os
import threading
import wave
import sys
import struct

# --- Configuration ---
WIDTH, HEIGHT = 900, 700
FPS = 60
SAMPLE_RATE = 44100
BUFFER_SIZE = 512

# --- Helper Functions ---
def get_ffmpeg_exe():
    """Find FFmpeg executable."""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return "ffmpeg"

def note_to_freq(note):
    """Convert MIDI note number to frequency."""
    return 440.0 * (2.0 ** ((note - 69) / 12.0))

# --- Audio Engine Class ---
class SynthEngine:
    def __init__(self):
        self.phase_acc = 0.0
        self.phase_sub = 0.0
        self.phase_fm = 0.0
        self.phase_lfo = 0.0
        self.z = 0.0  # Filter state
        
        # For visualization feedback
        self.current_amp = 0.0

    def get_chunk(self, frame_count, params):
        freq = params['freq']
        mod = params['mod']
        preset = params['preset']
        
        t = np.arange(frame_count)
        
        # Phase increments
        inc_main = 2 * np.pi * freq / SAMPLE_RATE
        inc_sub = 2 * np.pi * (freq / 2) / SAMPLE_RATE
        inc_lfo = 2 * np.pi * mod / SAMPLE_RATE

        # --- Synthesis Presets ---
        if preset == 0: 
            # AMBIENT: Multi-voice detuned saw
            voices = 5
            detune = 0.15
            wave = np.zeros(frame_count)
            
            # Vectorized detuning for performance
            for i in range(voices):
                d = 1.0 + (i - voices//2) * (detune / 100.0)
                # Sawtooth wave formula
                wave += 2 * ((self.phase_acc + t * inc_main * d) % (2*np.pi)) / (2*np.pi) - 1
            
            wave /= voices
            
            sub = np.sin(self.phase_sub + t * inc_sub)
            wave = wave * 0.7 + sub * 0.3
            
            # --- Optimized Low Pass Filter ---
            # Simple one-pole IIR filter: y[n] = alpha * x[n] + (1-alpha) * y[n-1]
            alpha = 0.4
            # Trick to vectorize IIR: python loop is slow, but acceptable for small buffer
            # For production, use scipy.lfilter, but let's keep dependencies low.
            # We use numpy's iterate for slight speedup over pure python
            val = self.z
            out = np.empty_like(wave)
            for i, x in enumerate(wave):
                val = alpha * x + (1-alpha) * val
                out[i] = val
            wave = out
            self.z = val
            
            lfo = 0.5 + 0.5 * np.sin(self.phase_lfo + t * inc_lfo * 0.1)
            wave *= lfo
            left, right = wave, wave

        elif preset == 1:
            # PSYCHEDELIC: FM Synthesis
            ratio = 2.0 + mod
            mod_index = 1.0 + (np.sin(self.phase_lfo + t * 0.05) * 0.5)
            mod_sig = np.sin(self.phase_fm + t * inc_main * ratio)
            
            wave_l = np.sin(self.phase_acc + t * inc_main + mod_sig * mod_index * 6.0)
            wave_r = np.sin(self.phase_acc + t * inc_main + mod_sig * mod_index * 6.0 + np.pi/3)
            
            left, right = np.tanh(wave_l * 1.2), np.tanh(wave_r * 1.2)
            self.phase_fm += frame_count * inc_main * ratio

        elif preset == 2:
            # HYPNOTIC: Rhythmic Gating
            wave = np.sin(self.phase_acc + t * inc_main)
            gate_freq = mod * 2
            gate_phase = self.phase_lfo + t * (gate_freq * 2 * np.pi / SAMPLE_RATE)
            gate_env = np.power(np.maximum(0, np.sin(gate_phase)), 8.0)
            wave *= (0.2 + 0.8 * gate_env)
            
            kick_env = np.exp(-20 * (1.0 - np.abs(np.sin(gate_phase))))
            kick = np.sin(t * 80 * np.exp(-t * 0.1)) * kick_env * 0.5
            out = wave + kick
            left, right = out, out
            
            self.phase_lfo += gate_freq * frame_count * 2 * np.pi / SAMPLE_RATE

        else:
            # BINAURAL: Brainwave Entrainment
            beat_diff = 10 # 10Hz Alpha waves
            left = np.sin(self.phase_acc + t * inc_main)
            right = np.sin(self.phase_acc + t * (inc_main + (2 * np.pi * beat_diff / SAMPLE_RATE)))
            
            lfo = 0.7 + 0.3 * np.sin(self.phase_lfo + t * inc_lfo)
            left *= lfo
            right *= lfo

        # --- Global Updates ---
        if preset != 2:
            self.phase_lfo += frame_count * inc_lfo * 0.1
            
        self.phase_acc += frame_count * inc_main
        self.phase_sub += frame_count * inc_sub

        # Soft Limiter & Amplitude Calculation
        left = np.tanh(left * 0.8)
        right = np.tanh(right * 0.8)
        
        # Calculate loudness for visuals (RMS)
        self.current_amp = np.sqrt(np.mean(left**2 + right**2))

        return np.column_stack((left, right))

# --- Visualization Functions ---
def draw_mandala(screen, tick, freq, mod, amp, w, h):
    cx, cy = w // 2, h // 2
    hue = (tick / 500) % 1.0
    breath = math.sin(tick * mod * 0.1) + amp * 2.0 # Audio Reactive
    radius = 100 + breath * 50 * (mod * 2)
    num_layers = int(3 + (freq / 150))
    
    for i in range(num_layers):
        rot_speed = 1 + mod * 0.5
        angle_offset = (tick + i * 15) * rot_speed
        points = []
        sides = 6
        for s in range(sides):
            angle = math.radians(s * (360/sides) + angle_offset)
            dist = radius + (i * 20) * breath
            points.append((cx + dist * math.cos(angle), cy + dist * math.sin(angle)))
        
        c_hsv = (hue + i*0.03) % 1.0
        rgb = colorsys.hsv_to_rgb(c_hsv, 0.7, 1.0)
        color = (int(rgb[0]*255), int(rgb[1]*255), int(rgb[2]*255))
        if len(points) > 2:
            pygame.draw.polygon(screen, color, points, 2)
    pygame.draw.circle(screen, (255, 255, 255), (cx, cy), int(10 + radius/10))

def draw_tunnel(screen, tick, freq, mod, amp, w, h):
    cx, cy = w // 2, h // 2
    hue = (tick / 500) % 1.0
    speed = 3 + mod * 8 + amp * 4 # Audio Reactive
    for i in range(30):
        r = (tick * speed + i * 25) % (max(w, h))
        if r < 20: continue
        thickness = int(2 + (freq/200) + amp * 5)
        c_hsv = (hue + i*0.02) % 1.0
        rgb = colorsys.hsv_to_rgb(c_hsv, 0.9, 1.0)
        color = (int(rgb[0]*255), int(rgb[1]*255), int(rgb[2]*255))
        pygame.draw.circle(screen, color, (cx, cy), int(r), thickness)

def draw_lissajous(screen, tick, freq, mod, amp, w, h):
    cx, cy = w // 2, h // 2
    a = freq / 100.0
    b = mod + 2.0
    delta = tick / 50.0
    scale = min(w, h) * 0.35 * (0.8 + amp * 0.4) # Audio Reactive
    prev = None
    for t_step in range(500):
        t_val = t_step / 10.0
        x = math.sin(a * t_val + delta)
        y = math.sin(b * t_val)
        px = int(cx + x * scale)
        py = int(cy + y * scale)
        if prev:
            hue = (t_step / 500 + tick/200) % 1.0
            rgb = colorsys.hsv_to_rgb(hue, 0.8, 1.0)
            color = (int(rgb[0]*255), int(rgb[1]*255), int(rgb[2]*255))
            pygame.draw.line(screen, color, prev, (px, py), 2)
        prev = (px, py)

def draw_particles(screen, tick, freq, mod, amp, particles, w, h):
    cx, cy = w // 2, h // 2
    # Spawn more particles on louder volume
    spawn_rate = max(1, int(30 / (freq/80)))
    if tick % spawn_rate == 0:
        count = int(1 + amp * 5) # Audio Reactive
        for _ in range(count):
            angle = random.uniform(0, 360)
            speed = 2 + mod * 4
            particles.append({
                'x': cx, 'y': cy, 
                'vx': math.cos(math.radians(angle)) * speed, 
                'vy': math.sin(math.radians(angle)) * speed,
                'life': 150
            })
    
    # Optimization: Create new list for alive particles
    new_particles = []
    for p in particles:
        p['x'] += p['vx']
        p['y'] += p['vy']
        p['life'] -= 1
        
        if p['life'] > 0:
            life_ratio = p['life'] / 150.0
            size = int(4 * life_ratio)
            hue_p = (tick/200) % 1.0
            rgb = colorsys.hsv_to_rgb(hue_p, 0.9, life_ratio)
            color = (int(rgb[0]*255), int(rgb[1]*255), int(rgb[2]*255))
            if size > 0:
                pygame.draw.circle(screen, color, (int(p['x']), int(p['y'])), size)
            new_particles.append(p)
    return new_particles

# --- Main Application ---
def main():
    # Init Pygame
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.RESIZABLE)
    pygame.display.set_caption("Synth Studio Pro")
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("Arial", 18, bold=True)
    
    # Init Audio
    p = pyaudio.PyAudio()
    synth = SynthEngine()
    
    # State
    audio_params = {'freq': 220.0, 'mod': 0.5, 'preset': 0}
    particles = []
    
    # Recording State
    is_recording = False
    video_frames = []
    audio_frames = []
    
    # Keyboard Piano Map (A S D F G H J K -> C Major Scale)
    # ASCII codes: a=97, s=115, d=100, f=102, g=103, h=104, j=106, k=107
    # Using QWERTY row for ease: A W S E D F T G Y H U J K
    # Let's stick to simple: A(C) S(D) D(E) F(F) G(G) H(A) J(B) K(C_high)
    # Map: Key -> MIDI Note
    key_map = {
        pygame.K_a: 60, # C4
        pygame.K_w: 61, # C#4
        pygame.K_s: 62, # D4
        pygame.K_e: 63, # D#4
        pygame.K_d: 64, # E4
        pygame.K_f: 65, # F4
        pygame.K_t: 66, # F#4
        pygame.K_g: 67, # G4
        pygame.K_y: 68, # G#4
        pygame.K_h: 69, # A4
        pygame.K_u: 70, # A#4
        pygame.K_j: 71, # B4
        pygame.K_k: 72  # C5
    }
    
    target_freq = 220.0
    VISUAL_MODE = 1
    PRESET_NAMES = ["Ambient Pad", "Psychedelic FM", "Rhythmic Gate", "Binaural Focus"]
    VISUAL_NAMES = ["Mandala", "Tunnel", "Lissajous", "Particles"]
    
    # Audio Callback
    def audio_callback(in_data, frame_count, time_info, status):
        stereo_data = synth.get_chunk(frame_count, audio_params)
        data = (stereo_data * 32767).astype(np.int16).tobytes()
        if is_recording:
            audio_frames.append(data)
        return (data, pyaudio.paContinue)

    stream = p.open(format=pyaudio.paInt16,
                    channels=2,
                    rate=SAMPLE_RATE,
                    output=True,
                    frames_per_buffer=BUFFER_SIZE,
                    stream_callback=audio_callback)

    stream.start_stream()
    
    running = True
    tick = 0
    keys_held = []

    print("--- Synth Studio Pro ---")
    print("Mouse X/Y: Modulation")
    print("Keys A,S,D,F,G,H,J,K: Play Notes")
    print("Q/W/E/R: Sound Presets | 1-4: Visual Modes")
    print("SPACE: Record | F: Fullscreen")

    while running:
        tick += 1
        w, h = screen.get_size()
        
        # 1. Input Handling
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE: running = False
                
                # Fullscreen
                if event.key == pygame.K_f:
                    flags = screen.get_flags()
                    if flags & pygame.FULLSCREEN:
                        screen = pygame.display.set_mode((WIDTH, HEIGHT))
                    else:
                        screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
                
                # Presets
                if event.key == pygame.K_q: audio_params['preset'] = 0
                if event.key == pygame.K_w: audio_params['preset'] = 1
                if event.key == pygame.K_e: audio_params['preset'] = 2
                if event.key == pygame.K_r: audio_params['preset'] = 3
                
                # Visuals
                if event.key == pygame.K_1: VISUAL_MODE = 1
                if event.key == pygame.K_2: VISUAL_MODE = 2
                if event.key == pygame.K_3: VISUAL_MODE = 3
                if event.key == pygame.K_4: VISUAL_MODE = 4
                
                # Recording
                if event.key == pygame.K_SPACE:
                    if not is_recording:
                        print("Recording Started...")
                        is_recording = True
                        video_frames = []
                        audio_frames = []
                    else:
                        print("Recording Stopped. Saving...")
                        is_recording = False
                        threading.Thread(target=save_recording, args=(list(video_frames), b''.join(audio_frames), w, h, get_ffmpeg_exe())).start()
                
                # Keyboard Piano (Note On)
                if event.key in key_map:
                    if event.key not in keys_held:
                        keys_held.append(event.key)
            
            if event.type == pygame.KEYUP:
                # Keyboard Piano (Note Off)
                if event.key in key_map:
                    if event.key in keys_held:
                        keys_held.remove(event.key)

            if event.type == pygame.VIDEORESIZE:
                screen = pygame.display.set_mode((event.w, event.h), pygame.RESIZABLE)

        # 2. Logic Update
        
        # Pitch Logic: Keyboard overrides Mouse if keys are held
        if keys_held:
            # Play the most recently pressed key (top of stack)
            midi_note = key_map[keys_held[-1]]
            target_freq = note_to_freq(midi_note)
        else:
            # Mouse Fallback
            mx, my = pygame.mouse.get_pos()
            target_freq = 110 + (mx / w) * 770
        
        # Modulation Logic
        mx, my = pygame.mouse.get_pos()
        audio_params['mod'] = 0.1 + (1 - (my / h)) * 4.9
        
        # Frequency Smoothing (Portamento)
        audio_params['freq'] += (target_freq - audio_params['freq']) * 0.1
        
        # Get audio amplitude for visuals
        current_amp = synth.current_amp
        
        # 3. Visualization
        # Create fade trail
        trail = pygame.Surface((w, h), pygame.SRCALPHA)
        trail.fill((0, 0, 0, 35)) # Ghosting amount
        screen.blit(trail, (0, 0))

        freq = audio_params['freq']
        mod = audio_params['mod']
        
        if VISUAL_MODE == 1: draw_mandala(screen, tick, freq, mod, current_amp, w, h)
        elif VISUAL_MODE == 2: draw_tunnel(screen, tick, freq, mod, current_amp, w, h)
        elif VISUAL_MODE == 3: draw_lissajous(screen, tick, freq, mod, current_amp, w, h)
        elif VISUAL_MODE == 4: particles = draw_particles(screen, tick, freq, mod, current_amp, particles, w, h)

        # 4. UI Overlay
        # Text Background Box
        pygame.draw.rect(screen, (0,0,0,150), (5,5,250,130))
        
        ui_text = [
            f"Sound: {PRESET_NAMES[audio_params['preset']]}",
            f"Visual: {VISUAL_NAMES[VISUAL_MODE-1]}",
            f"Pitch: {int(freq)} Hz",
            f"{'[REC]' if is_recording else ''}"
        ]
        
        for i, line in enumerate(ui_text):
            surf = font.render(line, True, (255, 255, 255))
            screen.blit(surf, (10, 10 + i * 25))
            
        # Draw VU Meter
        # Background bar
        pygame.draw.rect(screen, (50, 50, 50), (w-50, 100, 20, h-200))
        # Active level
        level_h = int(current_amp * (h-200))
        # Color gradient (Green -> Yellow -> Red)
        if current_amp < 0.4: color = (0, 255, 0)
        elif current_amp < 0.7: color = (255, 255, 0)
        else: color = (255, 0, 0)
        
        pygame.draw.rect(screen, color, (w-50, 100 + (h-200-level_h), 20, level_h))

        # 5. Capture Frame (if recording)
        if is_recording:
            raw = pygame.image.tostring(screen, 'RGB')
            video_frames.append(raw)

        pygame.display.flip()
        clock.tick(FPS)

    # Cleanup
    stream.stop_stream()
    stream.close()
    p.terminate()
    pygame.quit()

def save_recording(frames, audio_data, w, h, ffmpeg_cmd):
    if not frames: return
    print(f"Processing video ({len(frames)} frames)...")
    
    # Cross-platform startupinfo
    startupinfo = None
    if os.name == 'nt':
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    # 1. Write Video
    cmd_vid = [
        ffmpeg_cmd, '-y',
        '-f', 'rawvideo',
        '-vcodec', 'rawvideo',
        '-s', f'{w}x{h}',
        '-pix_fmt', 'rgb24',
        '-r', str(FPS),
        '-i', '-',
        '-c:v', 'libx264',
        '-preset', 'fast',
        '-pix_fmt', 'yuv420p',
        'temp_video.mp4'
    ]
    try:
        process = subprocess.Popen(cmd_vid, stdin=subprocess.PIPE, startupinfo=startupinfo)
        for frame in frames:
            process.stdin.write(frame)
        process.stdin.close()
        process.wait()
    except Exception as e:
        print("Error writing video:", e)
        return

    # 2. Write Audio
    with wave.open("temp_audio.wav", 'wb') as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio_data)

    # 3. Mux
    print("Muxing audio and video...")
    cmd_mux = [ffmpeg_cmd, '-y', '-i', 'temp_video.mp4', '-i', 'temp_audio.wav', '-c:v', 'copy', '-c:a', 'aac', 'synth_output.mp4']
    subprocess.run(cmd_mux, startupinfo=startupinfo)
    
    # Cleanup temp files
    try:
        os.remove('temp_video.mp4')
        os.remove('temp_audio.wav')
    except: pass
    print("Saved to synth_output.mp4")

if __name__ == "__main__":
    main()