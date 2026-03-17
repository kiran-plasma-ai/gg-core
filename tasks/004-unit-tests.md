+++
status = "pending"
priority = "high"
assignee = ""
estimated_hours = 4
sprint = "2"
+++

# Task 4: Unit Tests

## Objective
Write unit tests for core functionality.

## Background
Tests ensure correctness and prevent regressions.

## Requirements

1. **Test Structure**
   ```
   tests/
   ├── conftest.py
   ├── test_validation.py
   ├── test_session.py
   ├── test_tmux.py
   └── test_logs.py
   ```

2. **test_validation.py**
   - Test valid project names
   - Test invalid project names
   - Test valid agents
   - Test invalid agents

3. **test_logs.py**
   - Test get_log_path
   - Test read_log (mock file)
   - Test get_log_size

4. **test_session.py** (with mocks)
   - Test start_session validation
   - Test stop_session validation
   - Test send_command validation

5. **test_tmux.py** (with mocks)
   - Test Tmux class methods
   - Mock libtmux.Server

## Acceptance Criteria
- [ ] Tests run with `uv run pytest`
- [ ] Test coverage > 70%
- [ ] All tests pass

## Implementation Notes

### Mocking libtmux
```python
from unittest.mock import MagicMock, patch

@patch('gitgantt.core.tmux.libtmux.Server')
def test_has_session(mock_server):
    mock_server.return_value.has_session.return_value = True
    tmux = get_tmux()
    assert tmux.has_session("test")
```
