# Contributing to alive-memory

## Setup

```bash
git clone git@github.com:TriMinhPham/Alive-sdk.git
cd Alive-sdk
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[all,dev]"
```

## Development workflow

1. Create a branch from `main`: `git checkout -b feat/your-feature`
2. Write code in `alive_memory/`
3. Add tests in `tests/`
4. Run checks: `make check`
5. Commit and push
6. Open a PR against `main`

## Code style

- Python 3.12+, async/await throughout
- Type hints on function signatures
- Ruff for linting and formatting (`make lint`, `make format`)
- No global mutable state — pass dependencies via constructors
- Pipeline stages are functions, not classes (except facade)

## Testing

```bash
make test                           # Full suite
pytest tests/test_types.py -v       # Single module
pytest -k "test_memory" -v          # By name pattern
```

- Use `pytest-asyncio` for async tests
- Test files mirror source: `alive_memory/intake/thalamus.py` → `tests/intake/test_thalamus.py`
- All tests must pass before merge

## Architecture rules

- `alive_memory/` is a standalone package. It must NOT import from any external application code.
- Storage access goes through `BaseStorage` ABC only. No raw aiosqlite outside `storage/`.
- LLM access goes through `LLMProvider` protocol only.
- Consolidation features (dreaming, reflection) must work gracefully without an LLM provider — they just skip LLM-dependent steps.

## Commit messages

```
feat: add memory decay curve
fix: correct valence scoring for negative events
refactor: extract weighting math into recall/weighting.py
test: add consolidation pruning tests
docs: update architecture diagram
```
