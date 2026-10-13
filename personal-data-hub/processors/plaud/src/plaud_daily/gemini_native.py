"""使用既有 CPA 的 Gemini 原生音频格式，并保留上游过滤诊断。"""
import argparse
import base64
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .core import atomic_bytes
from .multiday_trial import gemini_seconds, inspect_gemini, parse_gemini, stamp

PROMPT = (
    "Generate a verbatim transcript of the speech in this audio. "
    "The speech is Chinese; preserve English terms. "
    "Include relative timestamps and anonymous speakers on each line using this format: "
    "[mm:ss] Speaker 1: text. Mark unclear words as [听不清] and overlapping speech as [重叠]. "
    "Keep timestamps in chronological, non-decreasing order. Do not repeat earlier timestamps. "
)


def normalize_timestamp_brackets(content: str) -> str:
    """补齐模型遗漏的时间戳方括号；不改时间、文字或说话人。"""
    return re.sub(r"^(\s*(?:[-*]\s*)?)(\d{1,2}:\d{2}(?::\d{2})?)(\s+Speaker\s+[\d?]+\s*[:：]\s*.+)$",
                  r"\1[\2]\3", content, flags=re.M)


def publish_response(audio: bytes, output: Path, model: str, wire: dict, seconds: float, elapsed: float) -> dict:
    """拒绝空候选、截断和异常时间；保留可定位的上游诊断。"""
    preserve_response(output)
    candidates = wire.get("candidates", [])
    diagnostic = {"model": model, "transport": "gemini_native", "audio_sha256": hashlib.sha256(audio).hexdigest(),
                  "elapsed_seconds": round(elapsed, 2), "candidate_count": len(candidates),
                  "prompt_feedback": wire.get("promptFeedback"), "usage": wire.get("usageMetadata"),
                  "model_version": wire.get("modelVersion"),
                  "finish_reasons": [c.get("finishReason") for c in candidates]}
    atomic_bytes(output / "gemini-response-diagnostic.json", json.dumps(diagnostic, ensure_ascii=False, indent=2).encode())
    if not candidates:
        feedback = wire.get("promptFeedback", {})
        raise RuntimeError("Gemini no candidate; block_reason=" + str(feedback.get("blockReason", "unknown")) +
                           "; inspect gemini-response-diagnostic.json")
    candidate = candidates[0]
    raw = "\n".join(p["text"] for p in candidate.get("content", {}).get("parts", []) if p.get("text") and not p.get("thought"))
    if candidate.get("finishReason") != "STOP" or not raw.strip():
        raise RuntimeError("Gemini native response incomplete; finish=" + str(candidate.get("finishReason")))
    atomic_bytes(output / "gemini-raw-transcript.md", (raw.strip() + "\n").encode())
    content = normalize_timestamp_brackets(raw)
    structured = raw.lstrip().startswith('{')
    if structured:
        try:
            rows = json.loads(raw)['turns']
            if not isinstance(rows,list):
                raise ValueError('turns_not_array')
            turns = []
            for row in rows:
                if 'start_timestamp' in row:
                    timestamp = row['start_timestamp']
                    if not isinstance(timestamp,str) or not re.fullmatch(r'\d{1,3}:\d{2}(?:\.\d{1,3})?',timestamp):
                        raise ValueError('invalid_timestamp')
                    start = gemini_seconds(timestamp)
                else:
                    start = row['start_seconds']
                speaker, text = row['speaker'], row['text']
                if (isinstance(start,bool) or not isinstance(start,(int,float)) or not math.isfinite(start) or start<0 or
                        not isinstance(speaker,str) or not re.fullmatch(r'[\d?]+',speaker) or not isinstance(text,str) or not text.strip()):
                    raise ValueError('invalid_turn')
                turns.append({'start':start,'speaker':speaker,'text':text.replace('\n',' ')})
            content = '\n'.join(turn_line(turn) for turn in turns)
        except (ValueError, KeyError, TypeError):
            diagnostic['timing'] = {'valid':False,'parsed_turns':0,'out_of_range_turns':0,'backwards_timestamps':0,'last_timestamp_seconds':None}
            atomic_bytes(output/'gemini-response-diagnostic.json',json.dumps(diagnostic,ensure_ascii=False,indent=2).encode())
            raise RuntimeError('Gemini structured transcript contract invalid') from None
    timing = inspect_gemini(content, seconds)
    diagnostic["timing"] = timing
    atomic_bytes(output / "gemini-response-diagnostic.json", json.dumps(diagnostic, ensure_ascii=False, indent=2).encode())
    if not timing["valid"]:
        raise RuntimeError("Gemini timestamps invalid; inspect gemini-raw-transcript.md")
    atomic_bytes(output / "gemini-transcript.md", ("# Gemini 原生音频转录（未经人工校对）\n\n" + content.strip() + "\n").encode())
    summary = {**diagnostic, "finish_reason": "stop", "timestamp_brackets_normalized": content != raw and not structured,
               'structured_transcript':structured}
    atomic_bytes(output / "gemini-summary.json", json.dumps(summary, ensure_ascii=False, indent=2).encode())
    return summary


def preserve_response(output: Path) -> None:
    files = [output / name for name in ('gemini-raw-transcript.md', 'gemini-response-diagnostic.json',
                                        'gemini-transcript.md', 'gemini-summary.json') if (output / name).is_file()]
    if files:
        history = output / 'gemini-response-history' / str(time.time_ns())
        history.mkdir(parents=True, exist_ok=True)
        for path in files:
            shutil.copy2(path, history / path.name)


def time_label(seconds):
    whole = int(seconds)
    millis = round((seconds - whole) * 1000)
    if millis == 1000:
        whole, millis = whole + 1, 0
    return stamp(whole) + (f'.{millis:03d}' if millis else '')


def turn_line(turn, offset=0):
    timing = time_label(offset + turn['start'])
    if 'end' in turn:
        timing += ' --> ' + time_label(offset + turn['end'])
    return f"[{timing}] Speaker {turn['speaker']}: {turn['text']}"


def transcribe_part(audio, folder, offset, duration, model, url, key):
    folder.mkdir(parents=True, exist_ok=True)
    part_audio = folder / 'audio.mp3'
    if not part_audio.is_file():
        staging = folder / 'audio.part.mp3'
        subprocess.run(['ffmpeg','-v','error','-nostdin','-y','-ss',str(offset),'-i',str(audio),
                        '-t',str(duration),'-ac','1','-ar','16000','-b:a','32k',str(staging)], check=True)
        os.replace(staging, part_audio)
    payload = part_audio.read_bytes()
    saved = folder / 'gemini-summary.json'
    if saved.is_file() and (folder / 'gemini-transcript.md').is_file():
        state = json.loads(saved.read_text())
        if state['audio_sha256'] != hashlib.sha256(payload).hexdigest() or state['model'] != model:
            raise RuntimeError('Gemini cached part identity mismatch')
        parse_gemini((folder/'gemini-transcript.md').read_text(), duration)
        return
    diagnostic_path, raw_path = folder/'gemini-response-diagnostic.json', folder/'gemini-raw-transcript.md'
    diagnostic = json.loads(diagnostic_path.read_text()) if diagnostic_path.is_file() else {}
    split = False
    if (raw_path.is_file() and diagnostic.get('finish_reasons') == ['STOP'] and
            diagnostic.get('audio_sha256') == hashlib.sha256(payload).hexdigest() and diagnostic.get('model') == model):
        # A source may use valid SRT rather than the requested line format.
        # Revalidate the exact saved response before paying for another call.
        wire = {'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':raw_path.read_text()}]}}],
                'usageMetadata':diagnostic.get('usage'), 'modelVersion':diagnostic.get('model_version')}
        try:
            state = publish_response(payload, folder, model, wire, duration, diagnostic.get('elapsed_seconds',0))
            state['revalidated_saved_response'] = True
            atomic_bytes(saved, json.dumps(state,ensure_ascii=False,indent=2).encode())
            return
        except RuntimeError:
            split = duration >= 120
    if not split:
        prompt = ('Generate a verbatim Chinese transcript of the speech in this audio, preserving English terms. '
                  'Return JSON turns with start_timestamp as a string in MM:SS.mmm format relative to this clip, '
                  'anonymous speaker digit strings or ?, and the exact text. MM means whole minutes; SS is 00 to 59; '
                  'mmm means milliseconds. Example: one minute eight seconds is "01:08.000". '
                  'Do not convert timestamps to decimal numbers. Keep timestamps chronological. Mark unclear speech [听不清]. '
                  'For no intelligible speech, use a single turn at "00:00.000", speaker ?, text [无可辨语音]. '
                  f'The clip lasts {duration:.3f} seconds; every timestamp must be before {time_label(duration)}. '
                  'Use clip-relative time, starting at 00:00.000, never absolute clock times.')
        schema = {'type':'OBJECT','properties':{'turns':{'type':'ARRAY','items':{'type':'OBJECT','properties':{
            'start_timestamp':{'type':'STRING'},'speaker':{'type':'STRING'},'text':{'type':'STRING'}},
            'required':['start_timestamp','speaker','text']}}},'required':['turns']}
        body = {'contents':[{'role':'user','parts':[
            {'inlineData':{'mimeType':'audio/mpeg','data':base64.b64encode(payload).decode()}},{'text':prompt}]}],
            'generationConfig':{'temperature':0,'maxOutputTokens':16000,'responseMimeType':'application/json','responseSchema':schema}}
        request = urllib.request.Request(url,data=json.dumps(body).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},method='POST')
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request,timeout=180) as response:
                wire = json.load(response)
        except urllib.error.HTTPError as error:
            raise RuntimeError(f'Gemini native route HTTP {error.code}') from None
        try:
            publish_response(payload,folder,model,wire,duration,time.monotonic()-started)
            return
        except RuntimeError:
            diagnostic = json.loads(diagnostic_path.read_text())
            split = duration >= 120 and (diagnostic.get('timing',{}).get('valid') is False or
                                         'MAX_TOKENS' in diagnostic.get('finish_reasons',[]))
            if not split:
                raise
    # Invalid timestamps remain rejected. Retry the same continuous audio
    # as smaller parts instead of repeatedly submitting an identical failure.
    lines, originals = [], []
    for index, relative in enumerate((0, duration/2)):
        child = folder / 'halves' / str(index)
        transcribe_part(audio,child,offset+relative,duration/2,model,url,key)
        lines.extend(turn_line(t,relative) for t in parse_gemini((child/'gemini-transcript.md').read_text(),duration/2))
        originals.append(f'## Subpart {index+1}; offset_seconds={relative}\n'+(child/'gemini-raw-transcript.md').read_text())
    content = '\n'.join(lines)
    timing = inspect_gemini(content,duration)
    if not timing['valid']:
        raise RuntimeError('Gemini adaptive part timestamps invalid')
    preserve_response(folder)
    atomic_bytes(raw_path,'\n'.join(originals).encode())
    atomic_bytes(folder/'gemini-transcript.md',(content+'\n').encode())
    atomic_bytes(saved,json.dumps({'audio_sha256':hashlib.sha256(payload).hexdigest(), 'model':model,
                 'transport':'gemini_native','finish_reason':'stop','adaptive_parts':2,'timing':timing},ensure_ascii=False,indent=2).encode())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--url", required=True)
    args = parser.parse_args()
    key = os.environ["CPA_PUBLIC_API_KEY"]
    audio = args.audio.read_bytes()
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                            "default=noprint_wrappers=1:nokey=1", str(args.audio)], capture_output=True, text=True, check=True)
    seconds = float(probe.stdout.strip())
    sample_path = args.output / 'sample.json'
    if sample_path.is_file():
        # MP3 frame padding must not create a separate near-empty final part.
        seconds = min(seconds, float(json.loads(sample_path.read_text())['duration_seconds']))
    base = args.url.removesuffix("/v1/chat/completions").rstrip("/")
    url = base + "/v1beta/models/" + urllib.parse.quote(args.model, safe="") + ":generateContent"
    started = time.monotonic()
    identity = hashlib.sha256(audio + args.model.encode() + PROMPT.encode() + b'continuous-300s-v1').hexdigest()[:20]
    # Smaller continuous inputs reduce timestamp drift. Every part includes
    # its tail; completed parts remain cached across automatic retries.
    parts = []
    raw_parts = []
    for index, offset in enumerate(range(0, int(seconds + .999), 300)):
        duration = min(300, seconds - offset)
        folder = args.output / 'gemini-parts' / identity / f'{index:03d}'
        transcribe_part(args.audio,folder,offset,duration,args.model,url,key)
        content = (folder/'gemini-transcript.md').read_text()
        turns = parse_gemini(content,duration)
        parts.extend(turn_line(t,offset) for t in turns)
        raw_parts.append(f'## Part {index+1}; offset_seconds={offset}\n'+(folder/'gemini-raw-transcript.md').read_text())
    content = '\n'.join(parts)
    timing = inspect_gemini(content,seconds)
    if not timing['valid']:
        raise RuntimeError('Gemini combined part timestamps invalid')
    preserve_response(args.output)
    atomic_bytes(args.output/'gemini-raw-transcript.md','\n'.join(raw_parts).encode())
    atomic_bytes(args.output/'gemini-transcript.md',('# Gemini 原生音频转录（未经人工校对）\n\n'+content+'\n').encode())
    summary = {'audio_sha256':hashlib.sha256(audio).hexdigest(),'model':args.model,'transport':'gemini_native',
               'finish_reason':'stop','elapsed_seconds':round(time.monotonic()-started,2),'parts':len(raw_parts),'timing':timing}
    atomic_bytes(args.output/'gemini-summary.json',json.dumps(summary,ensure_ascii=False,indent=2).encode())
    print(json.dumps({k: summary[k] for k in ("audio_sha256", "model", "transport", "finish_reason", "elapsed_seconds")}))


if __name__ == "__main__":
    main()
