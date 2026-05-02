import sys
import math
import numpy as np
import pyaudio
import colorsys
import random
import subprocess
import os
import threading
import wave

from PySide6.QtWidgets import QWidget, QMessageBox
from PySide6.QtCore import Qt, QTimer, QPointF, QRect
from PySide6.QtGui import (QPainter, QColor, QPen, QBrush, QPolygonF, QImage, 
                           QFont, QKeyEvent, QMouseEvent)

from config import (WIDTH, HEIGHT, FPS, SAMPLE_RATE, BUFFER_SIZE, 
                   PRESET_NAMES, VISUAL_NAMES, COLOR_NAMES, SCALE_NAMES, SCALES)
from engine import SynthEngine
from utils import get_ffmpeg_exe, note_to_freq

class SynthWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(WIDTH, HEIGHT)
        
        # State
        self.audio_params = {'freq': 220.0, 'mod': 0.5, 'preset': 0}
        self.target_freq = 220.0
        self.particles = []
        self.tick = 0
        
        # Modes
        self.VISUAL_MODE = 1
        self.COLOR_MODE = 0
        self.SCALE_MODE = 0 
        
        # Input State
        self.keys_held = []
        self.key_map = {
            Qt.Key_A: 60, Qt.Key_W: 61, Qt.Key_S: 62, Qt.Key_E: 63,
            Qt.Key_D: 64, Qt.Key_F: 65, Qt.Key_T: 66, Qt.Key_G: 67,
            Qt.Key_Y: 68, Qt.Key_H: 69, Qt.Key_U: 70, Qt.Key_J: 71,
            Qt.Key_K: 72
        }
        
        # Visual Settings
        self.trail_alpha = 35 
        
        # Recording State
        self.is_recording = False
        self.video_frames = []
        self.audio_frames = []
        self.recording_duration = 0 
        self.recording_resolution = None 
        
        # Audio Setup
        self.p = pyaudio.PyAudio()
        self.synth = SynthEngine()
        
        def audio_callback(in_data, frame_count, time_info, status):
            stereo_data = self.synth.get_chunk(frame_count, self.audio_params)
            data = (stereo_data * 32767).astype(np.int16).tobytes()
            if self.is_recording:
                self.audio_frames.append(data)
            return (data, pyaudio.paContinue)

        self.stream = self.p.open(format=pyaudio.paInt16,
                        channels=2,
                        rate=SAMPLE_RATE,
                        output=True,
                        frames_per_buffer=BUFFER_SIZE,
                        stream_callback=audio_callback)
        self.stream.start_stream()
        
        # Timer
        self.timer = QTimer()
        self.timer.timeout.connect(self.loop)
        self.timer.start(int(1000/FPS))
        
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

    def loop(self):
        self.tick += 1
        if self.keys_held:
            midi_note = self.key_map[self.keys_held[-1]]
            self.target_freq = note_to_freq(midi_note)
        
        # Smooth frequency transition
        self.audio_params['freq'] += (self.target_freq - self.audio_params['freq']) * 0.1
        self.update()

    # --- Unified Drawing Logic ---
    def get_color(self, hue_offset, saturation=0.8, value=1.0):
        h = (self.tick / 500 + hue_offset) % 1.0
        
        if self.COLOR_MODE == 1: # Ocean
            h = 0.55 + h * 0.1 
            s = 0.7
        elif self.COLOR_MODE == 2: # Fire
            h = 0.0 + h * 0.1 
            s = 0.9
        elif self.COLOR_MODE == 3: # Neon
            s = 1.0
            v = 1.0
        elif self.COLOR_MODE == 4: # Mono
            s = 0.0
            v = 1.0
            
        return QColor.fromHsvF(h, saturation, value)

    def draw_visuals(self, painter, w, h):
        freq = self.audio_params['freq']
        mod = self.audio_params['mod']
        amp = self.synth.current_amp
        
        cx, cy = w // 2, h // 2
        
        # Background Fade (Trail)
        painter.fillRect(0, 0, w, h, QColor(0, 0, 0, self.trail_alpha))

        if self.VISUAL_MODE == 1:
            # Mandala
            breath = math.sin(self.tick * mod * 0.1) + amp * 2.0
            radius = 100 + breath * 50 * (mod * 2)
            num_layers = int(3 + (freq / 150))
            
            for i in range(num_layers):
                rot_speed = 1 + mod * 0.5
                angle_offset = (self.tick + i * 15) * rot_speed
                points = []
                sides = 6
                for s in range(sides):
                    angle = math.radians(s * (360/sides) + angle_offset)
                    dist = radius + (i * 20) * breath
                    points.append(QPointF(cx + dist * math.cos(angle), cy + dist * math.sin(angle)))
                
                poly = QPolygonF(points)
                color = self.get_color(i*0.03)
                painter.setPen(QPen(color, 2))
                painter.setBrush(Qt.NoBrush)
                painter.drawPolygon(poly)
            
            painter.setBrush(QBrush(Qt.white))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QPointF(cx, cy), int(10 + radius/10), int(10 + radius/10))

        elif self.VISUAL_MODE == 2:
            # Tunnel
            speed = 3 + mod * 8 + amp * 4
            max_dim = max(w, h)
            for i in range(30):
                r = (self.tick * speed + i * 25) % max_dim
                if r < 20: continue
                thickness = int(2 + (freq/200) + amp * 5)
                color = self.get_color(i*0.02)
                painter.setPen(QPen(color, thickness))
                painter.drawEllipse(QPointF(cx, cy), int(r), int(r))

        elif self.VISUAL_MODE == 3:
            # Lissajous
            a = freq / 100.0
            b = mod + 2.0
            delta = self.tick / 50.0
            scale = min(w, h) * 0.35 * (0.8 + amp * 0.4)
            
            path_points = []
            for t_step in range(500):
                t_val = t_step / 10.0
                x = math.sin(a * t_val + delta)
                y = math.sin(b * t_val)
                path_points.append(QPointF(cx + x * scale, cy + y * scale))
            
            for i in range(1, len(path_points)):
                hue = i / 500 + self.tick/200
                color = self.get_color(hue)
                painter.setPen(QPen(color, 2))
                painter.drawLine(path_points[i-1], path_points[i])

        elif self.VISUAL_MODE == 4:
            # Particles
            spawn_rate = max(1, int(30 / (freq/80)))
            if self.tick % spawn_rate == 0:
                count = int(1 + amp * 5)
                for _ in range(count):
                    angle = random.uniform(0, 360)
                    speed = 2 + mod * 4
                    self.particles.append({
                        'x': cx, 'y': cy,
                        'vx': math.cos(math.radians(angle)) * speed,
                        'vy': math.sin(math.radians(angle)) * speed,
                        'life': 150
                    })
            
            new_particles = []
            painter.setPen(Qt.NoPen)
            for p in self.particles:
                p['x'] += p['vx']
                p['y'] += p['vy']
                p['life'] -= 1
                if p['life'] > 0:
                    life_ratio = p['life'] / 150.0
                    size = int(4 * life_ratio)
                    color = self.get_color(self.tick/200, 0.9, life_ratio)
                    painter.setBrush(QBrush(color))
                    painter.drawEllipse(QPointF(p['x'], p['y']), size, size)
                    new_particles.append(p)
            self.particles = new_particles

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        w, h = self.width(), self.height()
        
        self.draw_visuals(painter, w, h)
        self.draw_hud(painter, w, h)
        
        painter.end()
        
        if self.is_recording:
            self.record_frame()

    def draw_hud(self, painter, w, h):
        panel_rect = QRect(10, h - 110, 220, 100)
        painter.fillRect(panel_rect, QColor(0, 0, 0, 140))
        
        painter.setPen(Qt.white)
        font = QFont("Segoe UI", 10)
        painter.setFont(font)
        
        freq = int(self.audio_params['freq'])
        preset_name = PRESET_NAMES[self.audio_params['preset']]
        scale_name = SCALE_NAMES[self.SCALE_MODE]
        
        texts = [
            f"Sound: {preset_name}",
            f"Scale: {scale_name}",
            f"Visual: {VISUAL_NAMES[self.VISUAL_MODE-1]}",
            f"Pitch: {freq} Hz"
        ]
        
        y_offset = h - 95
        for t in texts:
            painter.drawText(20, y_offset, t)
            y_offset += 20
            
        if self.is_recording:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor(255, 50, 50)))
            painter.drawEllipse(w - 30, 20, 14, 14)
            painter.setPen(Qt.white)
            painter.setFont(QFont("Segoe UI", 10, QFont.Bold))
            painter.drawText(w - 80, 31, "REC")

    def record_frame(self):
        if self.recording_resolution:
            w, h = self.recording_resolution
        else:
            w, h = self.width(), self.height()
            
        rec_img = QImage(w, h, QImage.Format_RGB888)
        rec_img.fill(Qt.black)
        
        painter = QPainter(rec_img)
        painter.setRenderHint(QPainter.Antialiasing)
        self.draw_visuals(painter, w, h)
        painter.end()
        
        ptr = rec_img.bits()
        ptr.setsize(rec_img.sizeInBytes())
        self.video_frames.append(bytes(ptr))

    # --- Input Handling ---
    
    def quantize_freq(self, freq):
        if self.SCALE_MODE == 0: return freq
        
        note = 12 * math.log2(freq / 440.0) + 69
        base_note = int(note)
        
        scale_intervals = SCALES[self.SCALE_MODE]
        octave = base_note // 12
        note_in_octave = base_note % 12
        
        closest_dist = 12
        closest_interval = 0
        
        for interval in scale_intervals:
            d = abs(note_in_octave - interval)
            if d < closest_dist:
                closest_dist = d
                closest_interval = interval
        
        target_note = (octave * 12) + closest_interval
        return note_to_freq(target_note)

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        if key == Qt.Key_Escape:
            self.close()
        
        if key == Qt.Key_Space:
            if self.is_recording: self.stop_recording()
            else: self.start_recording()
            
        if key in self.key_map:
            if key not in self.keys_held:
                self.keys_held.append(key)

    def keyReleaseEvent(self, event: QKeyEvent):
        key = event.key()
        if key in self.key_map:
            if key in self.keys_held:
                self.keys_held.remove(key)

    def mouseMoveEvent(self, event: QMouseEvent):
        w, h = self.width(), self.height()
        mx, my = event.position().x(), event.position().y()
        
        if not self.keys_held:
            raw_freq = 110 + (mx / w) * 770
            self.target_freq = self.quantize_freq(raw_freq)
            
        self.audio_params['mod'] = 0.1 + (1 - (my / h)) * 4.9
    
    # --- Actions ---
    def set_preset(self, index):
        self.audio_params['preset'] = index
        
    def set_visual(self, index):
        self.VISUAL_MODE = index
        
    def set_color(self, index):
        self.COLOR_MODE = index
        
    def set_scale(self, index):
        self.SCALE_MODE = index
        
    def set_trail(self, alpha):
        self.trail_alpha = alpha

    def set_rec_duration(self, sec):
        self.recording_duration = sec

    def set_rec_resolution(self, res):
        self.recording_resolution = res

    def start_recording(self):
        if not self.is_recording:
            print("Recording Started...")
            self.is_recording = True
            self.video_frames = []
            self.audio_frames = []
            
            if self.recording_duration > 0:
                QTimer.singleShot(int(self.recording_duration * 1000), self.stop_recording)

    def stop_recording(self):
        if self.is_recording:
            print("Recording Stopped. Saving...")
            self.is_recording = False
            threading.Thread(target=self.save_recording, daemon=True).start()

    def save_recording(self):
        frames = self.video_frames
        audio_data = b''.join(self.audio_frames)
        
        if not frames: return
        
        if self.recording_resolution:
            w, h = self.recording_resolution
        else:
            w, h = self.width(), self.height()
            
        print(f"Processing {len(frames)} frames at {w}x{h}...")
        
        ffmpeg_exe = get_ffmpeg_exe()
        
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        cmd_vid = [
            ffmpeg_exe, '-y',
            '-f', 'rawvideo',
            '-vcodec', 'rawvideo',
            '-s', f'{w}x{h}',
            '-pix_fmt', 'rgb24',
            '-r', str(FPS),
            '-i', '-',
            '-c:v', 'libx264',
            '-preset', 'medium',
            '-crf', '23',
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

        with wave.open("temp_audio.wav", 'wb') as wf:
            wf.setnchannels(2)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(audio_data)

        cmd_mux = [ffmpeg_exe, '-y', '-i', 'temp_video.mp4', '-i', 'temp_audio.wav', 
                   '-c:v', 'copy', '-c:a', 'aac', '-shortest', 'synth_output.mp4']
        subprocess.run(cmd_mux, startupinfo=startupinfo)
        
        try:
            os.remove('temp_video.mp4')
            os.remove('temp_audio.wav')
        except: pass
        print("Saved to synth_output.mp4")

    def closeEvent(self, event):
        self.stream.stop_stream()
        self.stream.close()
        self.p.terminate()
        event.accept()