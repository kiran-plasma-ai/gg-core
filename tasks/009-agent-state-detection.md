+++
status = "completed"
priority = "high"
assignee = ""
estimated_hours = 2
sprint = "5"
+++

# Task 9: Add agent state detection

## Objective
Add state detection (idle/working) to gg-core for session lifecycle management and automation.

## Background
gg-channels has implemented state detection using spinner/tool indicators from tmux pane output. This should be extracted to gg-core so:
- CLI can show agent state in `gg ps`
- Automation scripts can wait for agent to finish
- gg-channels can import from gg-core instead of duplicating logic

## Requirements

### 1. Add AgentState enum to _types.py
```python
class AgentState(Enum):
    WORKING = "working"   # Agent processing (spinners, tool calls)
    IDLE = "idle"         # Agent at prompt, waiting
    UNKNOWN = "unknown"   # Cannot determine
```

### 2. Add state detection constants to cleaning.py
```python
# Shared constants for state detection
SPINNER_CHARS = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
TOOL_INDICATORS = (
    "Used Shell",
    "Used WriteFile",
    "Using Shell",
    "Tool:",
    "Running",
    "Executing",
)
```

### 3. Add detect_state function to core/session.py
```python
def detect_state(project: str) -> AgentState:
    """Detect current agent state for a session.
    
    Args:
        project: Project name
        
    Returns:
        AgentState: WORKING, IDLE, or UNKNOWN
    """
    
def is_working(project: str) -> bool:
    """Quick check if agent is working."""
    
def is_idle(project: str) -> bool:
    """Quick check if agent is idle."""
```

### 4. Export in modules
- Add to `core/__init__.py`
- Add to top-level `__init__.py`

### 5. Test
- Write unit tests for state detection
- Test with real session

## Acceptance Criteria
- [x] AgentState enum in _types.py
- [x] detect_state() returns correct state from tmux pane
- [x] is_working() and is_idle() work correctly
- [x] Exported in core and top-level __init__.py
- [x] All 59 tests pass
