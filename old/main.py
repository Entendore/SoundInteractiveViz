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

# --- FIXED IMPORTS ---
# QAction and QActionGroup are now in QtGui
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QMenuBar, 
                               QMenu, QMessageBox)
from PySide6.QtCore import Qt, QTimer, QPointF, QRect, QSize
from PySide6.QtGui import (QPainter, QColor, QPen, QBrush, QPolygonF, QImage, 
                           QFont, QKeyEvent, QMouseEvent, QAction, QActionGroup)

# --- Configuration ---
WIDTH, HEIGHT = 950, 700
FPS = 60
SAMPLE_RATE = 44100
BUFFER_SIZE = 512

# --- Helper Functions ---
def get_ffmpeg_exe():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return "ffmpeg"

def note_to_freq(note):
    return 440.0 * (2.0 ** ((note - 69) / 12.0))

# --- Audio Engine Class ---
class SynthEngine:
    def __init__(self):
        self.phase_acc = 0.0
        self.phase_sub = 0.0
        self.phase_fm = 0.0
        self.phase_lfo = 0.0
        self.z = 0.0
        self.current_amp = 0.0

    def get_chunk(self, frame_count, params):
        freq = params['freq']
        mod = params['mod']
        preset = params['preset']
        
        t = np.arange(frame_count)
        inc_main = 2 * np.pi * freq / SAMPLE_RATE
        inc_sub = 2 * np.pi * (freq / 2) / SAMPLE_RATE
        inc_lfo = 2 * np.pi * mod / SAMPLE_RATE

        if preset == 0: 
            # AMBIENT
            voices = 5
            detune = 0.15
            wave = np.zeros(frame_count)
            for i in range(voices):
                d = 1.0 + (i - voices//2) * (detune / 100.0)
                wave += 2 * ((self.phase_acc + t * inc_main * d) % (2*np.pi)) / (2*np.pi) - 1
            wave /= voices
            
            sub = np.sin(self.phase_sub + t * inc_sub)
            wave = wave * 0.7 + sub * 0.3
            
            alpha = 0.4
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
            # PSYCHEDELIC
            ratio = 2.0 + mod
            mod_index = 1.0 + (np.sin(self.phase_lfo + t * 0.05) * 0.5)
            mod_sig = np.sin(self.phase_fm + t * inc_main * ratio)
            
            wave_l = np.sin(self.phase_acc + t * inc_main + mod_sig * mod_index * 6.0)
            wave_r = np.sin(self.phase_acc + t * inc_main + mod_sig * mod_index * 6.0 + np.pi/3)
            
            left, right = np.tanh(wave_l * 1.2), np.tanh(wave_r * 1.2)
            self.phase_fm += frame_count * inc_main * ratio

        elif preset == 2:
            # HYPNOTIC
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
            # BINAURAL
            beat_diff = 10
            left = np.sin(self.phase_acc + t * inc_main)
            right = np.sin(self.phase_acc + t * (inc_main + (2 * np.pi * beat_diff / SAMPLE_RATE)))
            
            lfo = 0.7 + 0.3 * np.sin(self.phase_lfo + t * inc_lfo)
            left *= lfo
            right *= lfo

        if preset != 2:
            self.phase_lfo += frame_count * inc_lfo * 0.1
            
        self.phase_acc += frame_count * inc_main
        self.phase_sub += frame_count * inc_sub

        left = np.tanh(left * 0.8)
        right = np.tanh(right * 0.8)
        
        self.current_amp = np.sqrt(np.mean(left**2 + right**2))
        return np.column_stack((left, right))

# --- Main Widget ---
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
        self.SCALE_MODE = 0 # 0: Chromatic (Free), 1: Major, 2: Minor, 3: Pentatonic
        
        # Settings Data
        self.PRESET_NAMES = ["Ambient Pad", "Psychedelic FM", "Rhythmic Gate", "Binaural Focus"]
        self.VISUAL_NAMES = ["Mandala", "Tunnel", "Lissajous", "Particles"]
        self.COLOR_NAMES = ["Rainbow", "Ocean", "Fire", "Neon", "Monochrome"]
        self.SCALE_NAMES = ["Chromatic (Free)", "Major Scale", "Minor Scale", "Pentatonic"]
        
        # Music Theory Data (Semitone intervals from root)
        self.SCALES = {
            0: [], # Chromatic (no snap)
            1: [0, 2, 4, 5, 7, 9, 11], # Major
            2: [0, 2, 3, 5, 7, 8, 10], # Minor
            3: [0, 2, 4, 7, 9]          # Pentatonic
        }
        
        # Input State
        self.keys_held = []
        self.key_map = {
            Qt.Key_A: 60, Qt.Key_W: 61, Qt.Key_S: 62, Qt.Key_E: 63,
            Qt.Key_D: 64, Qt.Key_F: 65, Qt.Key_T: 66, Qt.Key_G: 67,
            Qt.Key_Y: 68, Qt.Key_H: 69, Qt.Key_U: 70, Qt.Key_J: 71,
            Qt.Key_K: 72
        }
        
        # Visual Settings
        self.trail_alpha = 35 # Lower = longer trails
        
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
            h = 0.55 + h * 0.1 # Cyan to Blue range
            s = 0.7
        elif self.COLOR_MODE == 2: # Fire
            h = 0.0 + h * 0.1 # Red to Orange range
            s = 0.9
        elif self.COLOR_MODE == 3: # Neon
            s = 1.0
            v = 1.0
        elif self.COLOR_MODE == 4: # Mono
            s = 0.0
            v = 1.0
        else: # Rainbow
            pass
            
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
        # Screen Painter
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        w, h = self.width(), self.height()
        
        # Draw Visuals
        self.draw_visuals(painter, w, h)
        
        # Draw HUD
        self.draw_hud(painter, w, h)
        
        painter.end()
        
        # Handle Recording
        if self.is_recording:
            self.record_frame()

    def draw_hud(self, painter, w, h):
        # Semi-transparent panel (Minimalist bottom-left)
        panel_rect = QRect(10, h - 110, 220, 100)
        painter.fillRect(panel_rect, QColor(0, 0, 0, 140))
        
        painter.setPen(Qt.white)
        font = QFont("Segoe UI", 10)
        painter.setFont(font)
        
        # Info
        freq = int(self.audio_params['freq'])
        preset_name = self.PRESET_NAMES[self.audio_params['preset']]
        scale_name = self.SCALE_NAMES[self.SCALE_MODE]
        
        texts = [
            f"Sound: {preset_name}",
            f"Scale: {scale_name}",
            f"Visual: {self.VISUAL_NAMES[self.VISUAL_MODE-1]}",
            f"Pitch: {freq} Hz"
        ]
        
        y_offset = h - 95
        for t in texts:
            painter.drawText(20, y_offset, t)
            y_offset += 20
            
        # Recording Indicator
        if self.is_recording:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor(255, 50, 50)))
            painter.drawEllipse(w - 30, 20, 14, 14)
            painter.setPen(Qt.white)
            painter.setFont(QFont("Segoe UI", 10, QFont.Bold))
            painter.drawText(w - 80, 31, "REC")

    def record_frame(self):
        # Determine resolution
        if self.recording_resolution:
            w, h = self.recording_resolution
        else:
            w, h = self.width(), self.height()
            
        # Create Offscreen Image
        rec_img = QImage(w, h, QImage.Format_RGB888)
        rec_img.fill(Qt.black)
        
        painter = QPainter(rec_img)
        painter.setRenderHint(QPainter.Antialiasing)
        self.draw_visuals(painter, w, h)
        painter.end()
        
        # Store Frame
        ptr = rec_img.bits()
        ptr.setsize(rec_img.sizeInBytes())
        self.video_frames.append(bytes(ptr))

    # --- Input Handling ---
    
    def quantize_freq(self, freq):
        if self.SCALE_MODE == 0: return freq # Chromatic
        
        # Calculate nearest note
        note = 12 * math.log2(freq / 440.0) + 69
        base_note = int(note)
        
        # Find closest note in scale
        scale_intervals = self.SCALES[self.SCALE_MODE]
        octave = base_note // 12
        note_in_octave = base_note % 12
        
        # Find closest interval
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

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Synth Studio Pro")
        self.synth_widget = SynthWidget()
        self.setCentralWidget(self.synth_widget)
        
        self.setStyleSheet("""
            QMainWindow { background-color: #1e1e1e; }
            QMenuBar {
                background-color: #2d2d2d; 
                color: #cccccc; 
                border-bottom: 1px solid #444;
                padding: 4px;
            }
            QMenuBar::item {
                background-color: transparent; 
                padding: 5px 10px; 
                border-radius: 4px;
            }
            QMenuBar::item:selected { background-color: #3d3d3d; }
            QMenu {
                background-color: #2d2d2d; 
                color: #cccccc; 
                border: 1px solid #444;
            }
            QMenu::item { padding: 5px 25px 5px 20px; }
            QMenu::item:selected { background-color: #0078d7; }
        """)
        
        self.create_menus()

    def create_menus(self):
        bar = self.menuBar()
        
        # 1. File
        file_menu = bar.addMenu("File")
        
        fullscreen_act = QAction("Fullscreen", self)
        fullscreen_act.setShortcut("F11")
        fullscreen_act.triggered.connect(lambda: self.showFullScreen() if not self.isFullScreen() else self.showNormal())
        file_menu.addAction(fullscreen_act)
        
        exit_act = QAction("Exit", self)
        exit_act.setShortcut("Ctrl+Q")
        exit_act.triggered.connect(self.close)
        file_menu.addAction(exit_act)
        
        # 2. Sound
        sound_menu = bar.addMenu("Sound")
        
        synth_menu = sound_menu.addMenu("Synthesizer")
        self.create_checkable_menu(synth_menu, self.synth_widget.PRESET_NAMES, 
                                   self.synth_widget.set_preset, 0)
                                   
        scale_menu = sound_menu.addMenu("Musical Scale")
        self.create_checkable_menu(scale_menu, self.synth_widget.SCALE_NAMES, 
                                   self.synth_widget.set_scale, 0)
        
        # 3. Visuals
        visual_menu = bar.addMenu("Visuals")
        
        mode_menu = visual_menu.addMenu("Visual Mode")
        self.create_checkable_menu(mode_menu, self.synth_widget.VISUAL_NAMES, 
                                   self.synth_widget.set_visual, 0)
                                   
        color_menu = visual_menu.addMenu("Color Theme")
        self.create_checkable_menu(color_menu, self.synth_widget.COLOR_NAMES, 
                                   self.synth_widget.set_color, 0)
                                   
        trail_menu = visual_menu.addMenu("Trail Effect")
        trail_options = [("Long", 15), ("Medium", 35), ("Short", 80)]
        self.create_checkable_menu(trail_menu, [x[0] for x in trail_options], 
                                   lambda idx: self.synth_widget.set_trail(trail_options[idx][1]), 1)
        
        # 4. Record
        record_menu = bar.addMenu("Record")
        
        rec_start = QAction("Start Recording", self)
        rec_start.triggered.connect(self.synth_widget.start_recording)
        record_menu.addAction(rec_start)
        
        rec_stop = QAction("Stop Recording", self)
        rec_stop.triggered.connect(self.synth_widget.stop_recording)
        record_menu.addAction(rec_stop)
        
        record_menu.addSeparator()
        
        res_menu = record_menu.addMenu("Resolution")
        res_options = [("Window Size", None), ("720p", (1280, 720)), ("1080p", (1920, 1080))]
        self.create_checkable_menu(res_menu, [x[0] for x in res_options], 
                                   lambda idx: self.synth_widget.set_rec_resolution(res_options[idx][1]), 0)
        
        dur_menu = record_menu.addMenu("Duration")
        dur_options = [("Manual", 0), ("5 sec", 5), ("10 sec", 10), ("30 sec", 30)]
        self.create_checkable_menu(dur_menu, [x[0] for x in dur_options], 
                                   lambda idx: self.synth_widget.set_rec_duration(dur_options[idx][1]), 0)

        # 5. Help
        settings_menu = bar.addMenu("Help")
        controls_act = QAction("Controls", self)
        controls_act.triggered.connect(self.show_controls)
        settings_menu.addAction(controls_act)

    def create_checkable_menu(self, menu, items, callback, default_index):
        group = QActionGroup(self)
        group.setExclusive(True)
        
        for i, name in enumerate(items):
            act = QAction(name, self, checkable=True)
            act.setChecked(i == default_index)
            # Use lambda default argument capture for idx
            act.triggered.connect(lambda checked, idx=i: callback(idx))
            group.addAction(act)
            menu.addAction(act)

    def show_controls(self):
        QMessageBox.information(self, "Keyboard Controls",
            "<b>General:</b><br>"
            "ESC: Exit<br>"
            "F11: Fullscreen<br><br>"
            "<b>Mouse:</b><br>"
            "X-Axis: Pitch (Snaps to Scale)<br>"
            "Y-Axis: Modulation<br><br>"
            "<b>Piano Keys:</b><br>"
            "A, W, S, E, D, F, T, G, Y, H, U, J, K<br><br>"
            "<b>Recording:</b><br>"
            "SPACE: Toggle Record"
        )

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())