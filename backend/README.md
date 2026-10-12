# LectureKaki backend

Python 3.14 and Poetry.

Run these commands from `backend/`:

```sh
poetry env use 3.14
poetry install
poetry run uvicorn app.main:app --reload
```

Health check: `http://localhost:8000/health`. API docs: `http://localhost:8000/docs`.

Checks: `poetry run ruff check .`, `poetry run ruff format --check .`, and
`poetry run pytest`. Run `poetry run ruff format .` to apply formatting.
