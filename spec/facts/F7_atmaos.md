# F7. AtmaOS contract (read 2026-11-03)

The repo formerly at `gh_all/atma_brain` is now `gh_all/atmaos` (its D296, commit 7aa3520, 2026-11-02). Package import name `atmaos`.

- Socket: `atmaos/src/atmaos/adapters/bayesian/base.py`, copied verbatim beside this file as `F7_atmaos_base.py.txt` (last changed in 7aa3520). `BayesianResult(Record)` fields: `posterior: dict[str, Any]`, `probability_best: dict[str, float]`, `expected_loss: dict[str, float]`, `uncertainty: dict[str, Any] = {}`, `config_hash: str`, `tool_version: str`. `BayesianTool.compare(dataset_uri, *, metric, variants, priors, window, segments) -> BayesianResult`.
- `Record` (`atmaos/src/atmaos/core/domain/models.py`): `pydantic.BaseModel` with `model_config = ConfigDict(frozen=True, extra="forbid", use_enum_values=False)`. So a result with any extra key fails validation.
- G3.4 (`atmaos/spec/03_agency.md` line 204): a Bayesian result is an `OBSERVATION` whose evidence carries tool version, dataset snapshot hash, window, metric, priors, configuration, segments, result, uncertainty, and `tool_result_id`.
- G8 (same file, line 349): G8.3 the Bayesian result is a tool result the ledger references; the model never reproduces the numbers. G8.4 recorded fixtures per platform. AtmaOS's own check: `test_bayesian_result_persisted_with_config_hash`.
- U52 (`atmaos/spec/undecided.md` line 177): the widening proposal, open, owner rules before G8's pack.
- The engine must not import `atmaos`. P11 validates against a local copy of the `BayesianResult` model reproduced from this file, with `frozen=True, extra="forbid"`.
