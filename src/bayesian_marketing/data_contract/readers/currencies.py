"""ISO 4217 alphabetic codes (list one, current funds and currencies, plus X-codes).

A code outside this set is an "unknown currency" and the row is quarantined (§5.1 C1).
``XXX`` is ISO 4217's "no currency involved" code; the reader uses it only for GA4 revenue when
neither the export, the manifest nor the client economics names a currency.
"""

from __future__ import annotations

NO_CURRENCY = "XXX"

ISO_4217: frozenset[str] = frozenset(
    """
    AED AFN ALL AMD ANG AOA ARS AUD AWG AZN BAM BBD BDT BGN BHD BIF BMD BND BOB BOV BRL BSD BTN
    BWP BYN BZD CAD CDF CHE CHF CHW CLF CLP CNY COP COU CRC CUC CUP CVE CZK DJF DKK DOP DZD EGP
    ERN ETB EUR FJD FKP GBP GEL GHS GIP GMD GNF GTQ GYD HKD HNL HTG HUF IDR ILS INR IQD IRR ISK
    JMD JOD JPY KES KGS KHR KMF KPW KRW KWD KYD KZT LAK LBP LKR LRD LSL LYD MAD MDL MGA MKD MMK
    MNT MOP MRU MUR MVR MWK MXN MXV MYR MZN NAD NGN NIO NOK NPR NZD OMR PAB PEN PGK PHP PKR PLN
    PYG QAR RON RSD RUB RWF SAR SBD SCR SDG SEK SGD SHP SLE SLL SOS SRD SSP STN SVC SYP SZL THB
    TJS TMT TND TOP TRY TTD TWD TZS UAH UGX USD USN UYI UYU UYW UZS VED VES VND VUV WST XAF XCD
    XCG XOF XPF YER ZAR ZMW ZWG ZWL
    XAG XAU XBA XBB XBC XBD XDR XPD XPT XSU XTS XUA XXX
    """.split()  # noqa: SIM905
)


def is_iso_4217(code: str) -> bool:
    return code in ISO_4217
