# Workspace Rules

## Git & Superpowers Artifacts

- **No Force-Adding Gitignored Superpowers Artifacts**: Files located inside `.superpowers/` (such as specs, plans, or scratch data) are local session artifacts and are gitignored.
- **Do NOT commit `.superpowers/` files**: Never use `git add -f` or force-commit any files inside `.superpowers/` into git history.
