import os
import sys
import math
import torch
import parselmouth

import numba as nb
import numpy as np

from librosa import yin, pyin
from scipy.signal import medfilt

sys.path.append(os.getcwd())

from modules.rmvpe import RMVPE
from modules.utils import Autotune
from modules.torchfcpe import FCPE
from modules.pyworld import PYWORLD
from modules.swipe import swipe, stonemask
from modules.torchcrepe import CREPE, mean, median

@nb.jit(nopython=True)
def post_process(f0, f0_up_key, f0_mel_min, f0_mel_max):
    f0 = np.multiply(f0, pow(2, f0_up_key / 12))

    f0_mel = 1127 * np.log(1 + f0 / 700)
    f0_mel[f0_mel > 0] = (f0_mel[f0_mel > 0] - f0_mel_min) * 254 / (f0_mel_max - f0_mel_min) + 1
    f0_mel[f0_mel <= 1] = 1
    f0_mel[f0_mel > 255] = 255

    return np.rint(f0_mel).astype(np.int32), f0

class Generator:
    def __init__(self, sample_rate = 16000, hop_length = 160, f0_min = 50, f0_max = 1100, is_half = False, device = "cpu"):
        self.sample_rate = sample_rate
        self.hop_length = hop_length
        self.f0_min = f0_min
        self.f0_max = f0_max
        self.is_half = is_half
        self.device = device
        self.window = 160
        self.ref_freqs = [49.00, 51.91, 55.00, 58.27, 61.74, 65.41, 69.30, 73.42, 77.78, 82.41, 87.31, 92.50, 98.00, 103.83, 110.00, 116.54, 123.47, 130.81, 138.59, 146.83, 155.56, 164.81, 174.61, 185.00, 196.00,  207.65, 220.00, 233.08, 246.94, 261.63, 277.18, 293.66, 311.13, 329.63, 349.23, 369.99, 392.00, 415.30, 440.00, 466.16, 493.88, 523.25, 554.37, 587.33, 622.25, 659.25, 698.46, 739.99, 783.99, 830.61, 880.00, 932.33, 987.77, 1046.50]
        self.autotune = Autotune(self.ref_freqs)
        self.note_dict = self.autotune.note_dict

    def calculator(self, f0_method, x, f0_up_key = 0, p_len = None, filter_radius = 3, f0_autotune = False, f0_autotune_strength = 1):
        if p_len is None: p_len = x.shape[0] // self.window
        f0 = self.compute_f0(f0_method, x, p_len, filter_radius if filter_radius % 2 != 0 else filter_radius + 1)

        if isinstance(f0, tuple): f0 = f0[0]
        if f0_autotune: f0 = Autotune.autotune_f0(self, f0, f0_autotune_strength)

        return post_process(
            f0, 
            f0_up_key, 
            1127 * math.log(1 + self.f0_min / 700), 
            1127 * math.log(1 + self.f0_max / 700), 
        )

    def _resize_f0(self, x, target_len):
        source = np.array(x)
        source[source < 0.001] = np.nan

        return np.nan_to_num(
            np.interp(
                np.arange(0, len(source) * target_len, len(source)) / target_len, 
                np.arange(0, len(source)), 
                source
            )
        )
    
    def compute_f0(self, f0_method, x, p_len, filter_radius):
        return {
            "pm": lambda: self.get_f0_pm(x, p_len), 
            "dio": lambda: self.get_f0_pyworld(x, p_len, filter_radius, "dio"), 
            "mangio-crepe-tiny": lambda: self.get_f0_mangio_crepe(x, p_len, "tiny"), 
            "mangio-crepe-small": lambda: self.get_f0_mangio_crepe(x, p_len, "small"), 
            "mangio-crepe-medium": lambda: self.get_f0_mangio_crepe(x, p_len, "medium"), 
            "mangio-crepe-large": lambda: self.get_f0_mangio_crepe(x, p_len, "large"), 
            "mangio-crepe-full": lambda: self.get_f0_mangio_crepe(x, p_len, "full"), 
            "crepe-tiny": lambda: self.get_f0_crepe(x, p_len, "tiny"), 
            "crepe-small": lambda: self.get_f0_crepe(x, p_len, "small"), 
            "crepe-medium": lambda: self.get_f0_crepe(x, p_len, "medium"), 
            "crepe-large": lambda: self.get_f0_crepe(x, p_len, "large"), 
            "crepe-full": lambda: self.get_f0_crepe(x, p_len, "full"), 
            "fcpe": lambda: self.get_f0_fcpe(x, p_len), 
            "fcpe-legacy": lambda: self.get_f0_fcpe(x, p_len, legacy=True), 
            "rmvpe": lambda: self.get_f0_rmvpe(x, p_len), 
            "rmvpe-legacy": lambda: self.get_f0_rmvpe(x, p_len, legacy=True), 
            "harvest": lambda: self.get_f0_pyworld(x, p_len, filter_radius, "harvest"), 
            "yin": lambda: self.get_f0_yin(x, p_len, mode="yin"), 
            "pyin": lambda: self.get_f0_yin(x, p_len, mode="pyin"), 
            "swipe": lambda: self.get_f0_swipe(x, p_len)
        }[f0_method]()
    
    def get_f0_pm(self, x, p_len):
        f0 = (
            parselmouth.Sound(
                x, 
                self.sample_rate
            ).to_pitch_ac(
                time_step=160 / self.sample_rate * 1000 / 1000, 
                voicing_threshold=0.6, 
                pitch_floor=self.f0_min, 
                pitch_ceiling=self.f0_max
            ).selected_array["frequency"]
        )

        pad_size = (p_len - len(f0) + 1) // 2

        if pad_size > 0 or p_len - len(f0) - pad_size > 0: f0 = np.pad(f0, [[pad_size, p_len - len(f0) - pad_size]], mode="constant")
        return f0
    
    def get_f0_mangio_crepe(self, x, p_len, model="full"):
        if not hasattr(self, "mangio_crepe"):
            self.mangio_crepe = CREPE(
                os.path.join(
                    "models", 
                    f"crepe_{model}.pth"
                ), 
                model_size=model, 
                hop_length=self.hop_length, 
                batch_size=self.hop_length * 2, 
                f0_min=self.f0_min, 
                f0_max=self.f0_max, 
                device=self.device, 
                sample_rate=self.sample_rate, 
                return_periodicity=False
            )

        x = x.astype(np.float32)
        x /= np.quantile(np.abs(x), 0.999)

        audio = torch.unsqueeze(torch.from_numpy(x).to(self.device, copy=True), dim=0)
        if audio.ndim == 2 and audio.shape[0] > 1: audio = torch.mean(audio, dim=0, keepdim=True).detach()

        f0 = self.mangio_crepe.compute_f0(audio.detach(), pad=True)
        return self._resize_f0(f0.squeeze(0).cpu().float().numpy(), p_len)
    
    def get_f0_crepe(self, x, p_len, model="full"):
        if not hasattr(self, "crepe"):
            self.crepe = CREPE(
                os.path.join(
                    "models", 
                    f"crepe_{model}.pth"
                ), 
                model_size=model, 
                hop_length=self.hop_length, 
                batch_size=512, 
                f0_min=self.f0_min, 
                f0_max=self.f0_max, 
                device=self.device, 
                sample_rate=self.sample_rate, 
                return_periodicity=True
            )

        f0, pd = self.crepe.compute_f0(torch.tensor(np.copy(x))[None].float(), pad=True)
        f0, pd = mean(f0, 3), median(pd, 3)
        f0[pd < 0.1] = 0

        return self._resize_f0(f0[0].cpu().numpy(), p_len)
    
    def get_f0_fcpe(self, x, p_len, legacy=False):
        if not hasattr(self, "fcpe"): 
            self.fcpe = FCPE(
                os.path.join(
                    "models", 
                    ("fcpe_legacy" if legacy else "fcpe") + ".pt"
                ), 
                hop_length=self.hop_length, 
                f0_min=self.f0_min, 
                f0_max=self.f0_max, 
                dtype=torch.float32, 
                device=self.device, 
                sample_rate=self.sample_rate, 
                threshold=0.03 if legacy else 0.006, 
                legacy=legacy
            )
        
        f0 = self.fcpe.compute_f0(x, p_len)
        return f0
    
    def get_f0_rmvpe(self, x, p_len, legacy=False):
        if not hasattr(self, "rmvpe"): 
            self.rmvpe = RMVPE(
                os.path.join(
                    "models", 
                    "rmvpe.pt"
                ), 
                is_half=self.is_half, 
                device=self.device, 
            )

        f0 = self.rmvpe.infer_from_audio_with_pitch(x, thred=0.03, f0_min=self.f0_min, f0_max=self.f0_max) if legacy else self.rmvpe.infer_from_audio(x, thred=0.03)
        return self._resize_f0(f0, p_len)
    
    def get_f0_pyworld(self, x, p_len, filter_radius, model="harvest"):
        if not hasattr(self, "pw"): self.pw = PYWORLD()

        x = x.astype(np.double)
        pw = self.pw.harvest if model == "harvest" else self.pw.dio

        f0, t = pw(
            x, 
            fs=self.sample_rate, 
            f0_ceil=self.f0_max, 
            f0_floor=self.f0_min, 
            frame_period=1000 * self.window / self.sample_rate
        )

        f0 = self.pw.stonemask(
            x, 
            self.sample_rate, 
            t, 
            f0
        )

        if filter_radius > 2 and model == "harvest": f0 = medfilt(f0, filter_radius)
        elif model == "dio":
            for index, pitch in enumerate(f0):
                f0[index] = round(pitch, 1)

        return self._resize_f0(f0, p_len)
    
    def get_f0_swipe(self, x, p_len):
        f0, t = swipe(
            x.astype(np.float32), 
            self.sample_rate, 
            f0_floor=self.f0_min, 
            f0_ceil=self.f0_max, 
            frame_period=1000 * self.window / self.sample_rate
        )

        return self._resize_f0(
            stonemask(
                x, 
                self.sample_rate, 
                t, 
                f0
            ), 
            p_len
        )
    
    def get_f0_yin(self, x, p_len, mode="yin"):
        self.if_yin = mode == "yin"
        self.yin = yin if self.if_yin else pyin

        f0 = self.yin(
            x.astype(np.float32), 
            sr=self.sample_rate, 
            fmin=self.f0_min, 
            fmax=self.f0_max, 
            hop_length=self.hop_length
        )

        if not self.if_yin: f0 = f0[0]
        return self._resize_f0(f0, p_len)