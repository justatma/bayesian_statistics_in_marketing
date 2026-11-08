"""The review tests reuse the acceptance env, so they need the acceptance isolation too."""

from tests.acceptance.conftest import iso  # noqa: F401  (autouse fixture)
