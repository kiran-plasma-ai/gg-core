+++
status = "pending"
priority = "high"
assignee = ""
estimated_hours = 3
sprint = "2"
+++

# Task 5: Connect Command (start + attach)

## Objective
Implement combined start + attach command.

## Background
Users often want to start a session and immediately attach to it.

## Requirements

1. **connect command**
   ```
   gg-core connect <project> [agent]
   ```
   - Starts session if not running
   - Attaches to session
   - Single command for workflow

2. **Implementation**
   - Check if session exists
   - If not, start it
   - Then attach

## Acceptance Criteria
- [ ] connect command starts session if needed
- [ ] connect command attaches to existing session
- [ ] Works with `gg-core connect myproject kimi`
