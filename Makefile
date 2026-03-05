.PHONY: install test search clean help

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Install package in editable mode with dev dependencies
	pip install -e ".[dev]"

test: ## Run all tests (offline, no network calls)
	python -m pytest tests/ -v

test-cov: ## Run tests with coverage report
	python -m pytest tests/ -v --cov=src/permit_engine --cov-report=term-missing

search: ## Smoke test — 2-night mock search for North Cascades
	wa-permits north-cascades --start-date 2026-07-15 --nights 2

clean: ## Remove Python bytecode and cache directories
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete
	rm -rf .pytest_cache .coverage htmlcov
