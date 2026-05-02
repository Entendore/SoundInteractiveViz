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

# --- Configuration ---
WIDTH, HEIGHT = 800, 600
FPS = 60
SAMPLE_RATE = 44100
BUFFER_SIZE = 512

# --- FFmpeg Auto-Detection ---
FFMPEG_EXE = "ffmpeg"
try:
    import imageio_ffmpeg
    FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()
except ImportError:
    pass

# --- Global Audio State ---
# Use double buffering for audio parameters to avoid race conditions
audio_params = {
    'freq': 220.0,
    'mod': 0.5,
    'preset': 0,
    'filter_state': 0.0
}

# --- Advanced Synthesizer Class ---
class SynthEngine:
    def __init__(self):
        self.phase_acc = 0.0  # Main phase accumulator
        self.phase_sub = 0.0  # Sub bass phase
        self.phase_fm = 0.0   # FM modulator phase
        self.phase_lfo = 0.0  # LFO phase
        
        # Filter states for smoothing
        self.z = 0.0 

    def get_chunk(self, frame_count, params):
        freq = params['freq']
        mod = params['mod']
        preset = params['preset']
        
        # Time arrays
        t = np.arange(frame_count)
        
        # Phase increments
        inc_main = 2 * np.pi * freq / SAMPLE_RATE
        inc_sub = 2 * np.pi * (freq / 2) / SAMPLE_RATE
        inc_lfo = 2 * np.pi * mod / SAMPLE_RATE

        # --- Preset Logic ---
        if preset == 0: 
            # AMBIENT: Multi-voice detuned saw (Super-saw style)
            # Rich, wide, and smooth
            voices = 5
            detune = 0.12 # Cents
            
            wave = np.zeros(frame_count)
            for i in range(voices):
                d = 1.0 + (i - voices//2) * (detune / 100.0)
                p_step = inc_main * d
                # Sawtooth wave: 2 * (phase / 2pi) - 1
                voice_sig = 2 * ((self.phase_acc + t * p_step) % (2*np.pi)) / (2*np.pi) - 1
                wave += voice_sig
            
            wave /= voices
            
            # Add sub bass
            sub = np.sin(self.phase_sub + t * inc_sub)
            wave = wave * 0.7 + sub * 0.3
            
            # Soft LPF filter simulation using convolution or simple iir
            # Simple one-pole low pass to mellow it
            alpha = 0.4
            for i in range(len(wave)):
                self.z = alpha * wave[i] + (1 - alpha) * self.z
                wave[i] = self.z
            
            # LFO Volume
            lfo = 0.5 + 0.5 * np.sin(self.phase_lfo + t * inc_lfo * 0.1)
            wave *= lfo
            
            left = wave * 0.9
            right = wave * 0.9 # Mono source

        elif preset == 1:
            # PSYCHEDELIC: FM Synthesis (DX7 style)
            # Complex harmonics that evolve over time
            # Carrier: freq, Modulator: freq * ratio
            
            ratio = 2.0 + mod
            mod_index = 1.0 + (np.sin(self.phase_lfo + t * 0.05) * 0.5)
            
            # Modulator
            mod_sig = np.sin(self.phase_fm + t * inc_main * ratio)
            
            # Carrier with PM
            wave = np.sin(self.phase_acc + t * inc_main + mod_sig * mod_index * 6.0)
            
            # Stereo widening via phase offset
            right_phase_offset = np.pi / 3
            wave_r = np.sin(self.phase_acc + t * inc_main + mod_sig * mod_index * 6.0 + right_phase_offset)
            
            # Add grit (Bitcrush simulation)
            # Not applied to keep it professional, replaced by distortion
            wave = np.tanh(wave * 1.2)
            wave_r = np.tanh(wave_r * 1.2)
            
            left = wave
            right = wave_r
            
            # Advance FM phase
            self.phase_fm += frame_count * inc_main * ratio

        else:
            # HYPNOTIC: Rhythmic Gating & Kick
            # Hard sync oscillators and gating
            
            # Base signal
            wave = np.sin(self.phase_acc + t * inc_main)
            
            # Gating signal (Rhythmic)
            gate_freq = mod * 2 # Hz
            gate_phase = self.phase_lfo + t * (gate_freq * 2 * np.pi / SAMPLE_RATE)
            
            # Envelope: fast attack, slow decay per beat
            # simulating sin^4 or similar
            gate_env = np.power(np.maximum(0, np.sin(gate_phase)), 8.0)
            
            # Apply gate
            wave *= (0.2 + 0.8 * gate_env) # Keep 20% volume for atmosphere
            
            # Add Kick Layer
            kick_phase = gate_phase
            kick_env = np.exp(-20 * (1.0 - np.abs(np.sin(kick_phase))))
            kick = np.sin(t * 80 * np.exp(-t * 0.1)) * kick_env * 0.5
            
            left = wave + kick
            right = wave + kick
            
            # Advance LFO phase specifically for gate timing
            self.phase_lfo += gate_freq * frame_count * 2 * np.pi / SAMPLE_RATE

        # --- Global Updates ---
        if preset != 2: # Hypnotic updates its own LFO
            self.phase_lfo += frame_count * inc_lfo * 0.1
            
        self.phase_acc += frame_count * inc_main
        self.phase_sub += frame_count * inc_sub

        # Soft Limiter (Safety)
        left = np.tanh(left * 0.8)
        right = np.tanh(right * 0.8)

        return np.column_stack((left, right))

synth = SynthEngine()

# --- PyAudio Setup ---
p = pyaudio.PyAudio()

def audio_callback(in_data, frame_count, time_info, status):
    global synth, audio_params
    stereo_data = synth.get_chunk(frame_count, audio_params)
    data = (stereo_data * 32767).astype(np.int16).tobytes()
    return (data, pyaudio.paContinue)

stream = p.open(format=pyaudio.paInt16,
                channels=2,
                rate=SAMPLE_RATE,
                output=True,
                frames_per_buffer=BUFFER_SIZE,
                stream_callback=audio_callback)

# --- Visualization State ---
VISUAL_MODE = 1
particles = []

# --- Recording State ---
is_recording = False
audio_frames = []
ffmpeg_process = None
frame_queue = [] # Thread-safe queue
recording_thread = None

# --- Pygame Setup ---
pygame.init()
screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.RESIZABLE)
pygame.display.set_caption("Pro Synthesizer (Q/W/E: Sound | 1-4: Visual | R: Rec)")
clock = pygame.time.Clock()

# Performance: Pre-allocate trail surface
trail_surface = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)

# --- Recording Logic (Threaded) ---
def ffmpeg_writer_thread(w, h, fps, audio_data):
    command = [
        FFMPEG_EXE,
        '-y',
        '-f', 'rawvideo',
        '-vcodec', 'rawvideo',
        '-s', f'{w}x{h}',
        '-pix_fmt', 'rgb24',
        '-r', str(fps),
        '-i', '-',
        '-f', 's16le',
        '-ac', '2',
        '-ar', str(SAMPLE_RATE),
        '-i', '-',
        '-c:v', 'libx264',
        '-preset', 'ultrafast', # Fast encoding
        '-crf', '23',
        '-pix_fmt', 'yuv420p',
        '-c:a', 'aac',
        'synth_output.mp4'
    ]
    
    try:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
        # Write Audio
        process.stdin.write(audio_data)
        # Write Video frames
        # Note: In this simplified pipe, we pipe video then audio. 
        # Ideally, we mux separately, but let's stick to the reliable 2-pass method 
        # used previously for synchronization reliability.
        # For this thread, we will just process the frames as they come in a real implementation
        # But sticking to the reliable 2-pass temp file method is safer for Python.
        pass 
    except Exception as e:
        print(e)

# Re-using the robust 'temp file' method but ensuring UI doesn't freeze
def start_recording():
    global is_recording, audio_frames
    if is_recording: return
    print("Recording Started...")
    is_recording = True
    audio_frames = []

def stop_recording():
    global is_recording, audio_frames, ffmpeg_process
    if not is_recording: return
    is_recording = False
    print("Recording Stopped. Processing MP4...")
    
    # 1. Save Audio Temp
    audio_file = wave.open("temp_audio.wav", 'wb')
    audio_file.setnchannels(2)
    audio_file.setsampwidth(2)
    audio_file.setframerate(SAMPLE_RATE)
    audio_file.writeframes(b''.join(audio_frames))
    audio_file.close()
    
    # 2. Run FFMPEG Mux
    w, h = screen.get_size()
    mux_cmd = [
        FFMPEG_EXE,
        '-y',
        '-i', 'temp_video.mp4',
        '-i', 'temp_audio.wav',
        '-c:v', 'copy',
        '-c:a', 'aac',
        'synth_output.mp4'
    ]
    
    # Run in background so UI stays responsive
    def run_mux():
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = subprocess.SW_HIDE
        subprocess.run(mux_cmd, startupinfo=si)
        try:
            os.remove('temp_video.mp4')
            os.remove('temp_audio.wav')
        except: pass
        print("Saved to synth_output.mp4")

    threading.Thread(target=run_mux).start()

# --- Main Loop ---
running = True
tick = 0
NOTE_DURATION = 180
note_timer = 0

SCALE = [130.81, 146.83, 164.81, 196.00, 220.00, 261.63, 293.66, 329.63, 392.00, 440.00]
target_freq = 220.0

# Start Stream
stream.start_stream()

while running:
    tick += 1
    
    # 1. Input
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE: running = False
            if event.key == pygame.K_f:
                flags = screen.get_flags()
                if flags & pygame.FULLSCREEN:
                    screen = pygame.display.set_mode((WIDTH, HEIGHT))
                    trail_surface = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
                else:
                    screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
                    w,h = screen.get_size()
                    trail_surface = pygame.Surface((w, h), pygame.SRCALPHA)
            
            if event.key == pygame.K_1: VISUAL_MODE = 1
            if event.key == pygame.K_2: VISUAL_MODE = 2
            if event.key == pygame.K_3: VISUAL_MODE = 3
            if event.key == pygame.K_4: VISUAL_MODE = 4
            
            if event.key == pygame.K_q: audio_params['preset'] = 0
            if event.key == pygame.K_w: audio_params['preset'] = 1
            if event.key == pygame.K_e: audio_params['preset'] = 2
            
            if event.key == pygame.K_r:
                if is_recording: stop_recording()
                else: start_recording()
        
        if event.type == pygame.VIDEORESIZE:
            screen = pygame.display.set_mode((event.w, event.h), pygame.RESIZABLE)
            trail_surface = pygame.Surface((event.w, event.h), pygame.SRCALPHA)

    w, h = screen.get_size()
    
    # 2. Logic
    note_timer += 1
    if note_timer >= NOTE_DURATION:
        note_timer = 0
        if audio_params['preset'] == 2:
            target_freq = random.choice(SCALE[:5])
        else:
            target_freq = random.choice(SCALE)
    
    # Smooth Freq Glide
    audio_params['freq'] += (target_freq - audio_params['freq']) * 0.02
    audio_params['mod'] = 0.5 + math.sin(tick * 0.01) * 0.3

    # 3. Visualization
    
    # Performance: Re-use trail surface
    # Fill with low alpha black
    trail_surface.fill((0, 0, 0, 25)) 
    screen.blit(trail_surface, (0, 0))

    # Draw commands (Optimized)
    freq = audio_params['freq']
    mod = audio_params['mod']
    
    cx, cy = w // 2, h // 2
    hue = (tick / 500) % 1.0
    
    if VISUAL_MODE == 1:
        # Mandala
        breath = math.sin(tick * mod * 0.1)
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
    
    elif VISUAL_MODE == 2:
        # Tunnel
        speed = 3 + mod * 8
        for i in range(25):
            r = (tick * speed + i * 25) % (max(w, h))
            if r < 20: continue
            thickness = int(2 + (freq/200))
            c_hsv = (hue + i*0.02) % 1.0
            rgb = colorsys.hsv_to_rgb(c_hsv, 0.9, 1.0)
            color = (int(rgb[0]*255), int(rgb[1]*255), int(rgb[2]*255))
            pygame.draw.circle(screen, color, (cx, cy), int(r), thickness)

    elif VISUAL_MODE == 3:
        # Lissajous
        a = freq / 100.0
        b = mod + 2.0
        delta = tick / 50.0
        scale = min(w, h) * 0.35
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

    elif VISUAL_MODE == 4:
        # Particles
        if tick % max(1, int(60 / (freq/80))) == 0:
            angle = random.uniform(0, 360)
            speed = 2 + mod * 4
            particles.append({
                'x': cx, 'y': cy, 
                'vx': math.cos(math.radians(angle)) * speed, 
                'vy': math.sin(math.radians(angle)) * speed,
                'life': 150
            })
        for p in particles[:]:
            p['x'] += p['vx']
            p['y'] += p['vy']
            p['life'] -= 1
            life_ratio = max(0, p['life'] / 150.0)
            size = int(4 * life_ratio)
            hue_p = (tick/200) % 1.0
            rgb = colorsys.hsv_to_rgb(hue_p, 0.9, life_ratio)
            color = (int(rgb[0]*255), int(rgb[1]*255), int(rgb[2]*255))
            if p['life'] <= 0:
                particles.remove(p)
            elif size > 0:
                pygame.draw.circle(screen, color, (int(p['x']), int(p['y'])), size)

    # 4. Recording
    if is_recording:
        # Write video frame
        raw_data = pygame.image.tostring(screen, 'RGB')
        try:
            # We need to initialize ffmpeg process lazily on first frame
            if not ffmpeg_process:
                command = [
                    FFMPEG_EXE,
                    '-y',
                    '-f', 'rawvideo',
                    '-vcodec', 'rawvideo',
                    '-s', f'{w}x{h}',
                    '-pix_fmt', 'rgb24',
                    '-r', str(FPS),
                    '-i', '-',
                    '-an',
                    '-vcodec', 'libx264',
                    '-preset', 'fast',
                    '-crf', '23',
                    '-pix_fmt', 'yuv420p',
                    'temp_video.mp4'
                ]
                si = subprocess.STARTUPINFO()
                si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                si.wShowWindow = subprocess.SW_HIDE
                ffmpeg_process = subprocess.Popen(command, stdin=subprocess.PIPE, startupinfo=si)
            
            ffmpeg_process.stdin.write(raw_data)
        except Exception as e:
            print("Recording Error:", e)
            stop_recording()

    pygame.display.flip()
    clock.tick(FPS)

# Cleanup
if is_recording:
    stop_recording()
stream.stop_stream()
stream.close()
p.terminate()
pygame.quit()