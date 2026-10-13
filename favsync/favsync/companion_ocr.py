"""Offline CPU OCR, single task, two threads; cache only confident text."""
import hashlib
import json
import os
from pathlib import Path
import threading
import time
from urllib.parse import urlsplit

import requests

VERSION = "rapidocr-3.9.2-ppocrv5-mobile-0.85"
MODELS = {
    "det": ("ch_PP-OCRv5_det_mobile.onnx", "4d97c44a20d30a81aad087d6a396b08f786c4635742afc391f6621f5c6ae78ae"),
    "rec": ("ch_PP-OCRv5_rec_mobile.onnx", "5825fc7ebf84ae7a412be049820b4d86d77620f204a041697b0494669b1742c5"),
    "cls": ("ch_PP-LCNet_x0_25_textline_ori_cls_mobile.onnx", "54379ae5174d026780215fc748a7f31910dee36818e63d49e17dc598ecc82df7"),
}
_lock = threading.Lock()
_engine = None


def model_dir():
    return Path(os.environ.get("FAVSYNC_OCR_MODELS", "/opt/favsync/ocr"))


def download_models():
    root = model_dir()
    root.mkdir(parents=True, exist_ok=True)
    for kind, (name, digest) in MODELS.items():
        response = requests.get("https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/onnx/PP-OCRv5/"
                                + kind + "/" + name, timeout=180)
        response.raise_for_status()
        if hashlib.sha256(response.content).hexdigest() != digest:
            raise ValueError("OCR model checksum mismatch")
        (root / name).write_bytes(response.content)


def recognize(content):
    global _engine
    with _lock:
        if _engine is None:
            for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
                os.environ[name] = "2"
            import cv2
            cv2.setNumThreads(2)
            from rapidocr import RapidOCR, ModelType, OCRVersion
            params = {"EngineConfig.onnxruntime.intra_op_num_threads": 2,
                      "EngineConfig.onnxruntime.inter_op_num_threads": 1,
                      "EngineConfig.onnxruntime.use_cuda": False,
                      "EngineConfig.onnxruntime.use_dml": False,
                      "Global.text_score": 0.85,
                      "Global.log_level": "error"}
            for kind, (name, digest) in MODELS.items():
                path = model_dir() / name
                if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                    raise ValueError("OCR model checksum mismatch")
                params[kind.title() + ".model_path"] = str(path)
                params[kind.title() + ".model_type"] = ModelType.MOBILE
                params[kind.title() + ".ocr_version"] = OCRVersion.PPOCRV5
            _engine = RapidOCR(params=params)
        result = _engine(content)
        texts, scores = result.txts or [], result.scores or []
        accepted = [(t, float(s)) for t, s in zip(texts, scores) if s >= 0.85]
        return "\n".join(t for t, _ in accepted), [s for _, s in accepted]


def image_text(db, url):
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or not any(
            parsed.hostname == h or parsed.hostname.endswith("." + h) for h in ("xhscdn.com", "xiaohongshu.com")):
        raise ValueError("untrusted image URL")
    with requests.get(url, stream=True, timeout=30, allow_redirects=False) as response:
        response.raise_for_status()
        if response.is_redirect:
            raise ValueError("image redirect refused")
        data = bytearray()
        for part in response.iter_content(65536):
            data.extend(part)
            if len(data) > 16 * 1024 * 1024:
                raise ValueError("image too large")
    key = VERSION + ":" + hashlib.sha256(data).hexdigest()
    cached = db.execute("SELECT text FROM companion_ocr WHERE cache_key=?", (key,)).fetchone()
    if cached:
        return cached[0]
    text, scores = recognize(bytes(data))
    db.execute("INSERT INTO companion_ocr VALUES(?,?,?,?,?)",
               (key, text, json.dumps(scores), "ready", time.time()))
    db.commit()
    return text


if __name__ == "__main__":
    download_models()
