"""Shared plumbing for every stage: the storyboard contract, caching, logging and retries.

Design rules (see ARCHITECTURE.md):
  * storyboard.json is read-only for stages. Stages write only under outputs/.
  * Every generated artifact sits at a stable path with a sidecar <file>.cache.json
    holding the hash of everything that produced it. Same hash -> reuse, no model call.
  * Every model call (success or failure) appends exactly one line to runs.jsonl.
"""
from __future__ import annotations

import functools
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
STORYBOARD = ROOT / "storyboard.json"
SCHEMA = ROOT / "schema" / "storyboard.schema.json"
OUT = ROOT / "outputs"
RUNS = ROOT / "runs.jsonl"
PIPELINE_LOG = OUT / "pipeline.log"

# One id per invocation of the pipeline so runs.jsonl lines can be grouped.
RUN_ID = os.environ.get("HERITAGE_RUN_ID") or time.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]

# Load .env if present (secrets live there, never in the repo; .env is git-ignored).
try:
    from dotenv import load_dotenv  # type: ignore

    load_dotenv(ROOT / ".env")
except Exception:  # dotenv is optional
    pass


# --------------------------------------------------------------------------- logging
def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    with open(PIPELINE_LOG, "a", encoding="utf-8") as f:
        f.write(f"{RUN_ID} {line}\n")


def log_call(**fields: Any) -> None:
    """Append one model call to runs.jsonl. Required keys are filled with defaults."""
    rec = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "run_id": RUN_ID,
        "stage": None,
        "item": None,
        "provider": None,
        "model": None,
        "params": {},
        "seed": None,
        "latency_s": None,
        "device": None,
        "compute_s": None,
        "cost_usd": 0.0,
        "list_price_usd": None,
        "status": "ok",
        "cache_key": None,
        "output": None,
        "error": None,
    }
    rec.update(fields)
    with open(RUNS, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# --------------------------------------------------------------------------- storyboard
class StoryboardError(ValueError):
    pass


def load_storyboard(path: Path = STORYBOARD) -> dict:
    """Load and validate the storyboard. Every stage calls this first."""
    import jsonschema

    with open(path, encoding="utf-8") as f:
        sb = json.load(f)
    with open(SCHEMA, encoding="utf-8") as f:
        schema = json.load(f)
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(sb), key=lambda e: list(e.path))
    if errors:
        msgs = [f"  - {'/'.join(map(str, e.path)) or '<root>'}: {e.message}" for e in errors]
        raise StoryboardError("storyboard.json failed schema validation:\n" + "\n".join(msgs))
    _semantic_checks(sb)
    return sb


def _semantic_checks(sb: dict) -> None:
    """Rules JSON Schema cannot express."""
    problems = []
    ids = [s["id"] for s in sb["shots"]]
    if len(ids) != len(set(ids)):
        problems.append("shot ids must be unique")
    chars = set(sb["characters"])
    for s in sb["shots"]:
        for c in s["characters"]:
            if c not in chars:
                problems.append(f"{s['id']}: unknown character '{c}'")
        for c in chars:
            if "{" + c + "}" in s["image_prompt"] and c not in s["characters"]:
                problems.append(f"{s['id']}: prompt uses {{{c}}} but '{c}' not listed in characters")
        if s.get("narration") and not s.get("subtitle_en"):
            problems.append(f"{s['id']}: narration without an English subtitle")
    m = sb["music"]
    if m["chosen"] not in m["candidates"]:
        problems.append("music.chosen must be one of music.candidates")
    for cue in m["cues"]:
        if cue["at_shot"] not in ids:
            problems.append(f"music cue refers to unknown shot {cue['at_shot']}")
    for name, c in sb["characters"].items():
        if c["real_person"]:
            ethics = (ROOT / "ETHICS.md").read_text(encoding="utf-8") if (ROOT / "ETHICS.md").exists() else ""
            if c.get("consent_ref", "") not in ethics or not c.get("consent_ref"):
                problems.append(f"character '{name}' is a real person but consent_ref is not found in ETHICS.md")
    if problems:
        raise StoryboardError("storyboard.json failed semantic checks:\n" + "\n".join("  - " + p for p in problems))


def expand_prompt(sb: dict, shot: dict) -> str:
    """Shot prompt with character descriptions substituted and the style block appended unchanged."""
    p = shot["image_prompt"]
    for name, c in sb["characters"].items():
        p = p.replace("{" + name + "}", c["description"])
    return f"{p}, {sb['style']['style_block']}"


# --------------------------------------------------------------------------- caching
def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def cache_key(**inputs: Any) -> str:
    blob = json.dumps(inputs, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _sidecar(path: Path) -> Path:
    return path.with_name(path.name + ".cache.json")


def cache_hit(path: Path, key: str) -> bool:
    sc = _sidecar(path)
    if not (path.exists() and sc.exists()):
        return False
    try:
        return json.loads(sc.read_text())["key"] == key
    except Exception:
        return False


def cache_meta(path: Path) -> dict:
    sc = _sidecar(path)
    return json.loads(sc.read_text()) if sc.exists() else {}


def cache_write(path: Path, key: str, **meta: Any) -> None:
    _sidecar(path).write_text(json.dumps({"key": key, **meta}, ensure_ascii=False, indent=1, default=str))


# --------------------------------------------------------------------------- retries
class ProviderUnavailable(RuntimeError):
    """Raised when a provider cannot run at all here (no key, no GPU output). Not retried."""


def retry(times: int = 3, base_delay: float = 2.0, retry_on: tuple = (Exception,)):
    """Exponential backoff. ProviderUnavailable is never retried: it falls through to the next provider."""

    def deco(fn: Callable):
        @functools.wraps(fn)
        def wrapper(*a, **kw):
            last = None
            for attempt in range(1, times + 1):
                try:
                    return fn(*a, **kw)
                except ProviderUnavailable:
                    raise
                except retry_on as e:  # noqa: PERF203
                    last = e
                    if attempt == times:
                        break
                    delay = base_delay * (2 ** (attempt - 1))
                    log(f"  retry {attempt}/{times - 1} for {fn.__name__} after error: {e!r}; sleeping {delay:.0f}s")
                    time.sleep(delay)
            raise last  # type: ignore[misc]

        return wrapper

    return deco


def run_chain(stage: str, chain: list[str], impls: dict[str, Callable[..., Any]], *args, **kwargs):
    """Try providers in order; return (provider_name, result). Failures are logged and fall through."""
    errors = []
    for name in chain:
        family = name.split(":", 1)[0] if name.split(":", 1)[0] in impls else name
        fn = impls.get(name) or impls.get(family)
        if fn is None:
            errors.append(f"{name}: not implemented")
            continue
        try:
            return name, fn(name, *args, **kwargs)
        except ProviderUnavailable as e:
            log(f"  [{stage}] provider {name} unavailable: {e}")
            errors.append(f"{name}: unavailable ({e})")
        except Exception as e:  # provider failed after retries; try the next one
            log(f"  [{stage}] provider {name} failed: {e!r}")
            errors.append(f"{name}: failed ({e!r})")
    raise RuntimeError(f"[{stage}] every provider failed: " + "; ".join(errors))


# --------------------------------------------------------------------------- ffmpeg helpers
def ffmpeg_bin(name: str = "ffmpeg") -> str:
    exe = shutil.which(name) or shutil.which(name, path=str(Path(sys.executable).parent))
    if not exe:
        raise RuntimeError(f"{name} not found on PATH")
    return exe


def run(cmd: list[str], quiet: bool = True) -> subprocess.CompletedProcess:
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"command failed ({p.returncode}): {' '.join(cmd[:6])} ...\n{p.stderr[-3000:]}")
    if not quiet:
        print(p.stdout)
    return p


def ffmpeg(*args: str) -> subprocess.CompletedProcess:
    return run([ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y", *args])


def duration_s(path: Path) -> float:
    p = run([ffmpeg_bin("ffprobe"), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)])
    return float(p.stdout.strip())


def loudness(path: Path) -> dict:
    """Integrated loudness (LUFS) and true peak (dBTP) via ffmpeg's ebur128 filter."""
    p = subprocess.run(
        [ffmpeg_bin(), "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128=peak=true", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    txt = p.stderr
    out: dict[str, float] = {}
    tail = txt[txt.rfind("Summary:"):]
    for line in tail.splitlines():
        line = line.strip()
        if line.startswith("I:"):
            out["integrated_lufs"] = float(line.split()[1])
        elif line.startswith("LRA:"):
            out["lra_lu"] = float(line.split()[1])
        elif line.startswith("Peak:"):
            out["true_peak_dbtp"] = float(line.split()[1])
    return out


def stage_paths(stage: str) -> Path:
    p = OUT / stage
    p.mkdir(parents=True, exist_ok=True)
    return p


def device_name() -> str:
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda:" + torch.cuda.get_device_name(0)
    except Exception:
        pass
    import platform

    return f"cpu:{platform.processor() or platform.machine()}x{os.cpu_count()}"


def model_path(repo_id: str) -> str:
    """Prefer a complete local mirror made by tools/fetch_models.sh; else let HF download it."""
    local = Path(os.environ.get("HERITAGE_MODELS", Path.home() / ".cache" / "heritage-models")) / repo_id
    return str(local) if (local / ".complete").exists() else repo_id
