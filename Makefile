# gg-core Makefile

.PHONY: help install uninstall test lint typecheck clean deploy verify quality rollback

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
# Deploy to gateway (see gg-supervisor/docs/deployment-workflow.md for full pipeline)
# Convention: each project has its own venv at $GATEWAY_DIR/.venv
# gg-core must be deployed FIRST (others depend on it).
# -----------------------------------------------------------------------------

GATEWAY_DIR := $(GATEWAY_HOME)/gg-core
GATEWAY_VENV := $(GATEWAY_HOME)/gg-core/.venv
GATEWAY_VENV_PYTHON := $(GATEWAY_VENV)/bin/python3

deploy: lint typecheck test
	@echo ""
	@echo "=== Deploying gg-core to gateway ==="
	@echo ""
	@echo "[1/7] Checking gateway..."
	@ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no gateway 'echo ok' || { echo "ERROR: Cannot reach gateway"; exit 1; }
	@echo ""
	@echo "[2/7] Syncing source to gateway..."
	@rsync -av --delete \
		--exclude='*.pyc' \
		--exclude='__pycache__' \
		--exclude='*.egg-info' \
		--exclude='.pytest_cache' \
		./src/ \
		gateway:$(GATEWAY_DIR)/src/
	@rsync -av \
		./pyproject.toml \
		gateway:$(GATEWAY_DIR)/
	@rsync -av --delete \
		--exclude='*.pyc' \
		--exclude='__pycache__' \
		./tests/ \
		gateway:$(GATEWAY_DIR)/tests/
	@echo ""
	@echo "[3/7] Clearing pycache and stale package files on gateway..."
	@ssh gateway 'find $(GATEWAY_DIR) -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true'
	@ssh gateway 'find $(GATEWAY_DIR)/src -name "*.pyc" -delete 2>/dev/null || true'
	@ssh gateway 'find $(GATEWAY_DIR)/src -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true'
	@ssh gateway 'for f in __init__.py _config.py _errors.py _types.py gg_core ggcore; do rm -rf "$(GATEWAY_DIR)/$$f" 2>/dev/null || true; done'
	@echo ""
	@echo "[4/7] Ensuring venv exists on gateway..."
	@ssh gateway 'test -d "$(GATEWAY_VENV)" || uv venv $(GATEWAY_VENV)'
	@ssh gateway 'test -f "$(GATEWAY_VENV)/bin/pip" || $(GATEWAY_VENV_PYTHON) -m ensurepip'
	@echo ""
	@echo "[5/7] Reinstalling gg-core..."
	@ssh gateway 'cd $(GATEWAY_DIR) && $(GATEWAY_VENV_PYTHON) -m pip install --force-reinstall --no-cache-dir -e . 2>&1'
	@echo ""
	@echo "[6/7] Running tests on gateway..."
	@ssh gateway 'cd $(GATEWAY_DIR) && $(GATEWAY_VENV_PYTHON) -m pytest tests/ -v 2>&1 | tail -10'
	@echo ""
	@echo "[7/7] Verifying version..."
	@ssh gateway '$(GATEWAY_VENV_PYTHON) -c "import gg_core; print(\"gg-core version:\", gg_core.__version__)"'
	@echo ""
	@echo "=== gg-core deploy complete ==="

verify:
	@echo "Verifying gg-core on gateway..."
	@ssh gateway '$(GATEWAY_VENV_PYTHON) -c "import gg_core; from gg_core.core import Deduplicator; print(\"version:\", gg_core.__version__); print(\"Deduplicator: ok\")"' 2>&1

rollback:
	@echo "Stopping dependent services (gg-supervisor + gg-channels)..."
	@ssh gateway 'systemctl --user stop gg-supervisor 2>/dev/null; echo "supervisor stopped" || echo "supervisor not running"'
	@ssh gateway 'systemctl --user stop gg-telegram gg-voice 2>/dev/null; echo "channels stopped" || echo "channels not running"'
	@echo "To redeploy: make deploy (gg-core first, then others)"
