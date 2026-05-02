from PySide6.QtWidgets import QMainWindow, QMenuBar, QMenu, QMessageBox
# QAction and QActionGroup are in QtGui for PySide6 (Qt6)
from PySide6.QtGui import QAction, QActionGroup, QFont

from widget import SynthWidget
from config import (PRESET_NAMES, VISUAL_NAMES, COLOR_NAMES, SCALE_NAMES,
                   TRAIL_OPTIONS, RES_OPTIONS, DUR_OPTIONS)

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
        self.create_checkable_menu(synth_menu, PRESET_NAMES, 
                                   self.synth_widget.set_preset, 0)
                                   
        scale_menu = sound_menu.addMenu("Musical Scale")
        self.create_checkable_menu(scale_menu, SCALE_NAMES, 
                                   self.synth_widget.set_scale, 0)
        
        # 3. Visuals
        visual_menu = bar.addMenu("Visuals")
        
        mode_menu = visual_menu.addMenu("Visual Mode")
        self.create_checkable_menu(mode_menu, VISUAL_NAMES, 
                                   self.synth_widget.set_visual, 0)
                                   
        color_menu = visual_menu.addMenu("Color Theme")
        self.create_checkable_menu(color_menu, COLOR_NAMES, 
                                   self.synth_widget.set_color, 0)
                                   
        trail_menu = visual_menu.addMenu("Trail Effect")
        self.create_checkable_menu(trail_menu, [x[0] for x in TRAIL_OPTIONS], 
                                   lambda idx: self.synth_widget.set_trail(TRAIL_OPTIONS[idx][1]), 1)
        
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
        self.create_checkable_menu(res_menu, [x[0] for x in RES_OPTIONS], 
                                   lambda idx: self.synth_widget.set_rec_resolution(RES_OPTIONS[idx][1]), 0)
        
        dur_menu = record_menu.addMenu("Duration")
        self.create_checkable_menu(dur_menu, [x[0] for x in DUR_OPTIONS], 
                                   lambda idx: self.synth_widget.set_rec_duration(DUR_OPTIONS[idx][1]), 0)

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