+++
status = "pending"
priority = "medium"
assignee = ""
estimated_hours = 2
sprint = "1"
+++

# Task 3: Attach Command

## Objective
Implement attach command to connect to running tmux session.

## Background
Users need to attach to running sessions to interact with agents directly.

## Requirements

1. **attach command**
   ```
   gg-core attach <project>
   ```
   - Attaches to tmux session
   - Replaces current process

2. **Implementation**
   - Use `os.execlp('tmux', 'tmux', 'attach', '-t', project)`
   - Handle case where session doesn't exist

## Acceptance Criteria
- [ ] attach command works
- [ ] Error message if session doesn't exist

## Implementation Notes
```python
def cmd_attach(project: str) -> int:
    import os
    os.execlp('tmux', 'tmux', 'attach', '-t', project)
```
