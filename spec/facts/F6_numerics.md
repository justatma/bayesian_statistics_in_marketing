# F6. Numerics stack, pinned on build day

Checked 2026-11-03 by `pip index versions` and by installing into the repo `.venv` (Python 3.13.15, macOS arm64, JAX CPU). All VERIFIED by install and a smoke run unless marked.

| Package | Version | Note |
|---|---|---|
| numpyro | 0.22.0 | `numpyro.infer.MCMC`, `NUTS`; `numpyro.distributions.LKJCholesky(dim, concentration)` present and samples |
| jax / jaxlib | 0.12.0.1 | CPU only |
| arviz | 1.3.0 | **ArviZ 1.x, not 0.x.** Split into `arviz-base` 1.3.1 and `arviz-stats` 1.3.3. `az.from_numpyro(mcmc)` returns an `xarray.DataTree`, not the 0.x `InferenceData`. `az.rhat`, `az.ess`, `az.mcse`, `az.bfmi`, `az.summary` exist at top level and return `DataTree`. Code written against 0.x tutorials (`idata.posterior`, `az.InferenceData`) must be checked against 1.x before use. |
| xarray | 2026.9.0 | pulled by arviz |
| numpy | 2.5.4 | |
| scipy | 1.18.1 | |
| pydantic | 2.14.2 | |
| pandas | 3.1.0 | **pandas 3**: copy-on-write default, string dtype default. |
| pyarrow | 26.0.0 | |
| pyyaml | 6.0.3 | |
| jinja2 | 3.1.6 | |
| weasyprint | 70.0 | needs system Pango (not installed yet; P10 only) INFERRED |
| httpx | 0.28.1 | connectors only |
| pytest | 9.2.0 | |
| hypothesis | 6.170.14 | |
| ruff | 0.17.3 | |
| openpyxl | 3.1.5 | reading .xlsx exports |

Smoke run (VERIFIED): a model with `Normal(0,1)` and `LKJCholesky(2, 2.0)`, NUTS, 200 warmup and 200 draws, one chain, ran; `az.from_numpyro` and `az.rhat` returned `DataTree`.

## Patterns builders must use

- Non-centered hierarchy: `z ~ Normal(0,1)`, `theta = mu + sigma * z`, with `numpyro.deterministic` for theta. INFERRED (standard NumPyro practice).
- Bivariate CTR/CVR coupling: `L ~ LKJCholesky(2, eta)`; scale by `sigma` via `jnp.diag(sigma) @ L`; draw logit offsets from `MultivariateNormal(0, scale_tril=...)` or non-centered `z @ (diag(sigma) @ L).T`. INFERRED.
- Fractional conversions: likelihood `Gamma`-based `gamma_obs` per spec §5.2, never `Poisson` on non-integers.
- Seeds: `jax.random.PRNGKey(seed)` with the recorded seed.

## Open questions

- ArviZ 1.x exact return structure for `az.summary` and `az.ess(method="tail")` must be checked by P6 against the installed package (read `help(az.ess)` in the venv, do not rely on 0.x docs).
