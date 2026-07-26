<!-- file: codemap-contract.md — consumers: skills/{analyse,audit,code-review,code-remediate,develop,investigate,optimize,release,research}/SKILL.md, shared/codemap_adapter.py -->

# Codemap-py structural-context contract — codex-rig

Protocol: `codemap-py.integration.v1`. Codex Rig is a **consumer**, never a provider — it reads only
the public `codemap-py` CLI/JSON surface (`doctor --json`, `query <subcommand>`) via
`../../shared/codemap_adapter.py`. It never imports `codemap_py`, never reads codemap-py cache
internals or source-tree paths, and never depends on `codemap-py` being installed.

## Persist-once rule

Each required workflow probes **once**, at its bounded decision point, and persists the result to
its own run artifact (e.g. `<run-directory>/codemap-context.json`). Specialists consume that
artifact from the context pack; they never re-run the adapter. Re-querying per child specialist
defeats the token-saving purpose of a shared structural index and is a contract violation.

Invocation:

```
python PLUGIN_ROOT/shared/codemap_adapter.py context --category <analysis|develop|review|audit> \
  [--target <qname>] [--root <path>] --out <run-directory>/codemap-context.json
```

## Named status vocabulary

| Status | Meaning | Workflow action |
| --- | --- | --- |
| `available` | `codemap-py` present, index healthy, evidence exhaustive for the queries run | consume the persisted evidence as authoritative |
| `absent` | `codemap-py` not installed / not on PATH | fall back to Codex Rig's own bounded file inspection; do not treat this as an error |
| `stale` | index older than source for at least one query's target | note the caveat, still use the returned evidence, do not silently treat it as exhaustive |
| `incompatible` | interpreter unsupported, `doctor` payload malformed, or every mapped query failed | fall back to bounded file inspection; record the incompatibility, never retry the adapter within the same run |
| `degraded` | some evidence returned but `query_complete`/`not_covered`/`degraded` flags a gap | use the evidence, surface the gap as a caveat, never silently present it as exhaustive |

Absence and incompatibility are non-fatal: the workflow proceeds with its normal bounded file
inspection. A run must never claim structural evidence it did not actually receive.

## Category → query map (plan §8.4)

| Category | Consuming skills | Queries (`codemap-py query <subcommand>`) |
| --- | --- | --- |
| `analysis` | analyse, research | `central` (no target) + `deps --with-imports <target>` |
| `develop` | develop, investigate, optimize | `rdeps <target>` + `coupled` (no target) + `test-impact <target>` |
| `review` | code-review, code-remediate | `diff-impact` (no target — reads the working-tree/PR diff once) |
| `audit` | audit, release | `undocumented --all` + `dead-modules` (no target) |

`target` is a dotted module or `module::symbol` qname when the skill has resolved one at its
decision point; `analysis`/`develop` queries marked `requires_target=True` in
`codemap_adapter.CATEGORY_QUERIES` return early with a bounded error instead of guessing one.

## Not-applicable skills (recorded reason, no forced query)

Per `.developments/codemap-py/2026-07-23T18-30-49Z/phase0/codex-rig-classification.md`, five
skills have no Python structural-query subject and stay not-applicable rather than being forced to
integrate:

| Skill | Reason |
| --- | --- |
| `manage` | operates on plugin config artifacts (`.md`/`.toml`/`.json`) — config-reference propagation, not a Python call graph |
| `sync` | pure package-lifecycle (install/refresh via Codex CLI) — zero source analysis; must stay the single-product owner, never a circular installer |
| `agent-shims` | manages authenticated agent shim lifecycle/filesystem state — no source-code subject |
| `calibrate` | consumes fixed `runtime/calibration/*` fixtures — self-measurement of the plugin, not consuming-project Python structure |
| `kaggle` | output is a Jupytext notebook; `*.ipynb` is outside the frozen `py311-ast-v1` module/package contract |

## Symmetric optionality (plan §8.5)

`codemap_adapter.py` has zero import-time or startup-time dependency on `codemap-py` being
installed — every subprocess call is lazy, inside a function called only when a wired skill reaches
its decision point. Codex Rig's own skill discovery, packaging, and startup never probe or require
`codemap-py`.
