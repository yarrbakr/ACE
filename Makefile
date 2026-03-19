.PHONY: install test lint demo clean build

install:
	pip install -e ".[dev]"

test:
	pytest --cov=ace -v

lint:
	ruff check src/
	ruff format --check src/
	mypy src/ace/ --ignore-missing-imports

demo:
	python examples/demo.py

clean:
	rm -rf build/ dist/ *.egg-info .pytest_cache .mypy_cache
	find . -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

build:
	python -m build
