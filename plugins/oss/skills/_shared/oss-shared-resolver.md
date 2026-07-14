# OSS Shared Dir Resolver

Pointer only — no bash to execute. Canonical resolver is bin script
`bin/resolve_shared_path.py`; consumers set `$_OSS_SHARED` by invoking it directly:

```bash
_OSS_SHARED=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/oss}/bin/resolve_shared_path.py" oss skills/_shared 2>/dev/null)
```

Performs tiered cascade (env root → registry → cache semver → source-tree fallback),
superseding old `ls | sort -V | tail -1` snippet this file used to carry.
