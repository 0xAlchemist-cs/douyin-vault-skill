"""GPU 批量转录: 抽音频(ffmpeg) + faster-whisper large-v3, CUDA 优先/CPU 兜底, 断点续跑。

用法: python transcribe.py D:/xxx/videos -o D:/xxx
生成: {out}/audio/*.wav, {out}/transcripts/*.txt|*.srt, {out}/transcribe_manifest.json

Windows CUDA 前置(一次性):
  pip install faster-whisper nvidia-cublas-cu12 nvidia-cudnn-cu12
  模型走镜像: HF_ENDPOINT=https://hf-mirror.com
关键坑:
  - ctranslate2 内部 LoadLibrary 找不到 cublas/cudnn -> 必须 ctypes.CDLL 预加载驻留
  - faster-whisper 1.2.1 与新版 PyAV 的 metadata_errors 参数不兼容 -> 直接喂 numpy 数组绕开
"""
import argparse
import ctypes
import glob
import json
import os
import re
import subprocess
import sys
import time
import wave
from pathlib import Path

import numpy as np

MP4_RE = re.compile(r"^(\d{3})_(\d{8,25})\.mp4$")
NV_GLOB = os.environ.get("NV_LIB_GLOB", r"{site}/nvidia/*/bin")


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def setup_cuda_dlls():
    """预加载 CUDA DLL 驻留内存, 供 ctranslate2 内部 LoadLibrary 解析依赖。"""
    site = next(iter(glob.glob(os.path.join(sys.prefix, "Lib", "site-packages"))), None) or ""
    for d in glob.glob(NV_GLOB.format(site=site)) + glob.glob(NV_GLOB.format(site=sys.prefix)):
        if os.path.isdir(d):
            os.add_dll_directory(d)
            os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
    for name in ("cudart64_12.dll", "cublas64_12.dll", "cublasLt64_12.dll", "cudnn64_9.dll"):
        try:
            ctypes.CDLL(name)
        except OSError:
            pass


def load_audio(wav_path):
    with wave.open(str(wav_path), "rb") as w:
        if w.getframerate() != 16000 or w.getnchannels() != 1:
            raise ValueError("need 16k mono wav")
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0


def fmt_ts(sec):
    h, m, s = int(sec // 3600), int(sec % 3600 // 60), sec % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("videos_dir", help="mp4 目录")
    ap.add_argument("-o", "--out", required=True, help="输出根目录")
    ap.add_argument("-m", "--model", default="large-v3")
    args = ap.parse_args()
    base = Path(args.out)
    audio_dir, trans_dir = base / "audio", base / "transcripts"
    audio_dir.mkdir(parents=True, exist_ok=True)
    trans_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = base / "transcribe_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}

    setup_cuda_dlls()
    from faster_whisper import WhisperModel

    try:
        model = WhisperModel(args.model, device="cuda", compute_type="float16")
        log("CUDA ready")
    except Exception as e:
        log(f"CUDA failed ({e}); CPU int8 fallback")
        model = WhisperModel(args.model, device="cpu", compute_type="int8")

    # 阶段1: 抽音频
    for mp4 in sorted(Path(args.videos_dir).glob("*.mp4")):
        m = MP4_RE.match(mp4.name)
        if not m:
            continue
        vid = m.group(2)
        wav = audio_dir / f"{vid}.wav"
        if wav.exists() and wav.stat().st_size > 10_000:
            continue
        r = subprocess.run(["ffmpeg", "-y", "-i", str(mp4), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav)], capture_output=True, text=True)
        if r.returncode == 0 and wav.exists() and wav.stat().st_size > 10_000:
            log(f"audio {vid}")
        else:
            wav.unlink(missing_ok=True)
            log(f"audio FAIL {vid}")

    # 阶段2: 转录(断点续跑)
    todo = [w for w in sorted(audio_dir.glob("*.wav")) if w.stem.isdigit() and manifest.get(w.stem, {}).get("status") != "ok"]
    log(f"todo={len(todo)}")
    for idx, wav in enumerate(todo, 1):
        vid, t0 = wav.stem, time.time()
        try:
            audio = load_audio(wav)
            segments, _ = model.transcribe(audio, language="zh", vad_filter=True, beam_size=5)
            lines, srt = [], []
            for i, seg in enumerate(segments, 1):
                text = seg.text.strip()
                if not text:
                    continue
                lines.append(text)
                srt.append(f"{i}\n{fmt_ts(seg.start)} --> {fmt_ts(seg.end)}\n{text}\n")
            (trans_dir / f"{vid}.txt").write_text("\n".join(lines), encoding="utf-8")
            (trans_dir / f"{vid}.srt").write_text("\n".join(srt), encoding="utf-8")
            manifest[vid] = {"status": "ok", "chars": len("".join(lines)), "secs": round(time.time() - t0)}
            log(f"[{idx}/{len(todo)}] {vid} -> {manifest[vid]['chars']} chars")
        except Exception as e:
            manifest[vid] = {"status": "error", "error": str(e)[:200]}
            log(f"FAIL {vid}: {e}")
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    log("ALL DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
