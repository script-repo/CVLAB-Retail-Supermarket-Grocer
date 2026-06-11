# Contributing

Thanks for your interest in improving this project. Contributions of all sizes
are welcome — bug fixes, new use cases, documentation, and examples.

## Ground rules

- Be respectful (see [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)).
- By contributing, you agree your contribution is licensed under the project's
  [AGPL-3.0](LICENSE) license.
- Never commit secrets. Read [SECURITY.md](SECURITY.md) first.

## Development setup

```bash
git clone https://github.com/<your-org>/<repo>.git
cd <repo>/cv-lab/backend
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1   |   macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp ../../.env.example .env        # adjust as needed (STORAGE_BACKEND=local is easiest)
uvicorn app.main:app --reload --port 8000
# open http://localhost:8000
```

There is no build step for the frontend — it is plain HTML/CSS/vanilla JS served
by the backend.

## Project layout

- `cv-lab/` — FastAPI backend + live-analysis frontend (the app).
- `cv-portal/` — static use-case library/portal site.
- `docs/` — documentation.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for how the pieces fit together.

## Adding a use case

The pipeline is plug-in based: create one analyzer file, register it, and it
appears automatically in the API and UI. Step-by-step guide:
[docs/ADDING_A_USE_CASE.md](docs/ADDING_A_USE_CASE.md).

## Pull requests

1. Fork and create a feature branch.
2. Keep changes focused; include a clear description of the "why".
3. Run a quick smoke check before pushing:
   - Backend imports/analyzers: `cd cv-lab/backend && python ../selftest.py`
     (with `PYTHONPATH` set to the backend dir if needed).
   - Manually verify the page still loads and a sample video analyzes.
4. Make sure no secrets are staged (`git diff --cached`).
5. Open the PR against `main`.

## Coding style

- Python: standard library + the existing dependencies; keep functions small and
  readable. Type hints where practical.
- JavaScript: vanilla ES5/ES6, no framework, no build tooling.
- Comments should explain intent/trade-offs, not restate the code.
