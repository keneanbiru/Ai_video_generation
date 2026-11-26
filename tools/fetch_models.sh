#!/usr/bin/env bash
# Resumable downloader for the open-weight models the local providers use.
# Mirrors each repo's needed files into $HERITAGE_MODELS (default ~/.cache/heritage-models)
# and writes a .complete marker; pipeline/common.py:model_path() prefers these local copies.
# Written because the connection here was ~0.1-0.7 MB/s and needed resume (FAILURES.md F03).
set -euo pipefail
DEST=${HERITAGE_MODELS:-$HOME/.cache/heritage-models}
fetch_repo () {  # repo  regex-of-files-to-keep
  local repo=$1 keep=$2 dir="$DEST/$1"
  [ -f "$dir/.complete" ] && { echo "have $repo"; return; }
  mkdir -p "$dir"
  curl -sf "https://huggingface.co/api/models/$repo/tree/main?recursive=true" \
   | python3 -c 'import json,sys,re; k=re.compile(sys.argv[1]); [print(f["path"]) for f in json.load(sys.stdin) if f["type"]=="file" and k.search(f["path"])]' "$keep" \
   | while read -r f; do
       mkdir -p "$dir/$(dirname "$f")"
       echo "  $repo/$f"
       until curl -sfL -C - --retry 20 --retry-delay 5 --speed-limit 20000 --speed-time 60 -o "$dir/$f" "https://huggingface.co/$repo/resolve/main/$f"; do
         rc=$?; [ $rc -eq 33 ] && break; echo "  retry $f (curl $rc)"; sleep 5; done
     done
  touch "$dir/.complete"; echo "done $repo"
}
fetch_repo facebook/mms-tts-amh '\.(json|safetensors|txt)$'
fetch_repo stabilityai/sd-turbo '(model_index\.json|scheduler/.*|tokenizer/.*|(text_encoder|unet|vae)/(config\.json|.*fp16\.safetensors))$'
fetch_repo facebook/musicgen-small '^(config\.json|generation_config\.json|preprocessor_config\.json|special_tokens_map\.json|spiece\.model|tokenizer\.json|tokenizer_config\.json|model\.safetensors)$'
for extra in ${EXTRA_MODELS:-}; do fetch_repo "$extra" '\.(json|safetensors|txt)$'; done
