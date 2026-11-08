.PHONY: install run lint fmt typecheck test dev

install:
	python -m venv .venv
	.venv/bin/pip install -e '.[dev]'

run:
	APP_TOKEN=$${APP_TOKEN:-change-me} .venv/bin/uvicorn app.main:app --host $${HOST:-0.0.0.0} --port $${PORT:-8000}

dev:
	APP_TOKEN=$${APP_TOKEN:-change-me} .venv/bin/uvicorn app.main:app --reload --host $${HOST:-0.0.0.0} --port $${PORT:-8000}

fmt:
	.venv/bin/ruff format app tests
	.venv/bin/ruff check --fix app tests

lint:
	.venv/bin/ruff check app tests
	.venv/bin/mypy app

test:
	.venv/bin/pytest

check: lint test
