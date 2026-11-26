# gg-core Makefile

.PHONY: help install install-path uninstall test lint typecheck clean deploy deploy-local verify quality rollback

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
install: install-wrapper install-systemd install-path stamp
	@echo "gg-core installed successfully"
	@echo "Usage: gg --help"

install-wrapper:
	@echo "Installing gg wrapper to ~/.local/bin/gg"
	@mkdir -p "$(HOME)/.local/bin"
	@cp bin/gg "$(HOME)/.local/bin/gg"
	@chmod +x "$(HOME)/.local/bin/gg"

# Idempotent, marker-commented PATH block. ~/.zshenv is read by
# non-interactive non-login zsh (the `ssh host 'gg ...'` path); ~/.profile
# covers login shells.
PATH_BLOCK_START := \# >>> gg-core PATH >>>
PATH_BLOCK_END := \# <<< gg-core PATH <<<

install-path: install-wrapper
	@echo "Ensuring gg is on PATH"
	@for rc in "$(HOME)/.zshenv" "$(HOME)/.profile"; do \
		if grep -q "gg-core PATH" "$$rc" 2>/dev/null; then \
			echo "  PATH block already present in $$rc"; \
		else \
			printf '\n$(PATH_BLOCK_START)\nexport PATH="$$HOME/.local/bin:$$PATH"\n$(PATH_BLOCK_END)\n' >> "$$rc"; \
			echo "  appended PATH block to $$rc"; \
		fi; \
	done
	@if [ -w /usr/local/bin ]; then \
		ln -sf "$(HOME)/.local/bin/gg" /usr/local/bin/gg; \
		echo "  symlinked /usr/local/bin/gg"; \
	elif sudo -n true 2>/dev/null; then \
		sudo ln -sf "$(HOME)/.local/bin/gg" /usr/local/bin/gg && \
		echo "  symlinked /usr/local/bin/gg (via sudo)"; \
	else \
		echo "  note: /usr/local/bin not writable and no passwordless sudo"; \
		echo "        rc PATH block covers zsh and login shells; run with sudo to add the symlink"; \
	fi

# Stamp the short commit for machines without .git (deploy rsync excludes it)
stamp:
	@/usr/bin/git rev-parse --short HEAD 2>/dev/null | sed 's/.*/COMMIT = "&"/' > src/gg_core/_commit.py || true

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

deploy-local: install
	@echo ""
	@echo "=== Deploying gg-core locally ==="
	@echo ""
	@echo "[1/4] Reinstalling from source..."
	@uv sync --reinstall-package gg-core 2>&1 | tail -3
	@echo ""
	@echo "[2/4] Running local tests..."
	@uv run pytest -v 2>&1 | tail -5
	@echo ""
	@echo "[3/4] Checking installation health..."
	@gg doctor || { echo "ERROR: gg doctor failed"; exit 1; }
	@echo ""
	@echo "[4/4] Local deploy complete"
	@echo "=== gg-core local deploy complete ==="

# -----------------------------------------------------------------------------
# Deploy to gateway
# -----------------------------------------------------------------------------

# Use the local SSH config alias so the correct user/key/hostname are picked up.
GATEWAY_HOST ?= gateway
GATEWAY_HOME ?= ~
GATEWAY_DIR := $(GATEWAY_HOME)/gg-core
GATEWAY_VENV := $(GATEWAY_HOME)/gg-core/.venv
GATEWAY_PYTHON := $(GATEWAY_VENV)/bin/python3
GATEWAY_SSH := ssh $(GATEWAY_HOST)
RSYNC_RSH := ssh

# All files needed for a working installation
SYNC_ROOT := ./
SYNC_EXCLUDES := --exclude='.venv' --exclude='__pycache__' --exclude='*.pyc' \
	--exclude='*.egg-info' --exclude='.pytest_cache' --exclude='.mypy_cache' \
	--exclude='.ruff_cache' --exclude='dist' --exclude='.git' --exclude='tasks' \
	--exclude='*.log'

deploy: lint typecheck test
	@echo ""
	@echo "=== Deploying gg-core to gateway ==="
	@echo ""
	@echo "[1/8] Checking gateway..."
	@$(GATEWAY_SSH) 'echo ok' || { echo "ERROR: Cannot reach gateway"; exit 1; }
	@echo ""
	@echo "[2/8] Syncing source to gateway..."
	@rsync -av --delete -e "$(RSYNC_RSH)" $(SYNC_EXCLUDES) \
		$(SYNC_ROOT) \
		$(GATEWAY_HOST):$(GATEWAY_DIR)/
	@echo ""
	@echo "[3/8] Clearing pycache on gateway..."
	@$(GATEWAY_SSH) 'find $(GATEWAY_DIR) -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true'
	@$(GATEWAY_SSH) 'find $(GATEWAY_DIR) -name "*.pyc" -delete 2>/dev/null || true'
	@echo ""
	@echo "[4/8] Ensuring venv exists on gateway..."
	@$(GATEWAY_SSH) 'test -d $(GATEWAY_VENV) || uv venv $(GATEWAY_VENV)'
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
	@echo "[8/9] Installing systemd service on gateway..."
	@$(GATEWAY_SSH) 'mkdir -p ~/.config/systemd/user && cp $(GATEWAY_DIR)/systemd/gg@.service ~/.config/systemd/user/ && systemctl --user daemon-reload'
	@echo ""
	@echo "[9/9] Checking gateway health..."
	@$(GATEWAY_SSH) '$(GATEWAY_PYTHON) -c "import sys; sys.path.insert(0, \"$(GATEWAY_DIR)/src\"); from gg_core.cli.run import cmd_doctor; sys.exit(cmd_doctor())"' || { echo "WARNING: gg doctor failed on gateway"; }
	@echo ""
	@echo "[10/10] Verifying deploy..."
	@echo "  Checksum of deployed files:"
	@$(GATEWAY_SSH) 'sha256sum $(GATEWAY_DIR)/systemd/gg@.service ~/.config/systemd/user/gg@.service'
	@echo "  Service health:"
	@$(GATEWAY_SSH) 'systemctl --user is-active gg-telegram gg-telegram-docent gg@gg-voice.service 2>/dev/null || true'
	@echo "  Anomalies (last 5 min):"
	@$(GATEWAY_SSH) 'journalctl --user --since "5 minutes ago" --no-pager 2>/dev/null | grep -iE "(error|failed|deprecated)" | grep -v "gg doctor" | tail -3 || echo "    ✓ none"'
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
