import numpy as np
from config import SAMPLE_RATE

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