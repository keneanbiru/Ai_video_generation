"""Remote GPU jobs on Kaggle: package inputs -> push a private kernel -> poll -> pull outputs.

    python -m pipeline.remote wan     [--only s04 s08] [--size 640]   # Wan 2.2 TI2V-5B clips
    python -m pipeline.remote acestep                                 # ACE-Step 1.5 score candidates
    python -m pipeline.remote probe                                   # GPU/software probe

Nothing is public: the input dataset and the kernels are created private. Credentials come from
~/.kaggle/access_token (or KAGGLE_API_TOKEN); they never enter the repository.

The remote scripts write <file> + <file>.json sidecars (keyframe hash / caption, GPU latency).
The local stages import them only if they still match the storyboard (stale guard), and merge
their GPU timing into runs.jsonl, so remote calls are logged like local ones.
Only work that is missing or stale is sent: a re-run with nothing changed submits no GPU job.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .common import OUT, ROOT, file_hash, load_storyboard, log, log_call

KAGGLE = str(Path(sys.executable).parent / "kaggle")
USER = None
JOBS = ROOT / "kaggle"
WORK = OUT / "remote"


def kg(*args: str, check: bool = True) -> str:
    p = subprocess.run([KAGGLE, *args], capture_output=True, text=True)
    if check and p.returncode != 0:
        raise RuntimeError(f"kaggle {' '.join(args[:3])} failed: {p.stdout[-400:]} {p.stderr[-400:]}")
    return p.stdout + p.stderr


def username() -> str:
    global USER
    if USER is None:
        out = kg("kernels", "list", "--mine", "--page-size", "1")
        USER = out.splitlines()[-1].split("/")[0].strip()
    return USER


def publish_inputs(files: dict[str, Path], slug: str) -> str:
    """Create or version a PRIVATE dataset holding the job inputs. Returns '<user>/<slug>'."""
    d = WORK / "datasets" / slug
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    for name, src in files.items():
        (d / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, d / name)
    ref = f"{username()}/{slug}"
    (d / "dataset-metadata.json").write_text(json.dumps({"title": slug, "id": ref, "licenses": [{"name": "other"}]}))
    exists = "403" not in kg("datasets", "status", ref, check=False) and "ready" in kg("datasets", "status", ref, check=False)
    if exists:
        kg("datasets", "version", "-p", str(d), "-m", f"inputs {time.strftime('%H:%M:%S')}", "-r", "zip", "-q")
    else:
        kg("datasets", "create", "-p", str(d), "-r", "zip", "-q")  # private unless --public
    for _ in range(60):  # wait until the new version is ready before a kernel mounts it
        if "ready" in kg("datasets", "status", ref, check=False):
            break
        time.sleep(10)
    return ref


def run_kernel(job: str, script: Path, dataset: str | None, timeout_min: int = 240, extra_args: str = "") -> Path:
    """Push a private GPU kernel, poll until done, download its /kaggle/working output."""
    slug = f"heritage-{job}"
    kdir = WORK / "kernels" / job
    if kdir.exists():
        shutil.rmtree(kdir)
    kdir.mkdir(parents=True)
    code = script.read_text()
    if extra_args:
        code = code.replace("ARGS_FROM_RUNNER = []", f"ARGS_FROM_RUNNER = {extra_args.split()!r}")
    (kdir / script.name).write_text(code)
    meta = {"id": f"{username()}/{slug}", "title": slug, "code_file": script.name, "language": "python",
            "kernel_type": "script", "is_private": "true", "enable_gpu": "true", "enable_tpu": "false",
            "enable_internet": "true", "machine_shape": "", "dataset_sources": [dataset] if dataset else [],
            "competition_sources": [], "kernel_sources": [], "model_sources": []}
    (kdir / "kernel-metadata.json").write_text(json.dumps(meta, indent=1))
    t0 = time.time()
    log(f"  [remote] pushing private kernel {meta['id']} (T4 x2)")
    kg("kernels", "push", "-p", str(kdir), "--accelerator", "NvidiaTeslaT4", "-t", str(timeout_min * 60))
    queued_s, status, last = None, "", ""
    while True:
        time.sleep(30)
        status = kg("kernels", "status", meta["id"], check=False)
        if "RUNNING" in status and queued_s is None:
            queued_s = round(time.time() - t0)
            log(f"  [remote] running after {queued_s}s in queue")
        if any(s in status for s in ("COMPLETE", "ERROR", "CANCEL")):
            break
        if status != last:
            log(f"  [remote] {status.strip().split('has status')[-1]}")
            last = status
        if time.time() - t0 > (timeout_min + 60) * 60:
            raise TimeoutError(f"{meta['id']} did not finish in {timeout_min} min")
    out = WORK / "results" / job
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    kg("kernels", "output", meta["id"], "-p", str(out), check=False)
    wall = round(time.time() - t0)
    ok = "COMPLETE" in status
    log_call(stage="remote", item=job, provider="kaggle", model=f"kernel:{meta['id']}", latency_s=wall,
             device="kaggle:T4x2", status="ok" if ok else "error", queue_s=queued_s,
             error=None if ok else status.strip()[:300], output=str(out.relative_to(ROOT)))
    log(f"  [remote] {job}: {'complete' if ok else 'FAILED'} in {wall}s (queue {queued_s}s); output -> {out.relative_to(ROOT)}")
    if not ok:
        logs = sorted(out.glob("*.log"))
        tail = logs[0].read_text()[-1500:] if logs else "(no log downloaded)"
        raise RuntimeError(f"Kaggle job {job} failed: {status.strip()}\n{tail}")
    return out


def wan(only: list[str] | None, size: int, frames: int, steps: int, jobs: int = 2) -> None:
    sb = load_storyboard()
    from .keyframes import keyframes as make_keyframes

    kfs = make_keyframes(sb)  # cached; ensures every keyframe exists locally
    clips = OUT / "clips_wan"
    clips.mkdir(exist_ok=True)
    todo = []
    for s in sb["shots"]:
        if only and s["id"] not in only:
            continue
        if not only and not s.get("animate", True):
            continue
        meta = clips / f"{s['id']}.json"
        if meta.exists():
            m = json.loads(meta.read_text())
            if (m.get("keyframe_sha16") == file_hash(kfs[s["id"]]) and m.get("motion_prompt") == s["motion_prompt"]
                    and m.get("params", {}).get("size") == size):
                continue  # this exact clip already exists
        todo.append(s["id"])
    if not todo:
        log("  [remote] wan: every requested clip is up to date; no GPU job submitted")
        return
    files = {"storyboard.json": ROOT / "storyboard.json"}
    files.update({f"keyframes/{sid}.png": kfs[sid] for sid in todo})
    ds = publish_inputs(files, "heritage-inputs")
    # E20/E21b: one model copy per machine. Split the shots over `jobs` parallel kernels (separate VMs).
    jobs = max(1, min(jobs, len(todo)))
    parts = [todo[i::jobs] for i in range(jobs)]
    from concurrent.futures import ThreadPoolExecutor

    def one(i_part):
        i, part = i_part
        name = "wan" if jobs == 1 else f"wan{i + 1}"
        return run_kernel(name, JOBS / "wan22_i2v.py", ds,
                          extra_args=f"--only {' '.join(part)} --size {size} --frames {frames} --steps {steps} "
                                     f"--offload sequential")

    with ThreadPoolExecutor(jobs) as ex:
        results = list(ex.map(lambda ip: _safe(one, ip), enumerate(parts)))
    clips.mkdir(exist_ok=True)  # F15: recreate even if it was moved while the job ran
    n = 0
    for out in [r for r in results if r]:
        for p in out.rglob("clips_wan/*.mp4"):
            shutil.copy(p, clips / p.name)
            shutil.copy(p.with_suffix(".json"), clips / p.with_suffix(".json").name)
            n += 1
    # A COMPLETE kernel is not a delivered clip: log the real outcome separately.
    log_call(stage="remote", item="wan:clips", provider="kaggle", model="Wan-AI/Wan2.2-TI2V-5B-Diffusers",
             status="ok" if n == len(todo) else "error", device="kaggle:T4", clips=n, requested=len(todo),
             error=None if n == len(todo) else f"{n}/{len(todo)} clips delivered")
    log(f"  [remote] wan: imported {n}/{len(todo)} clips into outputs/clips_wan/")


def _safe(fn, arg):
    try:
        return fn(arg)
    except Exception as e:  # one failed kernel must not lose the other's clips
        log(f"  [remote] a wan job failed: {e!r}"[:300])
        return None


def acestep() -> None:
    sb = load_storyboard()
    ds = publish_inputs({"storyboard.json": ROOT / "storyboard.json"}, "heritage-inputs")
    out = run_kernel("acestep", JOBS / "acestep_score.py", ds)
    dst = OUT / "music_acestep"
    dst.mkdir(exist_ok=True)
    n = 0
    for p in out.rglob("music_acestep/seed*.wav"):
        shutil.copy(p, dst / p.name)
        shutil.copy(p.with_suffix(".json"), dst / p.with_suffix(".json").name)
        n += 1
    log(f"  [remote] acestep: imported {n}/{len(sb['music']['candidates'])} candidates")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("wan")
    w.add_argument("--only", nargs="*")
    w.add_argument("--size", type=int, default=512)
    w.add_argument("--frames", type=int, default=49)
    w.add_argument("--steps", type=int, default=25)
    w.add_argument("--jobs", type=int, default=2, help="parallel Kaggle kernels (separate machines)")
    sub.add_parser("acestep")
    sub.add_parser("probe")
    a = ap.parse_args()
    if a.cmd == "wan":
        wan(a.only, a.size, a.frames, a.steps, a.jobs)
    elif a.cmd == "acestep":
        acestep()
    else:
        out = run_kernel("probe", JOBS / "jobs" / "gpu_probe" / "probe.py", None, timeout_min=30)
        print((out / "probe.json").read_text() if (out / "probe.json").exists() else "no probe.json")


if __name__ == "__main__":
    main()
