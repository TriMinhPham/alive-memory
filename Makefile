.PHONY: test lint typecheck format coverage check install clean

install:
	pip install -e ".[all,dev]"

test:
	python -m pytest tests/ --tb=short -q

test-v:
	python -m pytest tests/ -v --tb=short

lint:
	ruff check alive_memory/ tests/

format:
	ruff format alive_memory/ tests/
	ruff check --fix alive_memory/ tests/

typecheck:
	mypy alive_memory/

coverage:
	coverage run -m pytest tests/ --tb=short -q
	coverage report

check: lint typecheck test

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	rm -rf dist/ build/ *.egg-info/
