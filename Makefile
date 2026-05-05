.PHONY: test lint typecheck ci dryrun clean

PYTHON := .venv/bin/python
SRC := src/

test:
	$(PYTHON) -m pytest tests/ -q

test-verbose:
	$(PYTHON) -m pytest tests/ -v

test-contracts:
	$(PYTHON) -m pytest tests/contracts/ -v

lint:
	$(PYTHON) -m ruff check $(SRC)

lint-fix:
	$(PYTHON) -m ruff check --fix $(SRC)

typecheck:
	$(PYTHON) -m mypy $(SRC)

ci: lint typecheck test
	@echo "CI checks passed."

clean:
	find . -type d \( -name __pycache__ -o -name .mypy_cache -o -name .pytest_cache -o -name .ruff_cache \) -exec rm -rf {} + 2>/dev/null || true
	rm -rf dist/ *.egg-info/ *.egg

healthcheck:
	$(PYTHON) scripts/healthcheck.py --pair $(PAIR)

dryrun:
	$(PYTHON) -m gate_trade --dry-run
