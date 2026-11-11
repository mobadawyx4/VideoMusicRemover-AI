"""AI Audio Source Separation service powered by TIGER-DnR (Speech, Effects, Music)."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import torch

from app.core.config import settings
from app.core.schemas import ProcessOptions, SeparationMode, StemMetrics
from app.services.media_service import compute_rms_db, load_wav, save_wav
from app.vendor.tiger import TIGERDNR

logger = logging.getLogger(__name__)


class SeparationError(Exception):
    """Raised when AI audio source separation fails."""


class TigerSeparatorService:
    """Singleton manager for TIGER-DnR AI audio separation model."""

    _instance: Optional["TigerSeparatorService"] = None

    def __init__(self) -> None:
        self._model: Optional[TIGERDNR] = None
        self._device: str = "cuda" if torch.cuda.is_available() else "cpu"
        self._model_path: Optional[Path] = None
        torch.set_num_threads(settings.TORCH_NUM_THREADS)

    @classmethod
    def get_instance(cls) -> "TigerSeparatorService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @property
    def device(self) -> str:
        return self._device

    def find_local_snapshot(self) -> Optional[Path]:
        """Locate cached HuggingFace snapshot directory for JusperLee/TIGER-DnR."""
        models_dir = settings.MODELS_DIR
        repo_folder = models_dir / f"models--{settings.MODEL_REPO_ID.replace('/', '--')}"
        snapshots_dir = repo_folder / "snapshots"
        if snapshots_dir.is_dir():
            for snap in sorted(snapshots_dir.iterdir(), reverse=True):
                if (snap / "config.json").is_file() and (
                    (snap / "model.safetensors").is_file()
                    or (snap / "pytorch_model.bin").is_file()
                ):
                    return snap
        return None

    def is_model_available(self) -> bool:
        return self.find_local_snapshot() is not None

    def load_model(self) -> TIGERDNR:
        """Lazy-load TIGER-DnR model weights onto target device."""
        if self._model is not None:
            return self._model

        snap = self.find_local_snapshot()
        try:
            t0 = time.time()
            if snap is not None:
                logger.info("Loading TIGER-DnR weights from local snapshot: %s", snap)
                model = TIGERDNR.from_pretrained(str(snap))
                self._model_path = snap
            else:
                logger.info(
                    "Downloading TIGER-DnR weights from HuggingFace Hub (%s)...",
                    settings.MODEL_REPO_ID,
                )
                model = TIGERDNR.from_pretrained(
                    settings.MODEL_REPO_ID,
                    cache_dir=str(settings.MODELS_DIR),
                )

            # Attempt to move to device; fallback to CPU if GPU lacks memory or CUDA arch support
            if self._device == "cuda":
                try:
                    model = model.to("cuda")
                    # Quick smoke test on GPU
                    test_x = torch.zeros(1, 1, 4096, device="cuda")
                    with torch.no_grad():
                        _ = model.dialog(test_x)
                except Exception as gpu_exc:
                    logger.warning(
                        "CUDA execution failed (%s); falling back to CPU.", gpu_exc
                    )
                    self._device = "cpu"
                    model = model.to("cpu")

            model.eval()
            self._model = model
            logger.info(
                "TIGER-DnR loaded on %s in %.2fs", self._device, time.time() - t0
            )
            return self._model
        except Exception as exc:
            raise SeparationError(
                f"Failed to load AI separation model '{settings.MODEL_REPO_ID}': {exc}"
            ) from exc

    def _infer_mono_chunked(
        self,
        submodel: torch.nn.Module,
        mono_audio: np.ndarray,
        sample_rate: int,
        chunk_sec: float,
        overlap_sec: float,
        progress_cb: Optional[Callable[[float], None]] = None,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Run overlap-add chunked inference on a 1D float32 mono waveform.

        Returns (speech, effects, music) 1D float32 arrays of exact same length as mono_audio.
        In TIGER-DnR:
          track 0 = music
          track 1 = sound effects / environment
          track 2 = dialogue / human speech
        """
        total_samples = mono_audio.shape[-1]
        if total_samples == 0:
            empty = np.zeros(0, dtype=np.float32)
            return empty, empty, empty

        chunk_samples = int(chunk_sec * sample_rate)
        overlap_samples = int(overlap_sec * sample_rate)
        step_samples = max(1, chunk_samples - overlap_samples)

        if total_samples <= chunk_samples:
            tensor_in = torch.from_numpy(mono_audio).float().reshape(1, 1, -1).to(self._device)
            with torch.inference_mode():
                out = submodel(tensor_in)  # shape: [1, 3, T]
            out_np = out.squeeze(0).cpu().numpy()
            if progress_cb:
                progress_cb(100.0)
            return out_np[2], out_np[1], out_np[0]

        out_music = np.zeros(total_samples, dtype=np.float32)
        out_effects = np.zeros(total_samples, dtype=np.float32)
        out_speech = np.zeros(total_samples, dtype=np.float32)
        weight_sum = np.zeros(total_samples, dtype=np.float32)

        # Raised cosine (Tukey-like) crossfade window for seamless chunk boundaries
        window = np.ones(chunk_samples, dtype=np.float32)
        if overlap_samples > 0:
            fade = np.linspace(0.0, 1.0, overlap_samples, dtype=np.float32)
            window[:overlap_samples] = fade
            window[-overlap_samples:] = fade[::-1]

        starts = list(range(0, total_samples, step_samples))
        num_chunks = len(starts)

        for idx, start in enumerate(starts):
            end = min(start + chunk_samples, total_samples)
            seg_len = end - start
            segment = mono_audio[start:end]
            if seg_len < chunk_samples:
                padded = np.zeros(chunk_samples, dtype=np.float32)
                padded[:seg_len] = segment
                segment_in = padded
            else:
                segment_in = segment

            tensor_in = torch.from_numpy(segment_in).float().reshape(1, 1, -1).to(self._device)
            with torch.inference_mode():
                est = submodel(tensor_in).squeeze(0).cpu().numpy()  # [3, chunk_samples]

            w = window[:seg_len].copy()
            if idx == 0:
                w[: min(overlap_samples, seg_len)] = 1.0
            if end == total_samples:
                w[max(0, seg_len - overlap_samples) :] = 1.0

            out_music[start:end] += est[0, :seg_len] * w
            out_effects[start:end] += est[1, :seg_len] * w
            out_speech[start:end] += est[2, :seg_len] * w
            weight_sum[start:end] += w

            if progress_cb:
                progress_cb(((idx + 1) / num_chunks) * 100.0)

            if end == total_samples:
                break

        weight_sum = np.maximum(weight_sum, 1e-6)
        return (
            out_speech / weight_sum,
            out_effects / weight_sum,
            out_music / weight_sum,
        )

    def _project_stereo_stems(
        self,
        stereo_audio: np.ndarray,
        speech_mid: np.ndarray,
        effects_mid: np.ndarray,
        music_mid: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Project separated mid stems onto stereo (2, T) channels via STFT Wiener ratio masking.

        Preserves exact stereo panning and ensures speech_st + effects_st + music_st == stereo_audio.
        """
        n_fft = 2048
        hop = 512
        win = torch.hann_window(n_fft)

        def _stft(sig: np.ndarray) -> torch.Tensor:
            t = torch.from_numpy(sig).float()
            return torch.stft(t, n_fft=n_fft, hop_length=hop, window=win, return_complex=True)

        S_spec = _stft(speech_mid).abs()
        E_spec = _stft(effects_mid).abs()
        M_spec = _stft(music_mid).abs()

        denom = S_spec + E_spec + M_spec + 1e-8
        mask_s = (S_spec / denom).unsqueeze(0)
        mask_e = (E_spec / denom).unsqueeze(0)
        mask_m = (M_spec / denom).unsqueeze(0)

        stereo_t = torch.from_numpy(stereo_audio).float()
        mix_spec = torch.stft(
            stereo_t, n_fft=n_fft, hop_length=hop, window=win, return_complex=True
        )
        length = stereo_audio.shape[-1]

        speech_st = torch.istft(
            mix_spec * mask_s, n_fft=n_fft, hop_length=hop, window=win, length=length
        ).numpy()
        effects_st = torch.istft(
            mix_spec * mask_e, n_fft=n_fft, hop_length=hop, window=win, length=length
        ).numpy()
        music_st = torch.istft(
            mix_spec * mask_m, n_fft=n_fft, hop_length=hop, window=win, length=length
        ).numpy()

        return speech_st, effects_st, music_st

    def separate_audio_file(
        self,
        input_wav_path: Path,
        output_dir: Path,
        options: ProcessOptions,
        progress_callback: Optional[Callable[[float, str], None]] = None,
    ) -> tuple[dict[str, Path], StemMetrics]:
        """Separate an extracted audio WAV file into speech, environmental effects, and music stems,
        and reconstruct the music-removed audio track according to ProcessOptions.
        """
        t_start = time.time()
        if progress_callback:
            progress_callback(2.0, "Loading TIGER-DnR neural audio separation model...")

        model = self.load_model()
        audio, sr = load_wav(input_wav_path)  # shape: (channels, samples)
        channels, total_samples = audio.shape

        if total_samples == 0:
            raise SeparationError("Extracted audio track contains 0 samples.")

        mono_mix = np.mean(audio, axis=0) if channels > 1 else audio[0]

        if progress_callback:
            progress_callback(8.0, "Running AI source separation (Speech, Environment, Music)...")

        mode = options.separation_mode
        if mode == SeparationMode.FAST:
            chunk_sec, overlap_sec = 10.0, 1.0
            speech_m, effects_m, music_m = self._infer_mono_chunked(
                model.music,
                mono_mix,
                sr,
                chunk_sec=chunk_sec,
                overlap_sec=overlap_sec,
                progress_cb=lambda p: (
                    progress_callback(8.0 + p * 0.72, "Separating audio stems (Fast AI mode)...")
                    if progress_callback
                    else None
                ),
            )
        elif mode == SeparationMode.HIGH_QUALITY:
            chunk_sec, overlap_sec = 8.0, 2.0
            # Run dedicated dialog, effect, and music submodels
            s_d, _, _ = self._infer_mono_chunked(
                model.dialog,
                mono_mix,
                sr,
                chunk_sec=chunk_sec,
                overlap_sec=overlap_sec,
                progress_cb=lambda p: (
                    progress_callback(8.0 + p * 0.24, "Separating human speech stem (Pass 1/3)...")
                    if progress_callback
                    else None
                ),
            )
            _, e_e, _ = self._infer_mono_chunked(
                model.effect,
                mono_mix,
                sr,
                chunk_sec=chunk_sec,
                overlap_sec=overlap_sec,
                progress_cb=lambda p: (
                    progress_callback(32.0 + p * 0.24, "Separating environmental sounds stem (Pass 2/3)...")
                    if progress_callback
                    else None
                ),
            )
            _, _, m_m = self._infer_mono_chunked(
                model.music,
                mono_mix,
                sr,
                chunk_sec=chunk_sec,
                overlap_sec=overlap_sec,
                progress_cb=lambda p: (
                    progress_callback(56.0 + p * 0.24, "Separating background music stem (Pass 3/3)...")
                    if progress_callback
                    else None
                ),
            )
            speech_m, effects_m, music_m = s_d, e_e, m_m
        else:
            # BALANCED mode: overlap-add chunking with single conservation-preserving TIGER-DnR pass
            chunk_sec, overlap_sec = 8.0, 1.5
            speech_m, effects_m, music_m = self._infer_mono_chunked(
                model.music,
                mono_mix,
                sr,
                chunk_sec=chunk_sec,
                overlap_sec=overlap_sec,
                progress_cb=lambda p: (
                    progress_callback(8.0 + p * 0.72, "Separating Speech, Environmental Audio & Music stems...")
                    if progress_callback
                    else None
                ),
            )

        if progress_callback:
            progress_callback(82.0, "Reconstructing stereo spatial image and mixing clean audio...")

        if channels == 2:
            speech_st, effects_st, music_st = self._project_stereo_stems(
                audio, speech_m, effects_m, music_m
            )
        else:
            speech_st = speech_m.reshape(1, -1)
            effects_st = effects_m.reshape(1, -1)
            music_st = music_m.reshape(1, -1)

        output_dir.mkdir(parents=True, exist_ok=True)
        speech_path = save_wav(output_dir / "speech_stem.wav", speech_st, sr)
        effects_path = save_wav(output_dir / "effects_stem.wav", effects_st, sr)
        music_path = save_wav(output_dir / "music_stem.wav", music_st, sr)

        processed_audio = self.combine_stems_arrays(
            speech_st,
            effects_st,
            music_st,
            music_removal_strength=options.music_removal_strength,
            speech_gain=options.speech_gain,
            effects_gain=options.effects_gain,
        )
        processed_path = save_wav(output_dir / "processed_audio.wav", processed_audio, sr)

        orig_rms = compute_rms_db(audio)
        proc_rms = compute_rms_db(processed_audio)
        speech_rms = compute_rms_db(speech_st)
        effects_rms = compute_rms_db(effects_st)
        music_rms = compute_rms_db(music_st)

        residual_music_factor = max(1e-3, 1.0 - options.music_removal_strength)
        suppression_db = round(min(45.0, abs(20.0 * np.log10(residual_music_factor))), 1)

        elapsed = round(time.time() - t_start, 2)
        metrics = StemMetrics(
            speech_rms_db=speech_rms,
            effects_rms_db=effects_rms,
            music_rms_db=music_rms,
            original_rms_db=orig_rms,
            processed_rms_db=proc_rms,
            music_suppression_db=suppression_db,
            processing_time_seconds=elapsed,
            model_used=f"TIGER-DnR ({mode.value})",
            device_used=self._device,
        )

        if progress_callback:
            progress_callback(100.0, "AI source separation complete.")

        return (
            {
                "speech": speech_path,
                "effects": effects_path,
                "music": music_path,
                "processed": processed_path,
            },
            metrics,
        )

    @staticmethod
    def combine_stems_arrays(
        speech: np.ndarray,
        effects: np.ndarray,
        music: np.ndarray,
        music_removal_strength: float = 1.0,
        speech_gain: float = 1.0,
        effects_gain: float = 1.0,
    ) -> np.ndarray:
        """Mix separated stems according to user controls while preventing clipping."""
        music_gain = max(0.0, min(1.0, 1.0 - music_removal_strength))
        mixed = (
            (speech * float(speech_gain))
            + (effects * float(effects_gain))
            + (music * float(music_gain))
        )
        peak = float(np.max(np.abs(mixed))) if mixed.size > 0 else 0.0
        if peak > 0.99:
            mixed = mixed * (0.99 / peak)
        return mixed.astype(np.float32)

    def remix_existing_stems(
        self,
        job_dir: Path,
        music_removal_strength: float,
        speech_gain: float = 1.0,
        effects_gain: float = 1.0,
    ) -> Path:
        """Fast remix of already-separated stems without re-running neural network inference."""
        speech_path = job_dir / "speech_stem.wav"
        effects_path = job_dir / "effects_stem.wav"
        music_path = job_dir / "music_stem.wav"

        if not (speech_path.is_file() and effects_path.is_file() and music_path.is_file()):
            raise SeparationError("Separated audio stems are missing for this job.")

        speech, sr = load_wav(speech_path)
        effects, _ = load_wav(effects_path)
        music, _ = load_wav(music_path)

        remixed = self.combine_stems_arrays(
            speech,
            effects,
            music,
            music_removal_strength=music_removal_strength,
            speech_gain=speech_gain,
            effects_gain=effects_gain,
        )
        return save_wav(job_dir / "processed_audio.wav", remixed, sr)


separator_service = TigerSeparatorService.get_instance()
