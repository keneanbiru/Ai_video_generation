"""Stage 6: assembly. Deterministic FFmpeg only, no model calls.

  radio cut : narration over placeholder music on black (the audio animatic for user test 1)
  final     : picture cut to the voice, score ducked under narration (sidechaincompress),
              two-pass loudnorm to -14 LUFS / -1 dBTP, burned-in English subtitles inside the
              vertical safe area, AI end card, exported 16:9 and 9:16 (H.264 + AAC, CFR 24 fps).
"""
from __future__ import annotations

import json
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .common import OUT, duration_s, ffmpeg, ffmpeg_bin, log, loudness, run, stage_paths
from .shots import FPS, RATIOS

TARGET_LUFS, TARGET_TP = -14.0, -1.0
FONT_LATIN = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_ETHIOPIC = "/usr/share/fonts/truetype/noto/NotoSansEthiopic-Regular.ttf"


# --------------------------------------------------------------------------- audio
def narration_track(timeline: dict, narr: dict[str, Path], out: Path) -> Path:
    items = [(t, narr[t["id"]]) for t in timeline["shots"] if t["narration_start"] is not None]
    inputs, labels, parts = [], [], []
    for i, (t, p) in enumerate(items):
        inputs += ["-i", str(p)]
        ms = int(t["narration_start"] * 1000)
        parts.append(f"[{i}:a]adelay={ms}|{ms},apad[a{i}]")
        labels.append(f"[a{i}]")
    parts.append(f"{''.join(labels)}amix=inputs={len(items)}:normalize=0:duration=longest,"
                 f"atrim=0:{timeline['total_s']:.3f}[out]")
    ffmpeg(*inputs, "-filter_complex", ";".join(parts), "-map", "[out]", "-ar", "48000", "-ac", "1", str(out))
    return out


def placeholder_music(total: float, out: Path) -> Path:
    """Temp track for the radio cut: a soft two-note drone. Not used in the final film."""
    ffmpeg("-f", "lavfi", "-i", f"sine=f=110:d={total}", "-f", "lavfi", "-i", f"sine=f=164.8:d={total}",
           "-filter_complex", "[0][1]amix=inputs=2,tremolo=f=0.2:d=0.4,lowpass=f=900,volume=0.25,"
           f"afade=t=in:d=2,afade=t=out:st={max(0, total - 3)}:d=3[o]", "-map", "[o]", "-ar", "48000", "-ac", "2",
           str(out))
    return out


def mix(music: Path, narration: Path, duck: dict, out: Path) -> dict:
    """Duck music under narration, sum, then two-pass loudness normalisation."""
    pre = out.with_name(out.stem + ".premix.wav")
    fc = (f"[0:a]volume={duck['bed_gain_db']}dB[m];"
          f"[1:a]aformat=channel_layouts=stereo,asplit=2[v1][v2];"
          f"[m][v1]sidechaincompress=threshold={duck['threshold']}:ratio={duck['ratio']}:"
          f"attack={duck['attack_ms']}:release={duck['release_ms']}:makeup=1[ducked];"
          f"[ducked][v2]amix=inputs=2:normalize=0:duration=first[o]")
    ffmpeg("-i", str(music), "-i", str(narration), "-filter_complex", fc, "-map", "[o]", "-ar", "48000", str(pre))
    # pass 1: measure
    p = run([ffmpeg_bin(), "-hide_banner", "-i", str(pre), "-af",
             f"loudnorm=I={TARGET_LUFS}:TP={TARGET_TP}:LRA=11:print_format=json", "-f", "null", "-"])
    txt = p.stderr
    m = json.loads(txt[txt.rfind("{"): txt.rfind("}") + 1])
    # pass 2: apply with measured values (linear mode keeps dynamics intact)
    ffmpeg("-i", str(pre), "-af",
           f"loudnorm=I={TARGET_LUFS}:TP={TARGET_TP}:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
           f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:"
           f"linear=true", "-ar", "48000", str(out))
    pre.unlink(missing_ok=True)
    return {"pass1": {k: m[k] for k in ("input_i", "input_tp", "input_lra")}, "final": loudness(out)}


# --------------------------------------------------------------------------- subtitles
def _ts(t: float) -> str:
    h, r = divmod(t, 3600)
    m, s = divmod(r, 60)
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int(round((s - int(s)) * 1000)):03d}"


def srt(timeline: dict, out: Path) -> Path:
    blocks = []
    n = 0
    for t in timeline["shots"]:
        if t["narration_start"] is None or not t["subtitle_en"]:
            continue
        n += 1
        start, end = t["narration_start"], t["narration_start"] + t["narration_s"] + 0.4
        lines = textwrap.wrap(t["subtitle_en"], 40)
        if len(lines) > 2:  # keep to two lines: split into two timed cards
            half = len(lines) // 2
            mid = start + (end - start) * (len(" ".join(lines[:half])) / len(t["subtitle_en"]))
            blocks.append(f"{n}\n{_ts(start)} --> {_ts(mid)}\n" + "\n".join(lines[:half]))
            n += 1
            blocks.append(f"{n}\n{_ts(mid)} --> {_ts(end)}\n" + "\n".join(lines[half:]))
        else:
            blocks.append(f"{n}\n{_ts(start)} --> {_ts(end)}\n" + "\n".join(lines))
    out.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
    return out


def _sub_style(ratio: str) -> str:
    # libass scales against PlayResY=288. Vertical: smaller text, raised well above the bottom
    # ~20% where TikTok/Reels/Shorts put captions and buttons.
    if ratio == "9x16":
        return "FontName=DejaVu Sans,FontSize=8.5,Outline=1.2,Shadow=0,MarginV=70,MarginL=14,MarginR=14,BorderStyle=1"
    return "FontName=DejaVu Sans,FontSize=13,Outline=1.2,Shadow=0,MarginV=18,BorderStyle=1"


# --------------------------------------------------------------------------- picture
def end_card(sb: dict, ratio: str, out: Path) -> Path:
    w, h = RATIOS[ratio]
    img = Image.new("RGB", (w, h), (28, 20, 16))
    d = ImageDraw.Draw(img)
    lines = sb["end_card"]["lines"]
    big = int(min(w, h) * 0.075)
    small = int(min(w, h) * 0.038)
    y = h * 0.36
    for i, line in enumerate(lines):
        size = big if i < 2 else small
        # Ethiopic glyphs need an Ethiopic font; Latin text uses DejaVu.
        has_eth = any("ሀ" <= ch <= "᎟" for ch in line)
        if has_eth and " · " in line:
            eth, lat = line.split(" · ", 1)
            f1, f2 = ImageFont.truetype(FONT_ETHIOPIC, size), ImageFont.truetype(FONT_LATIN, int(size * 0.6))
            tw = d.textlength(eth, font=f1)
            d.text(((w - tw) / 2, y), eth, font=f1, fill=(240, 214, 170))
            y += size * 1.25
            tw = d.textlength(lat, font=f2)
            d.text(((w - tw) / 2, y), lat, font=f2, fill=(240, 214, 170))
            y += size * 1.1
            continue
        font = ImageFont.truetype(FONT_LATIN, size)
        for sub in textwrap.wrap(line, 34 if ratio == "9x16" else 60):
            tw = d.textlength(sub, font=font)
            d.text(((w - tw) / 2, y), sub, font=font, fill=(250, 245, 235) if i == 1 else (200, 190, 175))
            y += size * 1.35
        y += size * 0.5
    png = out.with_suffix(".png")
    img.save(png)
    dur = sb["end_card"]["duration_s"]
    ffmpeg("-loop", "1", "-i", str(png), "-vf", f"fade=t=in:d=0.6,format=yuv420p", "-t", str(dur), "-r", str(FPS),
           "-c:v", "libx264", "-crf", "18", "-an", str(out))
    return out


def concat(clips: list[Path], out: Path) -> Path:
    lst = out.with_suffix(".txt")
    lst.write_text("".join(f"file '{c.resolve()}'\n" for c in clips))
    ffmpeg("-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(out))
    return out


# --------------------------------------------------------------------------- top level
def radio_cut(sb: dict, timeline: dict, narr: dict[str, Path]) -> Path:
    d = stage_paths("radio_cut")
    nar = narration_track(timeline, narr, d / "narration.wav")
    temp = placeholder_music(timeline["total_s"], d / "temp_music.wav")
    loud = mix(temp, nar, sb["music"]["duck"], d / "mix.wav")
    sub = srt(timeline, d / "radio_cut.srt")
    out = d / "radio_cut.mp4"
    ffmpeg("-f", "lavfi", "-i", f"color=c=black:s=1280x720:r={FPS}:d={timeline['total_s']}", "-i", str(d / "mix.wav"),
           "-vf", f"subtitles={sub}:force_style='{_sub_style('16x9')}'", "-c:v", "libx264", "-crf", "28",
           "-c:a", "aac", "-b:a", "160k", "-shortest", str(out))
    (d / "qc.json").write_text(json.dumps({"duration_s": duration_s(out), "loudness": loud}, indent=1))
    log(f"  radio cut: {out.relative_to(OUT.parent)} ({duration_s(out):.1f}s, {loud['final']})")
    return out


def final(sb: dict, timeline: dict, narr: dict[str, Path], shot_clips: dict[str, dict[str, Path]],
          music_bed: Path) -> dict[str, Path]:
    d = stage_paths("final")
    nar = narration_track(timeline, narr, d / "narration.wav")
    loud = mix(music_bed, nar, sb["music"]["duck"], d / "mix.wav")
    sub = srt(timeline, d / "subtitles_en.srt")
    outs, qc = {}, {"loudness": loud, "exports": {}}
    for ratio in RATIOS:
        ec = end_card(sb, ratio, d / f"endcard_{ratio}.mp4")
        clips = [shot_clips[ratio][s["id"]] for s in sb["shots"]] + [ec]
        pic = concat(clips, d / f"picture_{ratio}.mp4")
        out = OUT / f"film_{ratio}.mp4"
        total = timeline["total_s"]
        vf = (f"fade=t=in:d=1.0,subtitles={sub}:force_style='{_sub_style(ratio)}',format=yuv420p")
        ffmpeg("-i", str(pic), "-i", str(d / "mix.wav"), "-vf", vf, "-r", str(FPS), "-c:v", "libx264",
               "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
               "-t", f"{total:.3f}", "-movflags", "+faststart", str(out))
        outs[ratio] = out
        qc["exports"][ratio] = {"file": out.name, "duration_s": round(duration_s(out), 3),
                                "loudness": loudness(out), "size_mb": round(out.stat().st_size / 1e6, 2)}
        log(f"  final {ratio}: {out.relative_to(OUT.parent)} {qc['exports'][ratio]}")
    (OUT / "qc.json").write_text(json.dumps(qc, indent=1))
    return outs
