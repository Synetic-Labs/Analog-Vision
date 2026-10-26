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
- `src/analog_vision/web/analog.js` is the same chain on the GPU, for the browser (the
  viewer, `analog-vision view`, and other projects that vendor it). Change it with the
  Python, stage for stage, and keep `tests/test_web.py` passing: it runs both in headless
  Chrome and needs them to agree.
- `docs/effects.jpg` is made by `uv run python scripts/effects.py`: rerun it when the
  simulation changes.
