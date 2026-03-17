# Quality Gates for gg-core
# Run with: make <target>

PREFIX ?= ~/.local
SYSTEMD_DIR ?= ~/.config/systemd/user

.PHONY: help check lint type test test-cov format fix clean install uninstall install-cli install-systemd

help:
	@echo "gg-core Quality Gates"
	@echo "====================="
	@echo ""
	@echo "Available targets:"
	@echo "  check       - Run all checks (lint, type, test)"
	@echo "  lint        - Run ruff linter"
	@echo "  type        - Run mypy type checker"
	@echo "  test        - Run pytest"
	@echo "  test-cov    - Run pytest with coverage"
	@echo "  format      - Format code with ruff"
	@echo "  fix         - Auto-fix lint issues"
	@echo "  clean       - Clean cache files"
	@echo "  install     - Full install (cli + systemd)"
	@echo "  install-cli - Install CLI only"
	@echo "  install-systemd - Install systemd service only"
	@echo "  uninstall   - Remove all installed files"

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

# Full install
install: install-cli install-systemd
	@echo ""
	@echo "✅ gg-core installed successfully!"
	@echo "Run 'gg-core --help' to get started"

# Install CLI
install-cli:
	@echo "Installing gg-core CLI..."
	uv pip install -e .
	@echo "✓ CLI installed"

# Install systemd service
install-systemd:
	@echo "Installing systemd service..."
	mkdir -p $(SYSTEMD_DIR)
	cp systemd/gg@.service $(SYSTEMD_DIR)/
	systemctl --user daemon-reload
	@echo "✓ Systemd service installed"

# Uninstall
uninstall:
	@echo "Uninstalling gg-core..."
	uv pip uninstall gg-core || true
	rm -f $(SYSTEMD_DIR)/gg@.service
	systemctl --user daemon-reload || true
	@echo "✓ gg-core uninstalled"

# Install dependencies only
sync:
	uv sync
	uv sync --group dev
