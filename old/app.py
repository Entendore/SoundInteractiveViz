import pygame
import numpy as np
import pyaudio
import colorsys
import math
import struct

# --- Configuration ---
WIDTH, HEIGHT = 800, 600
FPS = 60
SAMPLE_RATE = 44100

# --- Audio Synthesis Setup ---
# We generate sound in real-time based on mouse position
p = pyaudio.PyAudio()

# Define the callback for the audio stream
def audio_callback(in_data, frame_count, time_info, status):
    # Get global variables for synthesis
    global current_freq, current_mod, phase
    
    # Time steps for this chunk of audio
    t = (phase + np.arange(frame_count)) / SAMPLE_RATE
    
    # 1. Binaural Beat Generation (Psychedelic Audio)
    # Left ear hears 'freq', Right ear hears 'freq + beat_diff'
    # 10Hz difference (Alpha waves) is associated with relaxation
    beat_diff = 10 
    left_wave = np.sin(2 * np.pi * current_freq * t)
    right_wave = np.sin(2 * np.pi * (current_freq + beat_diff) * t)
    
    # 2. Add a "Drone" layer for depth (LFO modulation)
    # A low frequency oscillator to wobble the volume
    lfo = np.sin(2 * np.pi * current_mod * t)
    volume = 0.5 + (0.5 * lfo) # Volume oscillates 0.0 to 1.0
    
    # Apply volume to both channels
    left_out = left_wave * volume
    right_out = right_wave * volume
    
    # Interleave left and right channels
    # (L, R, L, R, L, R...)
    stereo_data = np.column_stack((left_out, right_out))
    
    # Update global phase to ensure smooth continuity between chunks
    phase += frame_count
    
    # Convert float data to bytes (16-bit PCM)
    # Pyaudio expects bytes, usually float32 or int16
    data = (stereo_data * 32767).astype(np.int16).tobytes()
    
    return (data, pyaudio.paContinue)

# Open the Output Stream (Speakers)
stream = p.open(format=pyaudio.paInt16,
                channels=2,
                rate=SAMPLE_RATE,
                output=True,
                stream_callback=audio_callback)

# --- Global Synth State ---
current_freq = 110.0   # Base frequency (Hz) - Controlled by Mouse X
current_mod = 0.5      # Tremolo speed (Hz) - Controlled by Mouse Y
phase = 0.0            # Keeps track of time for smooth waves

# --- Pygame Setup ---
pygame.init()
screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.RESIZABLE)
pygame.display.set_caption("Psychedelic Audio-Visual Synthesizer")
clock = pygame.time.Clock()
font = pygame.font.SysFont("Arial", 16)

print("Synthesizer Running.")
print("Move Mouse X to change Pitch.")
print("Move Mouse Y to change Visual Intensity.")
print("Press 'F' for Fullscreen. 'ESC' to Quit.")

# --- Main Loop ---
running = True
tick = 0

stream.start_stream()

while running:
    tick += 1
    
    # 1. Handle Input
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                running = False
            if event.key == pygame.K_f:
                if screen.get_flags() & pygame.FULLSCREEN:
                    screen = pygame.display.set_mode((WIDTH, HEIGHT))
                else:
                    screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)

    # 2. Map Mouse to Synth Parameters
    mx, my = pygame.mouse.get_pos()
    w, h = screen.get_size()
    
    # Map X (0 to Width) -> Frequency (110Hz to 880Hz)
    current_freq = 110 + (mx / w) * 770
    
    # Map Y (0 to Height) -> Modulation Speed (0.1Hz to 5Hz)
    current_mod = 0.1 + (1 - (my / h)) * 4.9 # Inverted Y so top is faster

    # 3. Visualization Logic
    # Create the "Trail" effect for ghosting
    trail_surface = pygame.Surface((w, h))
    trail_surface.set_alpha(25) # Adjust this for longer/shorter trails
    trail_surface.fill((0, 0, 0))
    screen.blit(trail_surface, (0, 0))

    # Center
    cx, cy = w // 2, h // 2

    # Dynamic Variables
    hue = (tick / 500) % 1.0
    # Radius based on the Modulation (Y axis)
    # We simulate the LFO here to sync visuals to audio roughly
    visual_lfo = math.sin(tick * current_mod * 0.1)
    radius = 100 + visual_lfo * 50 * (current_mod * 2) 
    
    # Complexity based on Frequency (X axis)
    num_shapes = int(3 + (current_freq / 100))

    # Draw the Mandala
    for i in range(num_shapes):
        # Rotate each layer
        angle_offset = (tick + i * 10) * (1 + current_mod * 0.5)
        
        # Calculate points for the shape
        points = []
        sides = 6 # Hexagon base
        for s in range(sides):
            angle = math.radians(s * (360/sides) + angle_offset)
            
            # Add "Breathing" distortion
            dist = radius + (i * 10) * visual_lfo
            
            x = cx + dist * math.cos(angle)
            y = cy + dist * math.sin(angle)
            points.append((x, y))

        # Color shifting based on frequency and time
        color_hsv = (hue + i*0.05) % 1.0
        rgb = colorsys.hsv_to_rgb(color_hsv, 0.8, 1)
        color = (int(rgb[0]*255), int(rgb[1]*255), int(rgb[2]*255))

        if len(points) > 2:
            pygame.draw.polygon(screen, color, points, 2)

    # Draw Center Core
    pygame.draw.circle(screen, (255, 255, 255), (cx, cy), int(10 + radius/10))

    # Display Info
    freq_text = f"Freq: {int(current_freq)} Hz | Mod: {current_mod:.2f} Hz"
    text_surf = font.render(freq_text, True, (200, 200, 200))
    screen.blit(text_surf, (10, 10))

    pygame.display.flip()
    clock.tick(FPS)

# --- Cleanup ---
stream.stop_stream()
stream.close()
p.terminate()
pygame.quit()