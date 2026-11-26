# Kaggle GPU stages (optional)

Two stages need a GPU that the build machine does not have. They are packaged as scripts you run in a Kaggle notebook (GPU T4 ×2, Internet on, phone-verified account). Their outputs come back into `outputs/` with a JSON sidecar, and the local pipeline imports them only if they still match the storyboard.

| script | writes | imported by | fallback if missing or stale |
|---|---|---|---|
| `wan22_i2v.py` | `outputs/clips_wan/<shot>.mp4` + `.json` (keyframe hash, motion prompt, latency) | `pipeline/shots.py` (`wan22:kaggle`) | Ken Burns |
| `acestep_score.py` | `outputs/music_acestep/seed<N>.wav` + `.json` (caption, latency) | `pipeline/music.py` (`acestep:kaggle`) | MusicGen-small, then the procedural score |

**Status: not executed.** See FAILURES.md F01/F06. Steps are in each script's docstring.
