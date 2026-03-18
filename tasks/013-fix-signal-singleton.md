+++
status = "in_progress"
priority = "high"
assignee = ""
estimated_hours = 1
sprint = "5"
+++

# Task 13: Fix signal handler and singleton issues

## Objective
Fix code review findings in gg-core.

## Issues

### 1. Signal handler bug in wait_for()
Current code:
```python
old_handler = signal.signal(signal.SIGINT, signal.SIG_IGN)
try:
    # ... wait loop ...
finally:
    signal.signal(signal.SIGINT, old_handler)
```
Problem: If signal.signal() raises an exception, old_handler is undefined and finally block raises NameError.

Fix: Use try/except around the signal call.

### 2. Singleton race condition
Current code uses manual double-checked locking which is not safe in Python.

Fix: Use `functools.lru_cache` for simpler, safer singleton.

## Implementation

### Fix wait_for() in core/session.py

```python
def wait_for(
    condition: Callable[[], bool],
    timeout: float = WAIT_FOR_TIMEOUT,
    interval: float = WAIT_FOR_INTERVAL,
) -> bool:
    """Wait for condition to become true."""
    # Ignore SIGINT during wait
    try:
        old_handler = signal.signal(signal.SIGINT, signal.SIG_IGN)
    except (OSError, ValueError):
        # Cannot set handler - proceed without it
        old_handler = None
    
    try:
        start = time.time()
        while time.time() - start < timeout:
            if condition():
                return True
            time.sleep(interval)
        return False
    finally:
        if old_handler is not None:
            try:
                signal.signal(signal.SIGINT, old_handler)
            except (OSError, ValueError):
                pass  # Cannot restore handler
```

### Fix get_tmux() in core/tmux.py

Use lru_cache instead of manual locking.

## Acceptance Criteria
- [ ] wait_for() handles signal errors gracefully
- [ ] get_tmux() uses simpler singleton pattern
- [ ] All tests pass
