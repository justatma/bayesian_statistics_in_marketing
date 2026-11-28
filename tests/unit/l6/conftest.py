"""The L6 unit tests resolve against the registry store, so they need the acceptance isolation."""

from tests.acceptance.conftest import iso  # noqa: F401  (autouse fixture)
