# gg-core

GitGantt session management core - thin wrapper around libtmux.

## Install

```bash
uv sync
```

## Usage

```python
import gg_core

# Start a session
gg_core.start_session("myproject", "kimi")

# Send a command
gg_core.send_command("myproject", "ls -la")

# List sessions
print(gg_core.list_sessions())

# Stop session
gg_core.stop_session("myproject")
```
