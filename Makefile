.PHONY: install dev worker test lint fmt demo-fdtd demo-vae demo-bayesian demo-pipeline demo-dipole up down clean help

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install:  ## Install package + dev tools (editable)
	uv pip install --system -e ".[dev]"

dev:  ## Run API server with auto-reload
	uvicorn yaf_api.main:app --reload --port 8000

worker:  ## Run Celery worker
	celery -A yaf_worker.celery_app worker --loglevel=info

test:  ## Run test suite
	pytest tests/ -x -v

test-strict:  ## Run tests with fallback solvers disabled (CI honesty mode)
	YAF_NO_FALLBACK=0 pytest tests/ -x -q

lint:  ## Ruff + mypy --strict
	ruff check . && mypy yaf_core yaf_ai yaf_solvers --strict

fmt:  ## Auto-fix lint issues
	ruff check . --fix

demo-fdtd:
	python -m yaf_ai.differentiable.diff_fdtd_jax --demo

demo-vae:
	python -m yaf_ai.generative.vae_designer --train --epochs 20

demo-bayesian:
	python -m yaf_ai.optimization.bayesian --demo

demo-pipeline:
	python -m yaf_ai.inverse_design.pipeline --demo

demo-dipole:
	python scripts/demo_dipole.py

up:
	docker compose up -d

down:
	docker compose down

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete 2>/dev/null || true
