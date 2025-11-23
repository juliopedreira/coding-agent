POETRY ?= poetry
RUN := POETRY_VIRTUALENVS_IN_PROJECT=1 $(POETRY) run

.PHONY: install format lint typecheck test ci lock pre-commit-install

install:
	POETRY_VIRTUALENVS_IN_PROJECT=1 $(POETRY) install --with dev

format:
	$(RUN) black .
	$(RUN) isort .

lint:
	$(RUN) ruff check .

typecheck:
	$(RUN) mypy src

test:
	$(RUN) pytest

ci: format lint typecheck test

lock:
	POETRY_VIRTUALENVS_IN_PROJECT=1 $(POETRY) lock

pre-commit-install:
	$(RUN) pre-commit install
