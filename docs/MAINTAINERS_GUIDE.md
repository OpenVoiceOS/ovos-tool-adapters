# Maintainers Guide — ovos-tool-adapters

## Repository layout

```
ovos-tool-adapters/
├── ovos_tool_adapters/
│   ├── version.py          # OVOS version block (source of truth)
│   ├── _async_runner.py    # daemon-thread asyncio bridge
│   ├── _schema.py          # JSON Schema → Pydantic, AdapterToolOutput
│   ├── mcp.py              # MCPToolBox
│   └── utcp.py             # UTCPToolBox
├── test/
│   ├── test_async_runner.py
│   ├── test_schema.py
│   ├── test_mcp.py         # all mocked — no live server needed
│   └── test_utcp.py
├── docs/                   # user-facing documentation
├── pyproject.toml
└── .github/workflows/      # OVOS standard CI/CD
```

## Versioning

Version is read from `ovos_tool_adapters/version.py` — do **not** edit `pyproject.toml` version manually.

```python
# START_VERSION_BLOCK
VERSION_MAJOR = 0
VERSION_MINOR = 1
VERSION_BUILD = 0
VERSION_ALPHA = 1  # 0 = stable
# END_VERSION_BLOCK
```

The release workflow bumps this block automatically from PR labels:
- `breaking` → major
- `feature` / `enhancement` → minor
- `fix` / `bug` → build
- no label → alpha increment only

## Release process

1. Open a PR targeting `dev`.
2. Label the PR (`breaking`, `feature`, `fix`, or none).
3. Merge — the release workflow bumps the version, publishes alpha to PyPI, and opens a release PR to `master`.
4. Review and merge the release PR to `master` — stable is published automatically.

**Do not manually push to `master`.**

## Running tests

```bash
# Full test suite with coverage
uv run pytest test/ -v --cov=ovos_tool_adapters --cov-report=term-missing

# Single module
uv run pytest test/test_mcp.py -v
```

Tests are fully mocked — no live MCP or UTCP server is needed.

## CI/CD workflows

| Workflow | Trigger | What it does |
|---|---|---|
| `build-tests.yml` | PR, push | Build + pytest on Python 3.10–3.14 |
| `coverage.yml` | PR, push | Coverage report posted to PR comment |
| `lint.yml` | PR, push | ruff check (informational, non-blocking) |
| `pip_audit.yml` | PR, push | CVE scan |
| `license_check.yml` | PR, push | Dependency license check (Apache 2.0 safe) |
| `opm-check.yml` | PR, push | OPM plugin discovery + interface validation |
| `release_workflow.yml` | merge to `dev` | Version bump + PyPI alpha |
| `publish_stable.yml` | push to `master` | Stable PyPI release |

All workflows delegate to `OpenVoiceOS/gh-automations@dev`.

## Required secrets

| Secret | Purpose |
|---|---|
| `PYPI_TOKEN` | Publish to PyPI |
| `MATRIX_TOKEN` | Release notifications |

Set at the org level — all repos inherit them.

## Adding a new transport

To support a new MCP transport (e.g. a future WebSocket transport):

1. Add a branch to `MCPToolBox._connect_and_list()` — `mcp.py:78`
2. Add the corresponding import from `mcp.client.*`
3. Update `docs/mcp.md` transport table
4. Add a test case in `test/test_mcp.py`

## Dependencies

Core: `ovos-plugin-manager>=0.7.0`, `pydantic>=2.0`
Optional: `mcp>=1.0` (MCP support), `utcp>=1.1` (UTCP support)
Dev: `pytest>=7.0`, `pytest-cov`, `pytest-asyncio`

Optional deps are guarded by `try/except ImportError` — never add them to `dependencies`.

## Audit items

See `AUDIT.md` for known issues and technical debt. Update it when new issues are found.
