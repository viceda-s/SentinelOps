## Summary

<!-- What changed and why. -->

## Issue

Closes #<!-- issue-number -->

## Evidence

<!--
This project is verified against a real running stack, not just code that looks right.
Paste actual command output. Pick what applies:

  - `./automation/scripts/bootstrap.sh --validate-only` (CMDB, Compose, Prometheus, Alertmanager)
  - `./automation/scripts/test.sh` / `pytest` results
  - `ruff check .` / `ruff format --check .`
  - A real chaos run (`chaos.sh stop <service>`) with the resulting `incident_events` trail
  - Screenshots or captures of Grafana dashboards, the health page, or a generated PDF report
-->

```
```

## Scope

- Area: `area:response-engine` / `area:observability` / `area:reporting` / `area:database` / `area:infra` / `area:tooling` / `area:api` / `area:testing` / `area:docs`
- Tier (if Phase 3 work): `tier:1` / `tier:2` / `tier:3` / n/a

## Checklist

- [ ] `README.md` updated if this PR changes documented behaviour, commands, or endpoints.
- [ ] Relevant ADR added or updated if this changes an architectural decision.
- [ ] Test suite passes locally (`./automation/scripts/test.sh` or `pytest -m "not e2e"`).
- [ ] `ruff check .` / `ruff format --check .` clean.
- [ ] `validate_cmdb.py` passes if CMDB or alert rules changed.
- [ ] No credentials, `.env` values, or generated secrets included.
