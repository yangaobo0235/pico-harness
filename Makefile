.PHONY: help install install-deps format check lint lint-python test test-retained test-performance benchmark benchmark-regression experiments-large experiments-provider resume-metrics check-architecture check-commits check-pr-title check-large-files build ci clean

PYTHON ?= python3
PYTHON_LINT_TARGETS ?= src scripts tests examples
COMMIT_RANGE ?= origin/main..HEAD

help:
	@echo "Targets:"
	@echo "  install        Install Python deps and git hooks"
	@echo "  install-deps   Install Python deps only (CI uses this)"
	@echo "  format         Format Python sources"
	@echo "  check          Run the complete local deterministic acceptance gate"
	@echo "  lint           Run Python lint gates"
	@echo "  lint-python    Ruff-check the current lint target set"
	@echo "  test           Run the deterministic Python suite without opt-in tests"
	@echo "  test-performance Run timing-sensitive experiments without parallel workers"
	@echo "  benchmark      Run the frozen coding-task benchmark with the scripted model"
	@echo "  benchmark-regression Run the harness regression track"
	@echo "  experiments-large Run the large-scale memory and context experiments"
	@echo "  experiments-provider Run the provider comparison experiments"
	@echo "  resume-metrics Collect resume and recovery metrics from run artifacts"
	@echo "  check-architecture Check executable import boundaries"
	@echo "  check-commits  Validate Conventional Commit subjects"
	@echo "  check-pr-title Validate the PR title in PR_TITLE"
	@echo "  check-large-files Fail on blocked assets and oversized files in the commit range"
	@echo "  build          Build a wheel and source archive"
	@echo "  ci             Run the local CI gate"
	@echo "  clean          Remove generated caches and build output"

install-deps:
	uv sync

install: install-deps
	uv run pre-commit install
	uv run pre-commit install --hook-type commit-msg

format:
	uv run ruff format $(PYTHON_LINT_TARGETS)

check: check-architecture lint test build

lint: lint-python

lint-python:
	uv run ruff check $(PYTHON_LINT_TARGETS)
	uv run ruff format --check $(PYTHON_LINT_TARGETS)

test: test-retained

test-retained:
	uv run pytest tests -n 4 -q --strict-markers

test-performance:
	uv run pytest tests -m performance -n 0 -q

check-architecture:
	uv run python -m scripts.ci.check_architecture

check-commits:
	PYTHONPATH=. uv run python scripts/ci/check_commit_messages.py $(COMMIT_RANGE)

check-pr-title:
	PYTHONPATH=. uv run python scripts/ci/check_pr_title.py

check-large-files:
	PYTHONPATH=. uv run python scripts/ci/check_large_files.py $(COMMIT_RANGE)

benchmark:
	uv run python -m scripts.dev.run_benchmark

benchmark-regression:
	uv run python -m scripts.dev.run_benchmark --regression

experiments-large:
	uv run python -m scripts.dev.run_large_scale_experiments

experiments-provider:
	uv run python -m scripts.dev.run_provider_experiments

resume-metrics:
	uv run python -m scripts.dev.collect_resume_metrics

build:
	uv build

ci: lint test build

clean:
	rm -rf .pytest_cache .ruff_cache .uv-cache .mypy_cache htmlcov dist build
	rm -rf .pico
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
