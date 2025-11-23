POETRY ?= poetry
VENV := .venv
export POETRY_VIRTUALENVS_IN_PROJECT=1
RUN := $(POETRY) run

.PHONY: install format lint typecheck test ci lock pre-commit-install

$(VENV):
	python3 -m venv $(VENV)
	POETRY_VIRTUALENVS_IN_PROJECT=1 $(POETRY) install --with dev

install: $(VENV)
	POETRY_VIRTUALENVS_IN_PROJECT=1 $(POETRY) install --with dev

format: $(VENV)
	$(RUN) black .
	$(RUN) isort .

lint: $(VENV)
	$(RUN) ruff check .

typecheck: $(VENV)
	$(RUN) mypy src

test: $(VENV)
	$(RUN) pytest

ci: format lint typecheck test

lock:
	POETRY_VIRTUALENVS_IN_PROJECT=1 $(POETRY) lock

pre-commit-install: $(VENV)
	$(RUN) pre-commit install
