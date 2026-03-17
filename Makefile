# gg-core Makefile
#

.PHONY: help install uninstall test lint typecheck clean

# Default target
help:
	@echo "gg-core Makefile"
	@echo "================="
	@echo ""
	@echo "Targets:"
	@echo "  install       Install gg wrapper and systemd service"
	@echo "  uninstall     Remove gg wrapper and systemd service"
	@echo "  test          Run tests"
	@echo "  lint          Run ruff linter"
	@echo "  typecheck     Run mypy type checker"
	@echo "  clean         Clean build artifacts"
	@echo ""

# Installation
install: install-wrapper install-systemd
	@echo "gg-core installed successfully"
	@echo "Usage: gg --help"

install-wrapper:
	@echo "Installing gg wrapper to ~/.local/bin/gg"
	@mkdir -p "$(HOME)/.local/bin"
	@cp bin/gg "$(HOME)/.local/bin/gg"
	@chmod +x "$(HOME)/.local/bin/gg"

install-systemd:
	@echo "Installing systemd service to ~/.config/systemd/user/"
	@mkdir -p "$(HOME)/.config/systemd/user"
	@cp systemd/gg@.service "$(HOME)/.config/systemd/user/"
	@systemctl --user daemon-reload 2>/dev/null || true
	@echo "Systemd service installed"

# Uninstallation
uninstall:
	@echo "Removing gg wrapper"
	@rm -f "$(HOME)/.local/bin/gg"
	@echo "Removing systemd service"
	@rm -f "$(HOME)/.config/systemd/user/gg@.service"
	@systemctl --user daemon-reload 2>/dev/null || true

# Testing
test:
	uv run pytest -v

# Linting
lint:
	uv run ruff check src/

# Type checking
typecheck:
	uv run mypy src/

# Clean build artifacts
clean:
	rm -rf build/ dist/ *.egg-info .pytest_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
