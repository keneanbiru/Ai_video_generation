"""v2 tests: quota ledger, Gemini retry parsing, batch narration splitting, script draft safety. No API calls."""
import json

import numpy as np
import pytest
import soundfile as sf

from pipeline import common, narration, quota


def test_quota_wait_parser():
    assert narration._quota_wait("Please retry in 58s or upgrade") == 58
    assert narration._quota_wait("Please retry in 23h4m31s or") == 23 * 3600 + 4 * 60 + 31
    assert narration._quota_wait("no hint here") is None


def _row(model, status="ok", error=None, ts="2026-11-26T12:00:00+0300"):
    return json.dumps({"ts": ts, "model": model, "status": status, "error": error}) + "\n"


def test_ledger_counts_like_the_dashboard(tmp_path, monkeypatch):
    runs = tmp_path / "runs.jsonl"
    runs.write_text(_row("m") + _row("m", "error", "503 high demand") + _row("m", "error", "429 Rate limit")
                    + _row("m", "unavailable") + _row("other"))
    monkeypatch.setattr(quota, "RUNS", runs)
    monkeypatch.setattr(quota, "ADJUST", tmp_path / "none.json")
    monkeypatch.setattr(quota, "quota_day", lambda now=None: "2026-11-26")
    assert quota.used_today("m") == 2  # ok + 503 count; 429 and 'unavailable' do not


def test_guard_refuses_experiments_below_reserve(monkeypatch):
    monkeypatch.setattr(quota, "remaining", lambda m: 8)
    monkeypatch.setenv("GEMINI_TTS_RESERVE", "8")
    with pytest.raises(common.ProviderUnavailable):
        quota.guard("gemini-3.8-flash-lite-tts", "experiment")
    quota.guard("gemini-3.8-flash-lite-tts", "film")  # the film may spend it


def test_batch_split_on_synthetic_take(tmp_path, monkeypatch):
    """Three 'lines' of tone separated by 2 s silences must split into 3 pieces of the right length."""
    sr = 24000
    tone = lambda s: 0.3 * np.sin(2 * np.pi * 220 * np.arange(int(s * sr)) / sr)  # noqa: E731
    gap = np.zeros(2 * sr)
    take = np.concatenate([tone(3.0), gap, tone(1.5), gap, tone(4.5)])

    def fake_tts(text, lang, out, item, ck, voice=None):
        sf.write(out, take, sr)
        return {"voice": "test"}

    monkeypatch.setattr(narration, "tts_gemini", fake_tts)
    lines = [("a", "x" * 30), ("b", "x" * 15), ("c", "x" * 45)]
    res = narration.gemini_batch(lines, tmp_path, None, {k: "ck" for k, _ in lines})
    assert set(res) == {"a", "b", "c"}
    assert all(0.7 < v["ratio"] < 1.5 for v in res.values())
    assert (tmp_path / "b.wav").exists() and common.cache_hit(tmp_path / "b.wav", "ck")


def test_batch_split_rejects_wrong_gap_count(tmp_path, monkeypatch):
    sr = 24000
    take = 0.3 * np.sin(2 * np.pi * 220 * np.arange(6 * sr) / sr)  # no silences at all

    def fake_tts(text, lang, out, item, ck, voice=None):
        sf.write(out, take, sr)
        return {}

    monkeypatch.setattr(narration, "tts_gemini", fake_tts)
    with pytest.raises(ValueError):
        narration.gemini_batch([("a", "x"), ("b", "y")], tmp_path, None, {"a": "1", "b": "2"})


def test_script_accept_refuses_invalid_draft(tmp_path, monkeypatch):
    from pipeline import script

    bad = tmp_path / "draft.json"
    bad.write_text("{}")
    monkeypatch.setattr(script, "DRAFT", bad)
    with pytest.raises(common.StoryboardError):
        script.accept()


def test_script_draft_repairs_invalid_json_and_never_touches_storyboard(tmp_path, monkeypatch):
    """Mocked Gemini: first returns an invalid storyboard, then a valid one. No API call is made."""
    from pipeline import script

    good = json.loads(common.STORYBOARD.read_text(encoding="utf-8"))
    bad = json.loads(json.dumps(good))
    del bad["shots"][0]["seed"]  # schema violation
    replies = iter([(bad, "mock-flash"), (good, "mock-flash")])
    calls = []

    def fake_gemini_json(prompt, item, stage="script"):
        calls.append(item)
        return next(replies)

    before = common.STORYBOARD.read_bytes()
    monkeypatch.setattr(script, "gemini_json", fake_gemini_json)
    monkeypatch.setattr(script, "DRAFT", tmp_path / "draft.json")
    story = tmp_path / "story.md"
    story.write_text("test story")
    out = script.draft(story, "amh", "Amharic", 75, 1.35)
    assert calls == ["draft", "draft-repair-1"]
    common.load_storyboard(out)  # the repaired draft validates
    assert common.STORYBOARD.read_bytes() == before  # the contract is never written by the model


def test_remote_wan_submits_nothing_when_clips_are_current(tmp_path, monkeypatch):
    """Every requested clip already matches its keyframe hash, motion prompt and size -> no Kaggle job."""
    from pipeline import remote

    from PIL import Image

    sb = common.load_storyboard()
    kfs = {}
    for i, s in enumerate(sb["shots"]):  # self-contained keyframes: the test must not depend on outputs/
        kfs[s["id"]] = tmp_path / f"{s['id']}.png"
        Image.new("RGB", (8, 8), (i, i, i)).save(kfs[s["id"]])
    clips = tmp_path / "clips_wan"
    clips.mkdir()
    for s in sb["shots"][:2]:
        (clips / f"{s['id']}.json").write_text(json.dumps({
            "keyframe_sha16": common.file_hash(kfs[s["id"]]), "motion_prompt": s["motion_prompt"],
            "params": {"size": 640}}))
    monkeypatch.setattr(remote, "OUT", tmp_path)
    import pipeline.keyframes as kf

    monkeypatch.setattr(kf, "keyframes", lambda sb, only=None, force=False: kfs)

    def boom(*a, **k):
        raise AssertionError("a GPU job was submitted although nothing changed")

    monkeypatch.setattr(remote, "publish_inputs", boom)
    monkeypatch.setattr(remote, "run_kernel", boom)
    remote.wan([s["id"] for s in sb["shots"][:2]], 640, 81, 30)  # must return without submitting


def test_batch_split_when_line_gaps_equal_inner_pauses(tmp_path, monkeypatch):
    """E22 regression: the model left the same ~0.6 s between lines as inside them. Picking the
    N-1 longest pauses fails; length-aligned cuts must still recover the lines."""
    sr = 24000
    tone = lambda s: 0.3 * np.sin(2 * np.pi * 220 * np.arange(int(s * sr)) / sr)  # noqa: E731
    gap = lambda s: np.zeros(int(s * sr))  # noqa: E731
    # line A = 2 words with an inner pause; line B = 1 word; line C = 3 words with inner pauses
    take = np.concatenate([tone(1.5), gap(0.65), tone(1.5), gap(0.6),       # A (3.0 s voiced) | cut
                           tone(1.5), gap(0.6),                              # B (1.5 s)         | cut
                           tone(1.5), gap(0.7), tone(1.5), gap(0.65), tone(1.5)])  # C (4.5 s)

    def fake_tts(text, lang, out, item, ck, voice=None):
        sf.write(out, take, sr)
        return {}

    monkeypatch.setattr(narration, "tts_gemini", fake_tts)
    lines = [("a", "x" * 20), ("b", "x" * 10), ("c", "x" * 30)]  # chars proportional to voiced length
    res = narration.gemini_batch(lines, tmp_path, None, {k: "ck" for k, _ in lines})
    assert abs(res["a"]["dur"] - 3.65) < 0.3 and abs(res["b"]["dur"] - 1.5) < 0.3 and abs(res["c"]["dur"] - 5.85) < 0.3


def test_offline_never_overwrites_hosted_narration(tmp_path, monkeypatch):
    """F16: with Gemini unavailable, cached Gemini lines are kept, not replaced by the MMS fallback."""
    sb = common.load_storyboard()
    monkeypatch.setattr(narration, "stage_paths", lambda name: tmp_path)
    monkeypatch.setenv("HERITAGE_OFFLINE", "1")
    lines = [s for s in sb["shots"] if s["narration"]]
    for s in lines:  # pretend every line has a cached Gemini take
        p = tmp_path / f"{s['id']}.wav"
        sf.write(p, np.zeros(2400), 24000)
        ck = common.cache_key(stage="narration", text=s["narration"].strip(), lang=sb["film"]["language"],
                              provider="gemini-tts", voice=narration.voice_settings("gemini-tts", sb.get("voice")))
        common.cache_write(p, ck, provider="gemini-tts")
    monkeypatch.setattr(narration, "tts_mms", lambda *a, **k: (_ for _ in ()).throw(AssertionError("MMS called")))
    monkeypatch.setitem(narration.IMPLS, "local:mms-tts", narration.tts_mms)
    out = narration.narration(sb)
    assert len(out) == len(lines)
    assert all(common.cache_meta(p)["provider"] == "gemini-tts" for p in out.values())
