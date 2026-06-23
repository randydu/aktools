# REASONIX.md

## Stack

- **Python 3.13** (`.python-version:3.13.13`, `pyproject.toml` targets `py312`)
- **FastAPI** — HTTP API framework (app in `aktools/main.py`)
- **Typer** — CLI entry point (`aktools/cli.py`)
- **Uvicorn / Gunicorn** — ASGI server (gunicorn in Docker, uvicorn locally)
- **AKShare** — upstream financial-data library (core dependency)
- **Ruff** — linter + formatter (Black-compatible config in `pyproject.toml`)

## Layout

- `aktools/` — main package: CLI, FastAPI app, core API router, login, DB, assets
- `tests/` — pytest suite; two test files (`test_cli.py`, `test_demo.py`)
- `src/` — single file `app.py`, thin re-export of `aktools.main:app` for Vercel
- `docs/` — MkDocs site (`mkdocs.yml` at root)
- `alembic/` — SQLAlchemy migrations (`alembic.ini` at root)
- `.github/workflows/` — CI (build on push/PR) + release/deploy workflows
- `var/` — scratch/test scripts, not part of the package

## Commands

```sh
# Run the HTTP API server
python -m aktools

# Run tests
pytest

# Lint
ruff check .

# Format
ruff format .

# Install dev dependencies (includes ruff, pytest, pre-commit, commitizen)
pip install -r requirements-dev.txt

# Set up pre-commit hooks (runs ruff lint+format + conventional-commit check)
pre-commit install

# Docs dev server
mkdocs serve
```

## RTK (Token Savings)

RTK v0.42.0 is installed at `~/.local/bin/rtk`. Reasonix has no PreToolUse hook, so **manually prefix** these commands with `rtk`:

### Always wrap with `rtk`

| Command | Rewrites to | Token savings |
|---|---|---|
| `pytest` | `rtk pytest` | ~90% (failures only) |
| `pytest -x` | `rtk pytest -x` | ~90% |
| `ruff check .` | `rtk ruff check .` | ~80% (JSON, grouped) |
| `ruff format .` | `rtk ruff format .` | ~80% |
| `git diff` | `rtk git diff` | ~75% (condensed) |
| `git log` | `rtk git log` | ~80% (one-line) |
| `pip install` | `rtk pip install` | ~80% (strips progress) |
| `pip list` | `rtk pip list` | ~80% |
| `docker ps` | `rtk docker ps` | ~80% |

### Skip RTK (already compact)

`git status`, `git add`, `git commit`, `git push`, `ls`, `grep -c`, `which`, `find`, `echo`, `python -m aktools`, `mkdocs serve`, `pre-commit install`

### Unknown commands

Check first: `rtk rewrite "<cmd>"` — if it prints a rewritten version, use that. If it exits 1 with no output, run the command directly.

## Conventions

- **Conventional Commits** enforced via pre-commit (`conventional-pre-commit` hook on `commit-msg` stage)
- **File header**: `# -*- coding:utf-8 -*-` + shebang + date/desc docstring on every `.py`
- **Ruff format**: 88-char lines, double quotes, space indent (Black-compatible)
- **Single test file per concern**: `tests/test_cli.py` tests the CLI; `tests/test_demo.py` smoke-tests AKShare data
- **CLI → subprocess**: the Typer CLI launches uvicorn via `subprocess.run(…, shell=True)` rather than importing it

## Watch out for

- `src/app.py` is a **Vercel deployment shim** — it just does `from aktools.main import app`. Edit app logic in `aktools/main.py`, not there.
- `aktools_log.log` in the root is a runtime log file; it's gitignored but may exist on disk.
- `setup.py` and `pyproject.toml` **both exist**: `setup.py` is the build/packaging config; `pyproject.toml` holds only Ruff settings.
- The `aktools/datasets.py` file loads HTML/asset paths relative to the package directory — moving asset files requires updating it.
- Docker uses Gunicorn with Uvicorn workers, not plain uvicorn — production differs from local `python -m aktools`.
