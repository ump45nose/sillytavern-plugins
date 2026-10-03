"""Music-aware bounded extraction; model failure never silently looks like success."""
from __future__ import annotations
import json
import os
import subprocess
import sys
import tempfile
import wave
from array import array
from pathlib import Path

def select_window(segments: list, duration: float, width: float = 45) -> dict:
    width = min(width, duration)
    if width <= 0:
        raise ValueError("empty audio")
    starts = {float(s) for s in range(0, max(1, int(duration-width)+1), 5)} | {max(0., duration-width)}
    starts |= {max(0., min(float(s[1]), duration-width)) for s in segments}
    choices = []
    for start in starts:
        shares = {k: 0. for k in ("music", "speech", "noise", "noEnergy")}
        for label, left, right in segments:
            label = "speech" if label in {"male", "female"} else label
            if label in shares:
                shares[label] += max(0., min(start+width, right)-max(start, left))/width
        choices.append((shares["music"], -shares["speech"], -shares["noise"], -shares["noEnergy"], -start, shares))
    best = max(choices, key=lambda x: x[:5])
    shares = best[5]
    return {"start": -best[4], "duration": width, "shares": shares,
            "quality": "high" if shares["music"] >= .8 and shares["speech"] <= .1 and shares["noEnergy"] <= .05 else "low"}

def analyze(source: str | Path, start: float, duration: float) -> dict:
    with tempfile.TemporaryDirectory(prefix="theme-analysis-") as temp:
        wav = Path(temp)/"audio.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-ss", str(start), "-i", str(source), "-t", str(min(duration, 1200)), "-vn", "-ac", "1", "-ar", "16000", str(wav)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=300)
        with wave.open(str(wav)) as audio:
            rate = audio.getframerate()
            samples = array("h", audio.readframes(audio.getnframes()))
            actual = len(samples)/rate
        if actual <= 0:
            raise ValueError("empty audio")
        try:
            result = subprocess.run([sys.executable, "-m", __name__, str(wav)], check=True, capture_output=True, text=True, timeout=600,
                                    env={**os.environ, "CUDA_VISIBLE_DEVICES": "-1", "OMP_NUM_THREADS": "2", "TF_NUM_INTRAOP_THREADS": "2", "TF_NUM_INTEROP_THREADS": "1"})
            segments = json.loads(result.stdout.strip().splitlines()[-1])
            selected = select_window(segments, actual)
            selected["method"] = "inaSpeechSegmenter"
        except (subprocess.SubprocessError, ValueError, IndexError):
            # Quiet/clipping analysis is an explicit low-confidence fallback,
            # not a fake music classifier and not highest-energy selection.
            width = min(45, actual)
            candidates = []
            for second in range(0, max(1, int(actual-width)+1), 5):
                values = samples[second*rate:int((second+width)*rate)]
                quiet = sum(abs(v) < 180 for v in values)/max(1, len(values))
                clipped = sum(abs(v) >= 32700 for v in values)/max(1, len(values))
                candidates.append((quiet+clipped*4, second))
            penalty, second = min(candidates)
            selected = {"start": second, "duration": width, "quality": "low", "method": "signal_fallback", "penalty": penalty}
        selected["start"] += start
        return selected

def child():
    import hashlib
    import inaSpeechSegmenter.segmenter as implementation
    model = Path("/opt/theme-models/keras_speech_music_noise_cnn.hdf5")
    if hashlib.sha256(model.read_bytes()).hexdigest() != "f04b5e3c86fa2e81666d106b0867350fe7858c7bd006c2a74c27b5b45507e7d8":
        raise ValueError("model checksum mismatch")
    implementation.get_remote = lambda _name: str(model)
    from inaSpeechSegmenter import Segmenter
    segmenter = Segmenter(vad_engine="smn", detect_gender=False)
    print(json.dumps([(label, float(start), float(end)) for label, start, end in segmenter(sys.argv[1])]))

if __name__ == "__main__":
    child()
