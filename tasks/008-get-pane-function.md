+++
status = "completed"
priority = "high"
assignee = ""
estimated_hours = 1
sprint = "4"
+++

# Task 8: Add get_pane function

## Objective
Add `get_pane()` function to expose tmux pane for direct capture.

## Background
No logger needed - adapters can capture directly from tmux pane. Provide access to libtmux Pane object.

## Requirements

1. **Add get_pane function**
   ```python
   from gitgantt.core.tmux import get_pane
   
   pane = get_pane("myproject")
   lines = pane.capture_pane(start='-', end='-')
   ```

2. **Export in modules**
   - Add to `core/__init__.py`
   - Add to top-level `__init__.py`

3. **Test**
   - Write test for get_pane
   - Test with real session

## Acceptance Criteria
- [ ] get_pane returns libtmux Pane or None
- [ ] Can capture full pane history
- [ ] Works with running session
- [ ] Returns None for non-existent session
