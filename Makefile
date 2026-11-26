# One command for the whole film:   make film
# Uses ./.venv if present (see `make setup`), else whatever python3 is on PATH.
PY ?= $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)

.PHONY: setup film radio validate smoke test costs clean-cache clean-all

setup:            ## create .venv and install CPU dependencies (needs ffmpeg on PATH)
	python3 -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu
	.venv/bin/pip install -r requirements.txt

film:             ## validate -> narration -> radio cut -> keyframes -> shots -> music -> both exports
	$(PY) -m pipeline.run

radio:            ## stop after the radio cut (user test 1 prototype)
	$(PY) -m pipeline.run --radio-only

validate:         ## schema + semantic checks only
	$(PY) -m pipeline.run --validate-only

smoke:            ## call each provider once and log latency
	$(PY) -m pipeline.smoke

test:
	$(PY) -m pytest -q tests

costs:            ## summarise runs.jsonl per stage (feeds COSTS.md)
	$(PY) -m pipeline.costs

clean-cache:      ## drop rendered video/audio but keep model outputs (keyframes, narration, music candidates)
	rm -rf outputs/shots outputs/final outputs/radio_cut outputs/music/bed.wav* outputs/film_*.mp4

clean-all:        ## everything generated; the next `make film` calls every model again
	rm -rf outputs/*
