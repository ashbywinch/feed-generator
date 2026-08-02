# Makefile for feed-generator (SignalFlow)
.PHONY: help setup run smoke topics spike spike-bg spike-logs spike-stop spike-weekly spike-weekly-bg spike-weekly-logs spike-weekly-stop eval-story eval-queries refresh-queries topic-sources topic-sources-bg topic-sources-logs topic-sources-stop lint lint-github typecheck test coverage format clean

PYTHON := .venv/bin/python
UV := $(shell command -v uv 2>/dev/null || echo $(HOME)/.local/bin/uv)
RUFF := .venv/bin/ruff
BASEDPYRIGHT := .venv/bin/basedpyright

GREEN := \033[0;32m
YELLOW := \033[0;33m
RED := \033[0;31m
NC := \033[0m

help:
	@echo "Available commands:"
	@echo "  ${GREEN}make setup${NC}        Create venv, install deps + pre-commit hooks, ensure .env exists"
	@echo "  ${GREEN}make run${NC}          Recurring run from stored strategies (setup first)"
	@echo "  ${GREEN}make smoke${NC}        Engine self-check (opml+memory+embeddings+chat)"
	@echo "  ${GREEN}make topics${NC}       Show the seeded topic table"
	@echo "  ${GREEN}make topic-sources${NC} Generate a topic's source list (TOPIC=\"name\")"
	@echo "  ${GREEN}make spike${NC}        Run topic-elicitation spike (foreground)"
	@echo "  ${GREEN}make spike-bg${NC}     Run spike in background; log to spikes/state/run.log"
	@echo "  ${GREEN}make spike-logs${NC}   Tail the background spike log"
	@echo "  ${GREEN}make spike-stop${NC}   Stop the background spike"
	@echo "  ${GREEN}make spike-weekly${NC} Weekly article selection spike (TOPIC=\"name\")"
	@echo "  ${GREEN}make spike-weekly-bg${NC} Run weekly spike in background; log to spikes/state/weekly.log"
	@echo "  ${GREEN}make spike-weekly-logs${NC} Tail the background weekly spike log"
	@echo "  ${GREEN}make spike-weekly-stop${NC} Stop the background weekly spike"
	@echo "  ${GREEN}make eval-story${NC}   Eval: can the story contextualize fresh articles"
	@echo "  ${GREEN}make eval-queries${NC}  Eval: are discovery queries global + well-formed"
	@echo "  ${GREEN}make refresh-queries${NC} Regenerate discovery queries via prompt (eval-gated, persists)"
	@echo "  ${GREEN}make lint${NC}         Check code quality (ruff)"
	@echo "  ${GREEN}make typecheck${NC}    Static type check (basedpyright)"
	@echo "  ${GREEN}make test${NC}         Run tests (lint + typecheck gate)"
	@echo "  ${GREEN}make coverage${NC}     Run tests with coverage report"
	@echo "  ${GREEN}make format${NC}       Auto-fix formatting issues"
	@echo "  ${GREEN}make clean${NC}        Remove .venv and generated files"

setup:
	@$(UV) --version >/dev/null 2>&1 || curl -LsSf https://astral.sh/uv/install.sh | sh
	@$(UV) sync
	@$(UV) run pre-commit install
	@[ -f .env ] || cp .env.example .env

run: setup
	@$(UV) run --env-file .env python -m signalflow run

smoke: setup
	@$(UV) run --env-file .env python -m signalflow smoke

topics: setup
	@$(UV) run --env-file .env python -m signalflow topics

topic-sources: setup
	@$(UV) run --env-file .env python -m signalflow sources "$(TOPIC)"

topic-sources-bg: setup
	mkdir -p spikes/state
	@nohup $(UV) run --env-file .env python -u -m signalflow sources "$(TOPIC)" >> spikes/state/topic-sources.log 2>&1 & echo $$! > spikes/state/topic-sources.pid
	@echo "topic-sources running in background (pid $$(cat spikes/state/topic-sources.pid))"
	@echo "  monitor: make topic-sources-logs"
	@echo "  stop:    make topic-sources-stop"

topic-sources-logs:
	tail -f spikes/state/topic-sources.log

topic-sources-stop:
	@if [ -f spikes/state/topic-sources.pid ]; then kill $$(cat spikes/state/topic-sources.pid) 2>/dev/null && rm spikes/state/topic-sources.pid && echo "topic-sources stopped"; else echo "no pid file — not running?"; fi

spike: setup
	@$(UV) run --env-file .env python spikes/topic_elicitation_resumable.py

spike-bg: setup
	mkdir -p spikes/state
	@nohup $(UV) run --env-file .env python -u spikes/topic_elicitation_resumable.py >> spikes/state/run.log 2>&1 & echo $$! > spikes/state/spike.pid
	@echo "spike running in background (pid $$(cat spikes/state/spike.pid))"
	@echo "  monitor: make spike-logs"
	@echo "  stop:    make spike-stop"

spike-logs:
	tail -f spikes/state/run.log

spike-stop:
	@if [ -f spikes/state/spike.pid ]; then kill $$(cat spikes/state/spike.pid) 2>/dev/null && rm spikes/state/spike.pid && echo "spike stopped"; else echo "no pid file — not running?"; fi

spike-weekly: setup
	@$(UV) run --env-file .env python spikes/weekly_selection.py

spike-weekly-bg: setup
	mkdir -p spikes/state
	@nohup $(UV) run --env-file .env python -u spikes/weekly_selection.py >> spikes/state/weekly.log 2>&1 & echo $$! > spikes/state/weekly.pid
	@echo "weekly spike running in background (pid $$(cat spikes/state/weekly.pid))"
	@echo "  monitor: make spike-weekly-logs"
	@echo "  stop:    make spike-weekly-stop"

spike-weekly-logs:
	tail -f spikes/state/weekly.log

spike-weekly-stop:
	@if [ -f spikes/state/weekly.pid ]; then kill $$(cat spikes/state/weekly.pid) 2>/dev/null && rm spikes/state/weekly.pid && echo "weekly spike stopped"; else echo "no pid file — not running?"; fi

eval-story: setup
	@$(UV) run --env-file .env python spikes/eval_story.py

eval-queries: setup
	@$(UV) run --env-file .env python spikes/eval_queries.py

refresh-queries: setup
	@$(UV) run --env-file .env python spikes/eval_queries.py --generate

lint: setup
	@$(RUFF) check signalflow tests spikes/weekly_selection.py spikes/eval_story.py spikes/eval_queries.py

lint-github: setup
	@$(RUFF) check signalflow tests spikes/weekly_selection.py spikes/eval_story.py spikes/eval_queries.py --output-format=github

typecheck: setup
	@$(BASEDPYRIGHT) --outputjson | $(PYTHON) -c "import json,sys; d=json.load(sys.stdin); sys.exit(1 if d['summary']['errorCount'] else 0)"

test: setup lint typecheck
	@$(PYTHON) -m pytest

coverage: setup
	@$(PYTHON) -m pytest --cov=signalflow --cov-report=term-missing --cov-report=xml

format: setup
	@$(RUFF) check --fix signalflow tests spikes/weekly_selection.py spikes/eval_story.py spikes/eval_queries.py
	@$(RUFF) format signalflow tests spikes/weekly_selection.py spikes/eval_story.py spikes/eval_queries.py

clean:
	@rm -rf .venv htmlcov/
	@rm -f .coverage coverage.xml
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete
