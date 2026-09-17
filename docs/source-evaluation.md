# Integrated Source Evaluation

Updated: 2026-09-17

| Dataset | Runtime source | Role | Observed behaviour | Display label |
| --- | --- | --- | --- | --- |
| HSTECH membership and weights | Hang Seng Indexes monthly factsheet | Canonical | 30 constituents parsed and total official weight equals 100%; factsheet data date retained | Official, latest available |
| HSTECH PE | Hang Seng Indexes monthly factsheet | Canonical | Monthly index PE available; PB and historical percentile are not published in the parsed factsheet | Official, latest available |
| HSTECH minute series | Tencent Finance public day/minute endpoint | Primary free vendor | Full 1-minute cash-session series returned for the latest five trading days; current snapshot matched the independent daily close | Delayed |
| HK constituent minute series and quotes | Tencent Finance public endpoints | Primary free vendor | All 30 current factsheet constituents returned for the tested date | Delayed |
| HSTECH daily history | Sina Finance through AKShare | Cross-check and technical history | OHLC, volume and turnover returned; 2026-09-16 close matched minute-series close | Latest available |
| Southbound flow | Eastmoney through AKShare | Secondary vendor | Daily成交净买额 and vendor intraday flow series returned; intraday value is explicitly labelled as a delayed estimate | Delayed estimate / latest available |
| HK market short selling | HKEX Main Board Daily Quotations | Canonical | Official full-day ratio and turnover parsed from the exchange report; morning report uses the previous completed day | Official, latest available |
| Cross-market series | Yahoo Finance chart endpoint | Secondary vendor | Timestamped 5-minute observations returned for HSI, mainland indices, Nikkei, KOSPI, Nasdaq, NDX, SOX, HXC, USD/CNH, TNX and Brent | Delayed |
| News Event Feed | Google News RSS | Discovery layer | Original title, publisher, publisher domain, feed URL, publish time and fetch time retained | Latest available; aggregator |

## Deliberately unavailable in the first working version

- HKEX half-day short-selling history: the full-day official report is integrated, while a past midday snapshot cannot be reconstructed safely after the session.
- HSTECH futures basis: a stable free contract quote with clear month/roll methodology has not passed validation.
- Index PB and historical valuation percentile: no reliable free source has passed provenance checks.
- Exact constituent contribution: official divisor and intraday free-float/share changes are unavailable. The dashboard exposes an explicitly marked estimate.

## Failed or degraded source paths

Eastmoney general quote and minute endpoints intermittently rejected connections from the current network. They are not used as the sole source for HSTECH or constituent prices. The Stock Connect data endpoints remained available through AKShare, so those datasets stay integrated with a visible vendor label and error handling.
