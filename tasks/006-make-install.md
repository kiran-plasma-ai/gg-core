+++
status = "pending"
priority = "medium"
assignee = ""
estimated_hours = 2
sprint = "2"
+++

# Task 6: Make Install Script

## Objective
Create make install/uninstall for deployment.

## Background
Users need to install gg-core system-wide or locally.

## Requirements

1. **make install**
   - Install systemd service template to `~/.config/systemd/user/`
   - Create symlink or copy CLI to `~/.local/bin/`
   - Install Python package

2. **make uninstall**
   - Remove systemd service template
   - Remove CLI from `~/.local/bin/`
   - Uninstall Python package

3. **pyproject.toml entry point**
   ```toml
   [project.scripts]
   gg-core = "gitgantt.cli.run:main"
   ```

## Acceptance Criteria
- [ ] `make install` works
- [ ] `gg-core` command available after install
- [ ] `make uninstall` removes all files
