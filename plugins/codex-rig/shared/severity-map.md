# Severity Map

Use across codex-native skills.

## Critical

- security issue with exploit path
- data loss or corruption risk
- release-blocking regression

## High

- incorrect behavior in core feature
- missing required test on changed core logic
- unresolved migration compatibility break

## Medium

- non-core behavior mismatch
- weak assertion quality or edge-case gap
- stale docs or partial config drift

## Low

- style/nit issues
- wording improvements
- non-blocking cleanup

## Gate Rule

- `critical > 0` => `status=fail`
- `checks_failed` non-empty => `status=fail`
- otherwise `status=pass`
