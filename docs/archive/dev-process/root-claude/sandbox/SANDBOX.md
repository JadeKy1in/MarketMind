# Sandbox — Third-Party File Security Review

All third-party files (skills, plugins, GitHub repos, MCP servers, scripts) MUST pass through this sandbox before installation.

## Protocol

1. **Isolate**: Place ALL files in `.claude/sandbox/incoming/<name>/` — never directly into any active directory
2. **Scan**: Check every file for:
   - `eval()`, `exec()`, `compile()` with dynamic input
   - `subprocess`, `os.system`, `os.popen` with unsanitized arguments
   - `__import__` with dynamic module names
   - Obfuscated strings: `base64.b64decode`, `zlib.decompress`, `codecs.decode`
   - Network calls to non-obvious hosts: `socket`, `requests`, `httpx`, `urllib`
   - File operations on sensitive paths: `~/.ssh`, `~/.aws`, `.env`, `/etc/`
   - Shell injection vectors: `shell=True`, unquoted command strings
3. **Approve**: Only after confirming no malicious patterns, move files to their target location
4. **Update**: When updating previously-installed files, re-run the FULL protocol — same rules apply to updates

## Incoming Queue

`.claude/sandbox/incoming/` — drop new files here. Never install directly.

## Approved Log

Record approved installations here with date, source, and scan summary:

| Date | Source | Files | Reviewer | Notes |
|------|--------|-------|----------|-------|
| — | — | — | — | — |
