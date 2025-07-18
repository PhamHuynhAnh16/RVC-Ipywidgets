import os
import sys
import torch

import numpy as np
import torch.nn as nn
import torch.nn.functional as F

from librosa.filters import mel

sys.path.append(os.getcwd())

from modules import opencl

N_MELS, N_CLASS = 128, 360

class ConvBlockRes(nn.Module):
    def __init__(self, in_channels, out_channels, momentum=0.01):
        super(ConvBlockRes, self).__init__()
        self.conv = nn.Sequential(nn.Conv2d(in_channels=in_channels, out_channels=out_channels, kernel_size=(3, 3), stride=(1, 1), padding=(1, 1), bias=False), nn.BatchNorm2d(out_channels, momentum=momentum), nn.ReLU(), nn.Conv2d(in_channels=out_channels, out_channels=out_channels, kernel_size=(3, 3), stride=(1, 1), padding=(1, 1), bias=False), nn.BatchNorm2d(out_channels, momentum=momentum), nn.ReLU())
        if in_channels != out_channels:
            self.shortcut = nn.Conv2d(in_channels, out_channels, (1, 1))
            self.is_shortcut = True
        else: self.is_shortcut = False

    def forward(self, x):
        return (self.conv(x) + self.shortcut(x)) if self.is_shortcut else (self.conv(x) + x)

class ResEncoderBlock(nn.Module):
    def __init__(self, in_channels, out_channels, kernel_size, n_blocks=1, momentum=0.01):
        super(ResEncoderBlock, self).__init__()
        self.n_blocks = n_blocks
        self.conv = nn.ModuleList()
        self.conv.append(ConvBlockRes(in_channels, out_channels, momentum))

        for _ in range(n_blocks - 1):
            self.conv.append(ConvBlockRes(out_channels, out_channels, momentum))

        self.kernel_size = kernel_size
        if self.kernel_size is not None: self.pool = nn.AvgPool2d(kernel_size=kernel_size)

    def forward(self, x):
        for i in range(self.n_blocks):
            x = self.conv[i](x)

        if self.kernel_size is not None: return x, self.pool(x)
        else: return x

class Encoder(nn.Module):
    def __init__(self, in_channels, in_size, n_encoders, kernel_size, n_blocks, out_channels=16, momentum=0.01):
        super(Encoder, self).__init__()
        self.n_encoders = n_encoders
        self.bn = nn.BatchNorm2d(in_channels, momentum=momentum)
        self.layers = nn.ModuleList()

        for _ in range(self.n_encoders):
            self.layers.append(ResEncoderBlock(in_channels, out_channels, kernel_size, n_blocks, momentum=momentum))
            in_channels = out_channels
            out_channels *= 2
            in_size //= 2
            
        self.out_size = in_size
        self.out_channel = out_channels

    def forward(self, x):
        concat_tensors = []
        x = self.bn(x)

        for layer in self.layers:
            t, x = layer(x)
            concat_tensors.append(t)

        return x, concat_tensors

class Intermediate(nn.Module):
    def __init__(self, in_channels, out_channels, n_inters, n_blocks, momentum=0.01):
        super(Intermediate, self).__init__()
        self.layers = nn.ModuleList()
        self.layers.append(ResEncoderBlock(in_channels, out_channels, None, n_blocks, momentum))

        for _ in range(n_inters - 1):
            self.layers.append(ResEncoderBlock(out_channels, out_channels, None, n_blocks, momentum))

    def forward(self, x):
        for layer in self.layers:
            x = layer(x)

        return x

class ResDecoderBlock(nn.Module):
    def __init__(self, in_channels, out_channels, stride, n_blocks=1, momentum=0.01):
        super(ResDecoderBlock, self).__init__()
        out_padding = (0, 1) if stride == (1, 2) else (1, 1)
        self.conv1 = nn.Sequential(nn.ConvTranspose2d(in_channels=in_channels, out_channels=out_channels, kernel_size=(3, 3), stride=stride, padding=(1, 1), output_padding=out_padding, bias=False), nn.BatchNorm2d(out_channels, momentum=momentum), nn.ReLU())
        self.conv2 = nn.ModuleList()
        self.conv2.append(ConvBlockRes(out_channels * 2, out_channels, momentum))

        for _ in range(n_blocks - 1):
            self.conv2.append(ConvBlockRes(out_channels, out_channels, momentum))

    def forward(self, x, concat_tensor):
        x = torch.cat((self.conv1(x), concat_tensor), dim=1)
        for conv2 in self.conv2:
            x = conv2(x)

        return x

class Decoder(nn.Module):
    def __init__(self, in_channels, n_decoders, stride, n_blocks, momentum=0.01):
        super(Decoder, self).__init__()
        self.layers = nn.ModuleList()

        for _ in range(n_decoders):
            out_channels = in_channels // 2
            self.layers.append(ResDecoderBlock(in_channels, out_channels, stride, n_blocks, momentum))
            in_channels = out_channels

    def forward(self, x, concat_tensors):
        for i, layer in enumerate(self.layers):
            x = layer(x, concat_tensors[-1 - i])

        return x

class DeepUnet(nn.Module):
    def __init__(self, kernel_size, n_blocks, en_de_layers=5, inter_layers=4, in_channels=1, en_out_channels=16):
        super(DeepUnet, self).__init__()
        self.encoder = Encoder(in_channels, 128, en_de_layers, kernel_size, n_blocks, en_out_channels)
        self.intermediate = Intermediate(self.encoder.out_channel // 2, self.encoder.out_channel, inter_layers, n_blocks)
        self.decoder = Decoder(self.encoder.out_channel, en_de_layers, kernel_size, n_blocks)

    def forward(self, x):
        x, concat_tensors = self.encoder(x)
        return self.decoder(self.intermediate(x), concat_tensors)

class E2E(nn.Module):
    def __init__(self, n_blocks, n_gru, kernel_size, en_de_layers=5, inter_layers=4, in_channels=1, en_out_channels=16):
        super(E2E, self).__init__()
        self.unet = DeepUnet(kernel_size, n_blocks, en_de_layers, inter_layers, in_channels, en_out_channels)
        self.cnn = nn.Conv2d(en_out_channels, 3, (3, 3), padding=(1, 1))
        self.fc = nn.Sequential(BiGRU(3 * 128, 256, n_gru), nn.Linear(512, N_CLASS), nn.Dropout(0.25), nn.Sigmoid()) if n_gru else nn.Sequential(nn.Linear(3 * N_MELS, N_CLASS), nn.Dropout(0.25), nn.Sigmoid())

    def forward(self, mel):
        return self.fc(self.cnn(self.unet(mel.transpose(-1, -2).unsqueeze(1))).transpose(1, 2).flatten(-2))

class MelSpectrogram(torch.nn.Module):
    def __init__(self, is_half, n_mel_channels, sample_rate, win_length, hop_length, n_fft=None, mel_fmin=0, mel_fmax=None, clamp=1e-5):
        super().__init__()
        n_fft = win_length if n_fft is None else n_fft
        self.hann_window = {}
        mel_basis = mel(sr=sample_rate, n_fft=n_fft, n_mels=n_mel_channels, fmin=mel_fmin, fmax=mel_fmax, htk=True)
        mel_basis = torch.from_numpy(mel_basis).float()
        self.register_buffer("mel_basis", mel_basis)
        self.n_fft = win_length if n_fft is None else n_fft
        self.hop_length = hop_length
        self.win_length = win_length
        self.sample_rate = sample_rate
        self.n_mel_channels = n_mel_channels
        self.clamp = clamp
        self.is_half = is_half 

    def forward(self, audio, keyshift=0, speed=1, center=True):
        factor = 2 ** (keyshift / 12)
        win_length_new = int(np.round(self.win_length * factor))
        keyshift_key = str(keyshift) + "_" + str(audio.device)
        if keyshift_key not in self.hann_window: self.hann_window[keyshift_key] = torch.hann_window(win_length_new).to(audio.device)

        n_fft = int(np.round(self.n_fft * factor))
        hop_length = int(np.round(self.hop_length * speed))

        if str(audio.device).startswith("ocl"):
            stft = opencl.STFT(filter_length=n_fft, hop_length=hop_length, win_length=win_length_new).to(audio.device)
            magnitude = stft.transform(audio, 1e-9)
        else:
            fft = torch.stft(audio, n_fft=n_fft, hop_length=hop_length, win_length=win_length_new, window=self.hann_window[keyshift_key], center=center, return_complex=True)
            magnitude = torch.sqrt(fft.real.pow(2) + fft.imag.pow(2))

        if keyshift != 0:
            size = self.n_fft // 2 + 1
            resize = magnitude.size(1)
            if resize < size: magnitude = F.pad(magnitude, (0, 0, 0, size - resize))
            magnitude = magnitude[:, :size, :] * self.win_length / win_length_new

        mel_output = torch.matmul(self.mel_basis, magnitude)
        if self.is_half: mel_output = mel_output.half()

        return torch.log(torch.clamp(mel_output, min=self.clamp))

class RMVPE:
    def __init__(self, model_path, is_half, device=None):
        self.resample_kernel = {}
        self.resample_kernel = {}
        model = E2E(4, 1, (2, 2))
        ckpt = torch.load(model_path, map_location="cpu")
        model.load_state_dict(ckpt)
        model.eval()
        if is_half: model = model.half()
        self.model = model.to(device)
        self.is_half = is_half
        self.device = device
        self.mel_extractor = MelSpectrogram(is_half, N_MELS, 16000, 1024, 160, None, 30, 8000).to(device)
        cents_mapping = 20 * np.arange(N_CLASS) + 1997.3794084376191
        self.cents_mapping = np.pad(cents_mapping, (4, 4))

    def mel2hidden(self, mel):
        with torch.no_grad():
            n_frames = mel.shape[-1]
            n_pad = 32 * ((n_frames - 1) // 32 + 1) - n_frames
            if n_pad > 0: mel = F.pad(mel, (0, n_pad), mode="constant")

            hidden = self.model(mel.half() if self.is_half else mel.float())
            return hidden[:, :n_frames]

    def decode(self, hidden, thred=0.03):
        f0 = 10 * (2 ** (self.to_local_average_cents(hidden, thred=thred) / 1200))
        f0[f0 == 10] = 0

        return f0

    def infer_from_audio(self, audio, thred=0.03):
        hidden = self.mel2hidden(self.mel_extractor(torch.from_numpy(audio).float().to(self.device).unsqueeze(0), center=True))

        return self.decode((hidden.squeeze(0).cpu().numpy().astype(np.float32) if self.is_half else hidden.squeeze(0).cpu().numpy()), thred=thred)
    
    def infer_from_audio_with_pitch(self, audio, thred=0.03, f0_min=50, f0_max=1100):
        hidden = self.mel2hidden(self.mel_extractor(torch.from_numpy(audio).float().to(self.device).unsqueeze(0), center=True))

        f0 = self.decode((hidden.squeeze(0).cpu().numpy().astype(np.float32) if self.is_half else hidden.squeeze(0).cpu().numpy()), thred=thred)
        f0[(f0 < f0_min) | (f0 > f0_max)] = 0  

        return f0

    def to_local_average_cents(self, salience, thred=0.05):
        center = np.argmax(salience, axis=1)
        salience = np.pad(salience, ((0, 0), (4, 4)))
        center += 4
        todo_salience, todo_cents_mapping = [], []
        starts = center - 4
        ends = center + 5

        for idx in range(salience.shape[0]):
            todo_salience.append(salience[:, starts[idx] : ends[idx]][idx])
            todo_cents_mapping.append(self.cents_mapping[starts[idx] : ends[idx]])

        todo_salience = np.array(todo_salience)
        devided = np.sum(todo_salience * np.array(todo_cents_mapping), 1) / np.sum(todo_salience, 1)
        devided[np.max(salience, axis=1) <= thred] = 0

        return devided

class BiGRU(nn.Module):
    def __init__(self, input_features, hidden_features, num_layers):
        super(BiGRU, self).__init__()
        self.gru = nn.GRU(input_features, hidden_features, num_layers=num_layers, batch_first=True, bidirectional=True)

    def forward(self, x):
        try:
            return self.gru(x)[0]
        except:
            torch.backends.cudnn.enabled = False
            return self.gru(x)[0]