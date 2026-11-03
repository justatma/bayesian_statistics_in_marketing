# Common rules for every builder (read once)

- Repo: your worktree of /Users/atma1/gh_all/bayesian_statistics_in_marketing on branch `piece/<P#>`. Python venv: create one in the worktree: `/opt/homebrew/bin/python3.13 -m venv .venv && .venv/bin/pip install -q -e ".[dev]"`.
- Fill in ONLY the files in your piece's file list. A diff outside it is refused at the gate, not reviewed. Never edit `src/bayesian_marketing/core/`, `registries/`, `tests/acceptance/`, `tests/fakes/`, `tests/oracle/`, `tests/conftest.py`, `tests/merged_pieces.txt`, `spec/`. If you need a core or registry change, stop and write it as an open question.
- You may add your own tests under `tests/unit/<p#>/`.
- Run your frozen tests with `BAYES_PIECES=<P#> .venv/bin/pytest -q tests/acceptance/test_<P#>.py`. Merge gate: those pass, `.venv/bin/pytest -q` passes, `.venv/bin/ruff check src tests` and `.venv/bin/ruff format --check src tests` clean.
- Neighbours you call that are not yet built: use `tests/fakes/` in your own tests; never implement a neighbour's stub.
- Every number, bound, threshold, template and phrase comes from `core.registries` (I6). Every random draw takes a recorded seed.
- No network, no live service, no credentials, never read `.env`. No LLM client imports (I4, §10 C2). httpx only in `data_contract/connectors/`.
- Persistent stores live under `BAYES_DATA_DIR` (default `data/generated/`).
- A fact you lack: do not invent it. Use the facts pack named in your brief; if absent, write it as an open question and choose the narrowest behaviour.
- Commit to your branch when the gate passes (`git add` your files only; message `P#: <what>`).
- Budget: stop once your record passes 250,000 tokens; write the manifest with what is done and left.
- Manifest (required) at `spec/manifests/<P#>.md`, the only spec/ file you may write: files touched; tests added; every command run with exit code; facts assumed, split VERIFIED (cite pack/section) and INFERRED; open questions. No prose summary.
- Final message: branch name, last commit hash, frozen-test result line, manifest path. Nothing else.
