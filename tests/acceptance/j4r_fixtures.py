"""Fixtures for the J4R acceptance set (Brain join spec v0.4, J4R and A1 to A6).

The runs and releases are j4_fixtures' own: lead runs of test_L5's client built by ``refresh``
against ``FakeStore``, their saved snapshots edited per case, and notebook releases written by
``notebook.release.write_release`` into ``tmp_path / "notebook"`` under ``BAYES_NOTEBOOK_DIR``.
Nothing reads the live store, the real notebook or ``configs/``: ``J4REnv.render`` and
``J4REnv.menu`` pass the fake ``load_names`` unless a case passes its own.

Slot strings follow the J4R grammar: ``{fig:run/<run_id>/<quantity_id>}``,
``{fig:nb/<release_id>/<entry_id>/<quantity_name>}``, ``{cmp:run/<run_id>}``,
``{name:ad/<entity_id>}``, ``{date:<iso>}``, each with an optional ``|full`` or ``|start`` form
and, for fig and cmp, an optional ``#<claim_id>`` on the ref.

The fixture run's comparison has IMG2's p_best near 1. Cases that render a ``cmp`` slot set the
record to IMG3 0.621 and IMG2 0.379 with ``set_p_best``, so the record and the quantities disagree
(IMG2's ctr is the higher): a renderer that works the leader out from the quantities names IMG2.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from typing import Any

from bayesian_marketing import pipeline
from bayesian_marketing.atmaos import socket as sock
from tests.acceptance import j4_fixtures as X
from tests.acceptance.j4_fixtures import CLIENT, J4Env

UTC = dt.UTC


def fig_run(run_id: str, qid: str, form: str | None = None, claim: str | None = None) -> str:
    ref = f"run/{run_id}/{qid}" + (f"#{claim}" if claim else "")
    return "{fig:" + ref + (f"|{form}" if form else "") + "}"


def fig_nb(
    release_id: str, entry_id: str, name: str, form: str | None = None, claim: str | None = None
) -> str:
    ref = f"nb/{release_id}/{entry_id}/{name}" + (f"#{claim}" if claim else "")
    return "{fig:" + ref + (f"|{form}" if form else "") + "}"


def cmp_run(run_id: str, form: str | None = None, claim: str | None = None) -> str:
    ref = f"run/{run_id}" + (f"#{claim}" if claim else "")
    return "{cmp:" + ref + (f"|{form}" if form else "") + "}"


def name_slot(entity_id: str) -> str:
    return "{name:ad/" + entity_id + "}"


def date_slot(value: str) -> str:
    return "{date:" + value + "}"


def slot_of_token(token: str, form: str | None = None) -> str:
    """A menu item's token as a slot to write, with a form if given. The token is "the slot as
    the persona writes it, without #claim_id and without a form"; it is taken with its braces,
    and wrapped in them if it comes without."""
    t = token if token.startswith("{") else "{" + token + "}"
    return t if form is None else t[:-1] + f"|{form}}}"


class J4REnv(J4Env):
    """j4_fixtures' env, with the J4R socket calls and the snapshot edits the slot cases need."""

    def render(self, text: str, client_id: str = CLIENT, **kw: Any) -> dict[str, Any]:
        kw.setdefault("load_names", self.load_names)
        return self.in_data(lambda: sock.render_client_text(text, client_id, **kw))

    def menu(self, client_id: str = CLIENT, **kw: Any) -> dict[str, Any]:
        kw.setdefault("load_names", self.load_names)
        return self.in_data(lambda: sock.client_slots(client_id, **kw))

    def qid(self, run_id: str, ad: str, name: str) -> str:
        return self.quantity(run_id, ad, name)["quantity_id"]

    def _patch(self, run_id: str, fn: Any) -> None:
        mtime = self.snapshot_file(run_id).stat().st_mtime
        self.rewrite(run_id, fn)
        os.utime(self.snapshot_file(run_id), (mtime, mtime))
        self.snapshot(run_id)  # the edited file still loads

    def set_p_best(self, run_id: str, p_best: dict[str, float]) -> None:
        """Set the run's comparison record's p_best, and nothing else."""

        def patch(d: dict[str, Any]) -> None:
            d["comparison"]["p_best"] = dict(p_best)

        self._patch(run_id, patch)

    def set_decision(self, run_id: str, status: str) -> None:
        """Set the run's decision (the comparison's feasibility) status."""

        def patch(d: dict[str, Any]) -> None:
            d["decision"]["status"] = status
            if status != "estimable" and not d["decision"]["reasons"]:
                d["decision"]["reasons"] = [f"decision set {status} for the case"]
            if status == "below_floor":
                d["decision"]["required"] = 4000.0

        self._patch(run_id, patch)

    def comparison(self, run_id: str) -> dict[str, Any]:
        return json.loads(self.snapshot_file(run_id).read_text())["comparison"]

    def releases_dated_alike(self) -> tuple[str, str]:
        """Two releases whose day, created_at and entries' as_of all say 20 November for the
        first; the second names the first as its parent, so the first is not newest (S21)."""
        r1 = self.release(day="20261120", created_at=dt.datetime(2026, 11, 20, 15, 0, tzinfo=UTC))
        r2 = self.release(
            day="20261126", created_at=dt.datetime(2026, 11, 26, 15, 0, tzinfo=UTC), parent=r1
        )
        return r1, r2

    def releases_adversarial(self) -> tuple[str, str]:
        """test_J4's pair: r2 has the greater day and names r1 as its parent, while its
        created_at is the earlier, so created_at alone would pick r1."""
        r1 = self.release(day="20261120", created_at=dt.datetime(2026, 11, 26, 15, 0, tzinfo=UTC))
        r2 = self.release(
            day="20261126", created_at=dt.datetime(2026, 11, 20, 15, 0, tzinfo=UTC), parent=r1
        )
        return r1, r2

    def other_release(self) -> str:
        """A release of another client, with that client's config written (as test_J4 (m))."""
        from tests.acceptance.test_L5 import config

        self.write_config(config(client_id=X.OTHER))
        other_entry = X._entry(
            X.E_OTHER,
            "constraint",
            "The account spending limit is $1,500.",
            "observed",
            "account",
            quantities=[{"name": "account_spending_limit", "value": 1500, "unit": "USD"}],
        )
        return self.release([other_entry], client_id=X.OTHER)

    def snapshot_with(self, run_id: str, fn: Any) -> pipeline.RunSnapshot:
        """The run's snapshot with ``fn`` applied to its JSON, the file left as it is (P4)."""
        data = json.loads(self.snapshot_file(run_id).read_text())
        fn(data)
        return pipeline.RunSnapshot.model_validate(data)

    def release_files(
        self, release_id: str
    ) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
        folder = self.release_folder(release_id)
        catalog = json.loads((folder / "catalog.json").read_text())
        entries = [json.loads(x) for x in (folder / "entries.jsonl").read_text().splitlines()]
        srcs = [json.loads(x) for x in (folder / "sources.jsonl").read_text().splitlines()]
        return catalog, entries, srcs


# ------------------------------------------------------------------ the numeral rule's word forms

#: Every QUANTITY_WORDS entry and the -fold, -ly, -s and -th forms English has for it, written out
#: by hand here (the skeleton's ``quantity_word_forms`` is a stub). Irregular forms are the English
#: ones: "fifth", "eighth", "ninth", "twelfth", "twentieth", "twenties".
_NUMBERS = [
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
    "twenty",
    "thirty",
    "forty",
    "fifty",
    "sixty",
    "seventy",
    "eighty",
    "ninety",
    "hundred",
    "thousand",
    "million",
    "billion",
]
_PLURAL = {
    "zero": "zeros",
    "six": "sixes",
    "twenty": "twenties",
    "thirty": "thirties",
    "forty": "forties",
    "fifty": "fifties",
    "sixty": "sixties",
    "seventy": "seventies",
    "eighty": "eighties",
    "ninety": "nineties",
}
_ORDINAL = {
    "zero": "zeroth",
    "four": "fourth",
    "five": "fifth",
    "six": "sixth",
    "seven": "seventh",
    "eight": "eighth",
    "nine": "ninth",
    "ten": "tenth",
    "eleven": "eleventh",
    "twelve": "twelfth",
    "thirteen": "thirteenth",
    "fourteen": "fourteenth",
    "fifteen": "fifteenth",
    "sixteen": "sixteenth",
    "seventeen": "seventeenth",
    "eighteen": "eighteenth",
    "nineteen": "nineteenth",
    "twenty": "twentieth",
    "thirty": "thirtieth",
    "forty": "fortieth",
    "fifty": "fiftieth",
    "sixty": "sixtieth",
    "seventy": "seventieth",
    "eighty": "eightieth",
    "ninety": "ninetieth",
    "hundred": "hundredth",
    "thousand": "thousandth",
    "million": "millionth",
    "billion": "billionth",
}


def _number_forms() -> list[str]:
    out: list[str] = []
    for w in _NUMBERS:
        out.append(_PLURAL.get(w, w + "s"))
        if w not in ("zero", "one"):
            out.append(w + "fold")
        if w in _ORDINAL:
            out.append(_ORDINAL[w])
    return out


#: Forms of the non-number words, where English has them.
_OTHER_FORMS = [
    "thirds",
    "thirdly",
    "quarters",
    "quarterly",
    "dozens",
    "couples",
    "handfuls",
    "scores",
    "mostly",
    "majorities",
    "minorities",
    "doubles",
    "doubly",
    "triples",
    "triply",
    "singles",
    "singly",
    "solely",
    "severally",
]

WORD_FORMS: tuple[str, ...] = tuple(dict.fromkeys(_number_forms() + _OTHER_FORMS))

# ------------------------------------------------------------------ Unicode numerals (J4R checks)

#: 50 characters of category Nd, No or Nl from many scripts; the test asserts each category.
NUMERIC_CHARS: tuple[str, ...] = (
    "0",
    "7",
    "\u0663",  # ARABIC-INDIC DIGIT THREE
    "\u06f4",  # EXTENDED ARABIC-INDIC DIGIT FOUR
    "\u096b",  # DEVANAGARI DIGIT FIVE
    "\u09ec",  # BENGALI DIGIT SIX
    "\u0e57",  # THAI DIGIT SEVEN
    "\u0f23",  # TIBETAN DIGIT THREE
    "\u1044",  # MYANMAR DIGIT FOUR
    "\u17e5",  # KHMER DIGIT FIVE
    "\u1816",  # MONGOLIAN DIGIT SIX
    "\uff19",  # FULLWIDTH DIGIT NINE
    "\U0001d7d6",  # MATHEMATICAL BOLD DIGIT EIGHT
    "\u0ae8",  # GUJARATI DIGIT TWO
    "\u0a69",  # GURMUKHI DIGIT THREE
    "\u0bed",  # TAMIL DIGIT SEVEN
    "\u0c6a",  # TELUGU DIGIT FOUR
    "\u0ce9",  # KANNADA DIGIT THREE
    "\u0d6e",  # MALAYALAM DIGIT EIGHT
    "\u0ed3",  # LAO DIGIT THREE
    "\u07c3",  # NKO DIGIT THREE
    "\U0001e953",  # ADLAM DIGIT THREE
    "\u00bd",  # VULGAR FRACTION ONE HALF
    "\u00bc",  # VULGAR FRACTION ONE QUARTER
    "\u00b2",  # SUPERSCRIPT TWO
    "\u00b3",  # SUPERSCRIPT THREE
    "\u2153",  # VULGAR FRACTION ONE THIRD
    "\u2155",  # VULGAR FRACTION ONE FIFTH
    "\u2460",  # CIRCLED DIGIT ONE
    "\u2473",  # CIRCLED NUMBER TWENTY
    "\u24ea",  # CIRCLED DIGIT ZERO
    "\u2776",  # DINGBAT NEGATIVE CIRCLED DIGIT ONE
    "\u2780",  # DINGBAT CIRCLED SANS-SERIF DIGIT ONE
    "\u3251",  # CIRCLED NUMBER TWENTY ONE
    "\u1369",  # ETHIOPIC DIGIT ONE
    "\u0bf0",  # TAMIL NUMBER TEN
    "\u09f4",  # BENGALI CURRENCY NUMERATOR ONE
    "\u2074",  # SUPERSCRIPT FOUR
    "\u2085",  # SUBSCRIPT FIVE
    "\u2189",  # VULGAR FRACTION ZERO THIRDS
    "\u2160",  # ROMAN NUMERAL ONE (NFKC: "I")
    "\u216b",  # ROMAN NUMERAL TWELVE (NFKC: "XII")
    "\u2170",  # SMALL ROMAN NUMERAL ONE (NFKC: "i")
    "\u2180",  # ROMAN NUMERAL ONE THOUSAND C D
    "\u3007",  # IDEOGRAPHIC NUMBER ZERO
    "\u3021",  # HANGZHOU NUMERAL ONE
    "\u3029",  # HANGZHOU NUMERAL NINE
    "\u16ee",  # RUNIC ARLAUG SYMBOL
    "\U00010341",  # GOTHIC LETTER NINETY
    "\U00012400",  # CUNEIFORM NUMERIC SIGN TWO ASH
)

CURRENCY_SIGNS: tuple[str, ...] = (
    "$",
    "\u20ac",  # euro
    "\u00a3",  # pound
    "\u00a5",  # yen
    "\u20b9",  # rupee
    "\u20a9",  # won
    "\u20bd",  # ruble
    "\u00a2",  # cent
    "\u20bf",  # bitcoin
    "\u0e3f",  # baht
    "\u20aa",  # shekel
    "\ufdfc",  # rial sign
)
#: ISO 4217 codes, upper case. Lower-case codes are not asserted: "all" is both ALL (the lek) and
#: an allowed word (see the manifest).
ISO_CODES: tuple[str, ...] = ("USD", "EUR", "GBP", "JPY", "INR", "CAD", "AUD", "CHF")
