# gg-core Makefile

.PHONY: help install uninstall test lint typecheck clean deploy deploy-local verify quality rollback

help:
	@echo "gg-core Makefile"
	@echo "================="
	@echo ""
	@echo "Local targets:"
	@echo "  install       Install gg wrapper and systemd service"
	@echo "  uninstall     Remove gg wrapper and systemd service"
	@echo "  test          Run tests"
	@echo "  lint          Run ruff linter"
	@echo "  typecheck     Run mypy type checker"
	@echo "  quality       Run lint + typecheck + tests"
	@echo "  clean         Clean build artifacts"
	@echo ""
	@echo "Deploy targets:"
	@echo "  deploy        Quality gate + sync to gateway + reinstall + restart"
	@echo "  deploy-local  Reinstall locally from source"
	@echo "  verify        Verify gateway installation"
	@echo "  rollback      Stop gg-supervisor + gg-channels (use after failed deploy)"

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

# Quality gate — lint + typecheck + test
quality: lint typecheck test

debug:
	@uv run python scripts/debug_pipeline.py $(project) $(lines)

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

# -----------------------------------------------------------------------------
# Local deploy — reinstall from source
# -----------------------------------------------------------------------------

deploy-local:
	@echo "=== Reinstalling gg-core locally ==="
	@uv sync --reinstall-package gg-core 2>&1 | tail -3
	@echo "=== Local reinstall complete ==="

# -----------------------------------------------------------------------------
# Deploy to gateway
# -----------------------------------------------------------------------------

GATEWAY_HOST := gateway
GATEWAY_DIR := $(GATEWAY_HOME)/gg-core
GATEWAY_VENV := $(GATEWAY_HOME)/gg-core/.venv
GATEWAY_PYTHON := $(GATEWAY_VENV)/bin/python3
GATEWAY_SSH := ssh -i $(HOME)/.ssh/node $(GATEWAY_HOST)

# All files needed for a working installation
SYNC_SRC := ./src/ ./bin/ ./systemd/ ./scripts/ ./pyproject.toml ./uv.lock ./README.md ./AGENTS.md ./REGISTRY.md ./CONTINUATION.md
SYNC_TESTS := ./tests/

deploy: lint typecheck test
	@echo ""
	@echo "=== Deploying gg-core to gateway ==="
	@echo ""
	@echo "[1/8] Checking gateway..."
	@$(GATEWAY_SSH) 'echo ok' || { echo "ERROR: Cannot reach gateway"; exit 1; }
	@echo ""
	@echo "[2/8] Syncing source to gateway..."
	@rsync -av --delete \
		--exclude='*.pyc' \
		--exclude='__pycache__' \
		--exclude='*.egg-info' \
		--exclude='.pytest_cache' \
		$(SYNC_SRC) \
		$(GATEWAY_HOST):$(GATEWAY_DIR)/
	@rsync -av --delete \
		--exclude='*.pyc' \
		--exclude='__pycache__' \
		$(SYNC_TESTS) \
		$(GATEWAY_HOST):$(GATEWAY_DIR)/
	@echo ""
	@echo "[3/8] Clearing pycache on gateway..."
	@$(GATEWAY_SSH) 'find $(GATEWAY_DIR) -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true'
	@$(GATEWAY_SSH) 'find $(GATEWAY_DIR) -name "*.pyc" -delete 2>/dev/null || true'
	@echo ""
	@echo "[4/8] Ensuring venv exists on gateway..."
	@$(GATEWAY_SSH) 'test -d "$(GATEWAY_VENV)" || uv venv $(GATEWAY_VENV)'
	@echo ""
	@echo "[5/8] Reinstalling gg-core on gateway..."
	@$(GATEWAY_SSH) 'cd $(GATEWAY_DIR) && uv sync --reinstall-package gg-core 2>&1 | tail -5'
	@echo ""
	@echo "[6/8] Running tests on gateway..."
	@$(GATEWAY_SSH) 'cd $(GATEWAY_DIR) && $(GATEWAY_PYTHON) -m pytest tests/ -v 2>&1 | tail -10'
	@echo ""
	@echo "[7/8] Installing gg wrapper on gateway..."
	@$(GATEWAY_SSH) 'mkdir -p ~/.local/bin && cp $(GATEWAY_DIR)/bin/gg ~/.local/bin/gg && chmod +x ~/.local/bin/gg'
	@echo ""
	@echo "[8/8] Installing systemd service on gateway..."
	@$(GATEWAY_SSH) 'mkdir -p ~/.config/systemd/user && cp $(GATEWAY_DIR)/systemd/gg@.service ~/.config/systemd/user/ && systemctl --user daemon-reload'
	@echo ""
	@echo "=== gg-core deploy complete ==="

verify:
	@echo "Verifying gg-core on gateway..."
	@$(GATEWAY_SSH) '$(GATEWAY_PYTHON) -c "import gg_core; from gg_core.core import Deduplicator; print(\"version:\", gg_core.__version__); print(\"Deduplicator: ok\")"' 2>&1
	@echo ""
	@echo "=== Service status ==="
	@$(GATEWAY_SSH) 'systemctl --user status gg-telegram --no-pager 2>/dev/null | head -5 || echo "gg-telegram: not running"'
	@$(GATEWAY_SSH) 'systemctl --user status gg-voice --no-pager 2>/dev/null | head -5 || echo "gg-voice: not running"'

rollback:
	@echo "Stopping dependent services on gateway..."
	@$(GATEWAY_SSH) 'systemctl --user stop gg-telegram gg-voice 2>/dev/null; echo "channels stopped" || echo "channels not running"'
	@echo "To redeploy: make deploy (gg-core first, then gg-channels)"
