"""§8.5 guarantee rendering from templates only (I8). Piece P4.

Only the four guarantee kinds of §4.8 have templates. A template id outside them, a registry entry
marked provisional, or a kind mismatch is refused (D15).
"""

from __future__ import annotations

from typing import get_args

from bayesian_marketing.core import Guarantee, registries

KINDS: tuple[str, ...] = get_args(Guarantee.model_fields["kind"].annotation)
LOCALES = ("en",)


class TemplateError(LookupError):
    """A guarantee whose template cannot be rendered."""


def render_guarantee(g: Guarantee, locale: str = "en") -> str:
    if locale not in LOCALES:
        raise TemplateError(f"no guarantee templates for locale {locale!r}")
    tid = g.template_id
    if tid not in KINDS:
        raise TemplateError(f"template {tid!r} is not one of the guarantee kinds {KINDS}")
    templates = registries.load("guarantee_templates")["templates"]
    if tid not in templates:
        raise TemplateError(f"no template {tid!r} in guarantee_templates")
    entry = templates[tid]
    if entry.get("provisional") or "provisional" in str(entry).lower():
        raise TemplateError(f"template {tid!r} is provisional and never rendered (D15)")
    if entry.get("kind") != g.kind:
        raise TemplateError(f"template {tid!r} is for kind {entry.get('kind')!r}, not {g.kind!r}")
    try:
        text = str(entry["text"]).format_map(g.slots)
    except KeyError as e:
        raise TemplateError(f"template {tid!r} needs slot {e.args[0]!r}") from e
    return " ".join(text.split())
