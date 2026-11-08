# Common rules for every live view builder (read once)

- Repo: your worktree of /Users/atma1/gh_all/atmaos/bayesian, branched from `eng-bayes-v2` at the freeze commit. Venv: `/opt/homebrew/bin/python3.13 -m venv .venv && .venv/bin/pip install -q -e ".[dev]"`.
- The contract is `spec/Live_View_Specification_v0.2.md` with `spec/live_build_log.md` (B1 to B8; the log wins over the spec). Read only the sections your brief names.
- Fill in ONLY the files in your brief's file list. A diff outside it is refused at the gate, not reviewed. Never edit `src/bayesian_marketing/live/contracts.py`, `registry.py`, `config.py`, the `SCHEMA` in `store.py`, `core/`, `registries/`, `configs/`, `data/recordings/`, `tests/acceptance/`, `tests/fakes/`, `tests/conftest.py`, `tests/merged_pieces.txt`, `spec/` (except your manifest). Need a change there: stop and write it as an open question.
- The frozen tests are `tests/acceptance/test_L<n>.py`; their sha256 is in `spec/manifests/acceptance_tests_live.md`. You may add tests under `tests/unit/l<n>/`.
- Merge gate, all in your worktree: `BAYES_PIECES=L<n> .venv/bin/pytest -q tests/acceptance/test_L<n>.py` passes; `.venv/bin/pytest -q -m "not slow"` passes; `.venv/bin/ruff check src tests` and `.venv/bin/ruff format --check src tests` clean.
- Every phrase, threshold and interval comes from a registry (`registries/live.yaml`, `registries/phrasing.yaml`) through the loaders. Never retype a string the registry holds.
- No network, no live service, no credentials, never read `.env` or any keys file. Meta in tests is `tests/fakes/meta_api.py` through `httpx.MockTransport`. Stores on `tmp_path` only. Never bind a fixed port; tests use port 0.
- A fact you lack: do not invent it. If your brief's facts do not cover it, write an open question and choose the narrowest behaviour.
- Commit to your branch when the gate passes (`git add` your files only; message `L<n>: <what>`).
- Budget: stop once your record passes 250,000 tokens; write the manifest with what is done and what is left.
- Manifest (required) at `spec/manifests/L<n>.md`: files touched; tests added; every command run with its exit code; facts assumed, split VERIFIED (cite file:line or pack section) and INFERRED; open questions. No prose summary.
- Final message: branch name, last commit hash, frozen-test result line, manifest path. Nothing else.
