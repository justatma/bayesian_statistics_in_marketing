# Connector recordings

Each directory here answers one pull and is replayed by the P8 tests with sockets blocked.

| Directory | Platform | What it must hold |
|---|---|---|
| `meta/` | meta | an ad account with spend in the window |
| `meta_empty/` | meta | an ad account with no insights in the window (C6) |
| `google_ads/` | google_ads | a customer with spend in the window |
| `linkedin/` | linkedin | an ad account with spend in the window |
| `ga4/` | ga4 | a property with sessions in the window |

A directory holds `request.json` (`{"config": <ClientConfig JSON>, "window": ["YYYY-MM-DD", "YYYY-MM-DD"]}`) and one `exchange_NNNN.json` per HTTP exchange, in call order. Record mode writes both. Authorization headers, access and refresh tokens, client secrets and the values of the credential environment variables are replaced by `REDACTED` before anything is written.

Nothing in this directory is hand-made. The unit fixtures in `tests/unit/p8/` are built in the test run and never written here.

## Recording

Credentials come only from the environment variables named in `.env.example`: `META_ACCESS_TOKEN`; `GOOGLE_ADS_CLIENT_ID`, `GOOGLE_ADS_CLIENT_SECRET`, `GOOGLE_ADS_REFRESH_TOKEN` (one refresh token for Google Ads and GA4, D25); `LINKEDIN_ACCESS_TOKEN`; `GA4_PROPERTY_ID` when the config names no GA4 property. `GOOGLE_ADS_DEVELOPER_TOKEN` and `GOOGLE_ADS_LOGIN_CUSTOMER_ID` are sent only when set (D21).

From the repo root, load the environment into the shell without printing it, then record one directory per platform. The config's `accounts` must name the account the recording is for.

```sh
set -a; . ./.env; set +a

record() {  # record <platform> <dir> <account id> <start> <end>
  BAYES_RECORD_DIR="data/recordings/$2" .venv/bin/python - "$@" <<'EOF'
import datetime as dt, sys
from bayesian_marketing.core import ClientConfig
from bayesian_marketing.data_contract.connectors.pull import pull
platform, _, account, start, end = sys.argv[1:6]
config = ClientConfig(client_id="recording", timezone="UTC", currency="USD",
                      accounts={platform: account})
p = pull(platform, config, (dt.date.fromisoformat(start), dt.date.fromisoformat(end)))
print(platform, len(p.rows), "rows", len(p.quarantined), "quarantined", "empty" if p.empty_account else "")
EOF
}

record meta        meta        act_<id>   2026-10-01 2026-10-07
record meta        meta_empty  act_<id>   2026-10-01 2026-10-07
record google_ads  google_ads  <10 digits> 2026-10-01 2026-10-07
record linkedin    linkedin    <id>       2026-10-01 2026-10-07
record ga4         ga4         <property> 2026-10-01 2026-10-07
```

Set `currency` to the client currency for GA4: it is sent as `currencyCode`, so revenue comes back in it. The property's own timezone and currency are read from the response `metadata`. Record mode writes into a staging directory beside the target and replaces the target only when the pull succeeds; a failed pull leaves the existing recording as it was.

Before committing, check the files:

```sh
BAYES_PIECES=P8 .venv/bin/pytest -q tests/acceptance/test_P8.py
grep -rEn 'EAA[A-Za-z0-9]{20}|ya29\.|1//[A-Za-z0-9_-]{20}|AQ[A-Za-z0-9_-]{60}' data/recordings || echo clean
```

Real client data (D25) belongs under `data/real/`, not here. A recording of a former client's account carries their numbers into git; record from an account whose data may be committed.

## Replay

`BAYES_REPLAY_DIR=data/recordings/<dir>` makes `pull` serve every exchange from that directory. A request with no recorded exchange raises `ReplayMiss`; no socket is opened and no credential is read.
