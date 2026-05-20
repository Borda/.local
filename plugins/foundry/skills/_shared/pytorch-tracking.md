<!-- file: pytorch-tracking.md — consumers: web-explorer.md -->

## PyTorch Release & Nightly Monitoring

For ecosystem CI maintainers — track upstream breaking changes:

```bash
# Check latest PyTorch release
gh release list --repo pytorch/pytorch --limit 5

# Fetch release notes for a specific version
gh release view <version> --repo pytorch/pytorch

# Extract body then search for deprecation notices using Grep tool on the saved output
mkdir -p .cache/gh
gh release view <version> --repo pytorch/pytorch --json body -q .body > .cache/gh/pytorch-release.txt
# Use Grep tool: pattern="deprecat" path=".cache/gh/pytorch-release.txt" (case-insensitive: true)

# Track nightly build status
# check pytorch/pytorch/actions on GitHub for nightly workflow
```

## Multi-Library Compatibility Matrix

Upgrading dependency in PyTorch ecosystem:

1. Fetch compatibility tables from each library's docs:

```bash
# Lightning compatibility — search "Lightning PyTorch version compatibility table" and fetch the result
# (do not use hardcoded URLs — fetch the current compatibility page via WebSearch first)

# TorchMetrics compatibility — search "TorchMetrics PyTorch version compatibility" and fetch the result
# (do not use hardcoded URLs — search the project's GitHub releases or README via WebSearch first)
```

2. Build cross-reference table from fetched docs — no hardcoded version numbers, go stale in one release cycle. Fetch + parse current matrix from each library's official compatibility page. Add 1–2 second delay between WebFetch calls for different packages to avoid rate limiting.

3. Cross-check against `pyproject.toml` constraints before recommending upgrade
