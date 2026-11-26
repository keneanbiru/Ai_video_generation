"""Fast tests (no models): the storyboard contract, caching keys, timeline and subtitle rules."""
import copy
import json
from pathlib import Path

import pytest

from pipeline import common
from pipeline.common import StoryboardError, cache_hit, cache_key, cache_write, expand_prompt, load_storyboard

ROOT = Path(__file__).resolve().parent.parent


def sb():
    return json.loads((ROOT / "storyboard.json").read_text(encoding="utf-8"))


def write(tmp_path, data):
    p = tmp_path / "sb.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


def test_storyboard_is_valid():
    s = load_storyboard()
    assert 8 <= len(s["shots"]) <= 12


def test_every_shot_has_a_reason_and_subtitle():
    for s in sb()["shots"]:
        assert len(s["reason"]) > 10
        if s["narration"]:
            assert s["subtitle_en"]


def test_schema_rejects_missing_field(tmp_path):
    d = sb()
    del d["shots"][0]["seed"]
    with pytest.raises(StoryboardError):
        load_storyboard(write(tmp_path, d))


def test_unknown_character_rejected(tmp_path):
    d = sb()
    d["shots"][1]["characters"] = ["nobody"]
    with pytest.raises(StoryboardError):
        load_storyboard(write(tmp_path, d))


def test_real_person_requires_consent(tmp_path):
    d = sb()
    d["characters"]["emama"]["real_person"] = True  # no consent_ref -> schema error
    with pytest.raises(StoryboardError):
        load_storyboard(write(tmp_path, d))
    d["characters"]["emama"]["consent_ref"] = "consent-does-not-exist-xyz"
    with pytest.raises(StoryboardError, match="consent"):
        load_storyboard(write(tmp_path, d))


def test_chosen_music_must_be_candidate(tmp_path):
    d = sb()
    d["music"]["chosen"] = 99999
    with pytest.raises(StoryboardError):
        load_storyboard(write(tmp_path, d))


def test_style_block_on_every_prompt_and_characters_expanded():
    d = sb()
    for s in d["shots"]:
        p = expand_prompt(d, s)
        assert p.endswith(d["style"]["style_block"])
        assert "{" not in p


def test_cache_key_changes_only_with_inputs(tmp_path):
    a = cache_key(prompt="x", seed=1)
    assert a == cache_key(seed=1, prompt="x")  # order-independent
    assert a != cache_key(prompt="x", seed=2)
    f = tmp_path / "o.png"
    f.write_bytes(b"1")
    assert not cache_hit(f, a)
    cache_write(f, a)
    assert cache_hit(f, a)
    assert not cache_hit(f, cache_key(prompt="y", seed=1))


def test_editing_one_narration_line_changes_one_key():
    d = sb()
    d2 = copy.deepcopy(d)
    d2["shots"][4]["narration"] += " ዛሬ።"
    keys = lambda s: [cache_key(stage="narration", text=x["narration"]) for x in s["shots"]]
    diff = [i for i, (x, y) in enumerate(zip(keys(d), keys(d2))) if x != y]
    assert diff == [4]


def test_srt_two_lines_max(tmp_path):
    from pipeline.assemble import srt

    tl = {"shots": [{"id": "s01", "narration_start": 0.4, "narration_s": 6.0,
                     "subtitle_en": "word " * 30}]}
    text = srt(tl, tmp_path / "x.srt").read_text()
    for block in text.strip().split("\n\n"):
        body = block.splitlines()[2:]
        assert len(body) <= 2
        assert all(len(l) <= 40 for l in body)


def test_prompts_fit_clip_77_tokens():
    """F08: longer prompts are silently truncated, dropping the style block at the end."""
    from pipeline.common import model_path

    if model_path("stabilityai/sd-turbo") == "stabilityai/sd-turbo":
        pytest.skip("SD-Turbo tokenizer not downloaded")
    from pipeline.keyframes import check_prompt_lengths

    check_prompt_lengths(load_storyboard())
