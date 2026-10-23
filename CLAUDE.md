# analog-vision

Python package `analog_vision` (src layout, uv): analog NTSC video over an FM link,
simulated signal by signal.

- Run everything with `uv run`. Never bare `python`.
- After code changes run `uv run ruff check src tests scripts`,
  `uv run basedpyright src tests scripts`, `uv run pytest -q`.
- Artifacts come out of the signal chain, never painted on: if a picture looks wrong, find
  the stage (encode, fm, decode) whose physics is off and fix it there.
- `reference/` is what real analog video looks like, to calibrate against: `lab/` our own
  captures, `web/` third-party stills. The repository is public and those stills are not
  ours to redistribute: they stay local and git-ignored, never committed; `web/SOURCES.md`
  says where each came from.
- `docs/effects.jpg` is made by `uv run python scripts/effects.py`: rerun it when the
  simulation changes.
