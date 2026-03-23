# gg-core

GitGantt session management core - thin wrapper around libtmux for managing AI agent sessions.

## Install

```bash
uv sync
```

## CLI Usage

```bash
# Start a session
gg start myproject kimi

# Start with specific model
gg start myproject kimi -m minimax-m27-highspeed
gg start myproject coder -m grok-2
gg start myproject opencode -m gpt-4

# Connect (start + attach)
gg connect myproject

# Send a command
gg send myproject "fix the bug"

# View logs
gg logs myproject

# List sessions
gg ps

# Stop session
gg stop myproject
```

**Supported agents:** `kimi`, `coder`, `grok`, `minimax`, `gemini`, `opencode`

## Library Usage

```python
import gg_core

# Start a session (with optional model)
gg_core.start_session("myproject", "kimi")
gg_core.start_session("myproject", "kimi", model="minimax-m27-highspeed")

# Send a command
gg_core.send_command("myproject", "ls -la")

# List sessions
print(gg_core.list_sessions())

# Check if agent is working
if gg_core.is_working("myproject"):
    print("Agent is processing...")

# Stop session
gg_core.stop_session("myproject")
```
