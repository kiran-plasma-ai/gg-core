+++
status = "pending"
priority = "high"
assignee = ""
estimated_hours = 2
sprint = "1"
+++

# Task 2: Systemd Service Template

## Objective
Create systemd service template for session lifecycle management.

## Background
Sessions are started via systemd user services. Need a service template that:
- Starts the agent command in tmux
- Handles cleanup on stop
- Sets environment variables

## Requirements

1. **Service Template**
   - Create `gg@.service` template in appropriate location
   - Install to `~/.config/systemd/user/`

2. **Template Variables**
   - `%i` = project name
   - Environment: `AGENT_CMD`

3. **Start Behavior**
   - Create tmux session with project name
   - Run agent command in session
   - Detach automatically

4. **Stop Behavior**
   - Kill tmux session
   - Clean up

## Acceptance Criteria
- [ ] Service template created at correct path
- [ ] Can start session via `systemctl --user start gg@myproject`
- [ ] Can stop session via `systemctl --user stop gg@myproject`

## Implementation Notes

### Template Location
```
~/.config/systemd/user/gg@.service
```

### Template Content
```ini
[Unit]
Description=gg-core session for %i

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/sh -c 'tmux new-session -d -s %i "${AGENT_CMD}"'
ExecStop=/usr/bin/tmux kill-session -t %i
KillMode=none
```

### Installation
- Copy to `~/.config/systemd/user/` on install
- `systemctl --user daemon-reload` after install
