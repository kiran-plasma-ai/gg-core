+++
status = "in_progress"
priority = "high"
assignee = ""
estimated_hours = 4
sprint = "1"
+++

# Task 1: CLI Parser and Basic Commands

## Objective
Implement basic CLI commands: start, stop, ps, send, logs.

## Background
gg-core needs a CLI for interactive use. Start with basic commands that wrap the core functions.

## Requirements

1. **Argparse Setup**
   - Create `cli/parser.py` with argparse configuration
   - Subcommands: start, stop, ps, send, logs, attach

2. **start command**
   ```
   gg-core start <project> [agent]
   gg-core start myproject kimi
   ```
   - Calls `start_session()`

3. **stop command**
   ```
   gg-core stop <project>
   ```
   - Calls `stop_session()`

4. **ps command**
   ```
   gg-core ps
   ```
   - Lists all sessions with status

5. **send command**
   ```
   gg-core send <project> <message>
   ```
   - Calls `send_command()`

6. **logs command**
   ```
   gg-core logs <project> [lines]
   gg-core logs myproject 50
   ```
   - Reads and displays log file

## Acceptance Criteria
- [x] CLI can be run via `uv run gg-core <command>`
- [ ] start command works
- [ ] stop command works
- [ ] ps command shows sessions
- [ ] send command sends to session
- [ ] logs command shows output

## Implementation Notes

### Structure
```
cli/
├── __init__.py
├── parser.py    # argparse setup
├── run.py      # main() dispatch
└── commands/
    ├── __init__.py
    ├── base.py
    ├── start.py
    ├── stop.py
    ├── ps.py
    ├── send.py
    └── logs.py
```

### Entry Point
Add to pyproject.toml:
```toml
[project.scripts]
gg-core = "gitgantt.cli.run:main"
```
