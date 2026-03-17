# Quality Gates for gg-core
# Run with: make <target>

.PHONY: help check lint type test test-cov format fix clean install

help:
	@echo "gg-core Quality Gates"
	@echo "====================="
	@echo ""
	@echo "Available targets:"
	@echo "  check      - Run all checks (lint, type, test)"
	@echo "  lint       - Run ruff linter"
	@echo "  type       - Run mypy type checker"
	@echo "  test       - Run pytest"
	@echo "  test-cov   - Run pytest with coverage"
	@echo "  format     - Format code with ruff"
	@echo "  fix        - Auto-fix lint issues"
	@echo "  clean      - Clean cache files"
	@echo "  install    - Install dependencies"

# Default target - run all checks
check: lint type test
	@echo ""
	@echo "✅ All checks passed!"

# Linting
lint:
	@echo "Running ruff linter..."
	uv run ruff check src/

# Type checking
type:
	@echo "Running mypy type checker..."
	uv run mypy src/

# Testing
test:
	@echo "Running pytest..."
	uv run pytest -v

# Test with coverage
test-cov:
	@echo "Running pytest with coverage..."
	uv run pytest --cov=gitgantt --cov-report=term-missing

# Code formatting
format:
	@echo "Formatting code with ruff..."
	uv run ruff format src/

# Auto-fix issues
fix:
	@echo "Auto-fixing lint issues..."
	uv run ruff check src/ --fix

# Clean cache
clean:
	@echo "Cleaning cache files..."
	rm -rf .pytest_cache
	rm -rf .mypy_cache
	rm -rf __pycache__
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true

# Install dependencies
install:
	uv sync
	uv sync --group dev
