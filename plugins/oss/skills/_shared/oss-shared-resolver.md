# OSS Shared Dir Resolver

Resolve oss plugin shared dir — installed first, local workspace fallback.
`sort -V` orders semver correctly (0.9.0 < 0.10.0); `tail -1` picks newest.

```bash
_OSS_SHARED=$(ls -d ~/.claude/plugins/cache/borda-ai-rig/oss/*/skills/_shared 2>/dev/null | sort -V | tail -1)
[ -z "$_OSS_SHARED" ] && _OSS_SHARED="plugins/oss/skills/_shared"
```
