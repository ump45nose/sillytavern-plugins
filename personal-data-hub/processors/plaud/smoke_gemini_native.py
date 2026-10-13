"""验证 Gemini 响应边界和时间戳规范化；不调用网络。"""
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from plaud_daily.gemini_native import normalize_timestamp_brackets, publish_response
from plaud_daily import gemini_native as native


def response(text, finish="STOP"):
    return {"candidates": [{"finishReason": finish, "content": {"parts": [
        {"text": "内部推理不应归档", "thought": True}, {"text": text}]}}]}


text = "00:01 Speaker 1: 数字1.0。\n[00:03] Speaker ?: [听不清]\n- 00:09 Speaker 2: 保留原话。"
expected = "[00:01] Speaker 1: 数字1.0。\n[00:03] Speaker ?: [听不清]\n- [00:09] Speaker 2: 保留原话。"
assert normalize_timestamp_brackets(text) == expected
assert normalize_timestamp_brackets(expected) == expected
with tempfile.TemporaryDirectory(prefix="plaud-gemini-smoke-") as folder:
    root = Path(folder)
    good = root / "good"
    summary = publish_response(b"same-audio", good, "gemini-pro-agent", response(text), 30, 1.5)
    assert summary["audio_sha256"] == hashlib.sha256(b"same-audio").hexdigest()
    assert summary["timing"]["valid"] and summary["timestamp_brackets_normalized"]
    assert (good / "gemini-raw-transcript.md").read_text() == text + "\n"
    assert (good / "gemini-transcript.md").read_text().endswith(expected + "\n")
    assert "内部推理" not in (good / "gemini-transcript.md").read_text()
    cases = {
        "blocked": {"promptFeedback": {"blockReason": "OTHER", "blockReasonMessage": "full diagnostic"}},
        "truncated": response("[00:01] Speaker 1: 未完成", "MAX_TOKENS"),
        "out_of_range": response("[00:30] Speaker 1: 不裁剪时间"),
        "backwards": response("[00:09] Speaker 1: 原话\n[00:01] Speaker 2: 原话"),
        "no_timestamps": response("只有说明，不是带时间的逐字稿"),
    }
    for name, wire in cases.items():
        output = root / name
        try:
            publish_response(b"same-audio", output, "gemini-pro-agent", wire, 30, 1.5)
        except RuntimeError:
            pass
        else:
            raise AssertionError(name + " must fail")
        assert not (output / "gemini-summary.json").exists()
        assert not (output / "gemini-transcript.md").exists()
    diagnostic = json.loads((root / "blocked/gemini-response-diagnostic.json").read_text())
    assert diagnostic["prompt_feedback"]["blockReasonMessage"] == "full diagnostic"
    audio = root / 'continuous.mp3'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','anullsrc=r=16000:cl=mono',
                    '-t','625','-b:a','32k',str(audio)], check=True)
    output = root / 'continuous'
    calls = []
    def fake_post(request, **kwargs):
        assert json.loads(request.data)['generationConfig']['responseMimeType'] == 'application/json'
        calls.append(request.full_url)
        if len(calls) == 3:
            raise TimeoutError('temporary upstream interruption')
        content = '[00:09] Speaker 1: 保留失败原稿\n[00:01] Speaker 2: 时间倒序' if len(calls) == 2 else '[00:01] Speaker 1: 原话'
        return io.BytesIO(json.dumps(response(content)).encode())
    argv = ['gemini_native','--audio',str(audio),'--output',str(output),'--model','test-model','--url','http://unused.invalid/v1/chat/completions']
    with patch.dict(os.environ, {'CPA_PUBLIC_API_KEY':'smoke-not-a-real-key'}), \
         patch.object(sys,'argv',argv), patch.object(native.urllib.request,'urlopen',side_effect=fake_post):
        try: native.main()
        except (RuntimeError, TimeoutError): pass
        else: raise AssertionError('backwards part must block the whole transcript')
        assert not (output/'gemini-summary.json').exists()
        native.main()
        assert len(calls) == 6  # First part reused; invalid timing retried as two halves.
        saved = json.loads((output/'gemini-summary.json').read_text())
        assert saved['parts'] == 3 and saved['timing']['valid']
        text = (output/'gemini-transcript.md').read_text()
        assert all(t in text for t in ('[00:01]', '[05:01]', '[10:01]'))
        assert list((output/'gemini-parts').glob('*/001/gemini-response-history/*/gemini-raw-transcript.md'))
        argv[argv.index('test-model')] = 'changed-model'
        native.main()
        assert len(calls) == 9
        assert len(list((output/'gemini-parts').iterdir())) == 2
    srt = '[00:00.670 --> 00:04.140] 原话\n[00:04,380 --> 00:08,000] Speaker 2: 保留原话'
    srt_state = publish_response(b'srt-audio',root/'srt','model',response(srt),30,1)
    assert srt_state['timing']['valid'] and srt_state['timing']['parsed_turns'] == 2
    turns = native.parse_gemini(srt,30)
    assert turns[0]['start'] == .670 and turns[0]['end'] == 4.140 and turns[0]['speaker'] == '?'
    assert native.turn_line(turns[0],300) == '[05:00.670 --> 05:04.140] Speaker ?: 原话'
    assert native.parse_gemini('[00:01:832 --> 00:06:552] Speaker 1: 原话',30)[0]['start'] == 1.832
    assert not native.inspect_gemini('[03:49:17] Speaker 1: 不擅自改成分秒',300)['valid']
    assert not native.inspect_gemini('[00:99] Speaker 1: 错误时间',300)['valid']
    # Reparse an old saved SRT response without calling the provider again.
    legacy_part = root/'legacy-srt';legacy_part.mkdir()
    (legacy_part/'audio.mp3').write_bytes(b'srt-audio')
    (legacy_part/'gemini-raw-transcript.md').write_text(srt)
    (legacy_part/'gemini-response-diagnostic.json').write_text(json.dumps({'model':'model',
        'audio_sha256':hashlib.sha256(b'srt-audio').hexdigest(),'finish_reasons':['STOP']}))
    with patch.object(native.urllib.request,'urlopen',side_effect=AssertionError('must reuse saved response')):
        native.transcribe_part(audio,legacy_part,0,30,'model','http://unused.invalid','smoke-key')
    assert json.loads((legacy_part/'gemini-summary.json').read_text())['revalidated_saved_response']
    structured_text = json.dumps({'turns':[{'start_seconds':1.832,'speaker':'?','text':'保留原话'},
                                         {'start_seconds':6.552,'speaker':'2','text':'数字123。'}]},ensure_ascii=False)
    state = publish_response(b'json-audio',root/'json','model',response(structured_text),30,1)
    assert state['structured_transcript'] and state['timing']['valid']
    assert (root/'json/gemini-raw-transcript.md').read_text() == structured_text+'\n'
    clock_text = json.dumps({'turns':[{'start_timestamp':'01:08.312','speaker':'?','text':'明确的分秒毫秒'}]},ensure_ascii=False)
    state = publish_response(b'clock-audio',root/'clock','model',response(clock_text),75,1)
    assert state['timing']['valid'] and state['timing']['last_timestamp_seconds'] == 68.312
    assert (root/'clock/gemini-raw-transcript.md').read_text() == clock_text+'\n'
    short_clock = json.dumps({'turns':[{'start_timestamp':'1:08.312','speaker':'?','text':'合法单数字分钟'}]},ensure_ascii=False)
    state = publish_response(b'clock-audio',root/'short-clock','model',response(short_clock),75,1)
    assert state['timing']['valid'] and state['timing']['last_timestamp_seconds'] == 68.312
    for value in ('01:75.000','01:15.000','00:00:100',68.312):
        bad = json.dumps({'turns':[{'start_timestamp':value,'speaker':'1','text':'不得改写错误时间'}]})
        try: publish_response(b'clock-audio',root/'bad-clock','model',response(bad),75,1)
        except RuntimeError: pass
        else: raise AssertionError('invalid clock timestamp must fail')
    for value in (True,-1,30, '00:01',float('nan')):
        bad = json.dumps({'turns':[{'start_seconds':value,'speaker':'1','text':'不得放宽时间'}]})
        try: publish_response(b'json-audio',root/'bad-json','model',response(bad),30,1)
        except RuntimeError: pass
        else: raise AssertionError('invalid structured time must fail')
print("smoke OK: exact timestamp bracketing, raw preservation, blocked/truncated/invalid source rejection; no network")
