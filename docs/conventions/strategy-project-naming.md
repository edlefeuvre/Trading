# Strategy Project Naming Convention

All per-strategy Paperclip projects follow this naming pattern:

`[ASSET_CLASS]-[account]-[Type_With_Underscores_For_Spaces]`

## The three parts

- **Asset class** — ALL_CAPS. The dominant risk-driver class of the strategy's underlying exposure. See `config/conventions/asset-classes.md` for the canonical list.
- **Account** — lowercase. The venue or account name (e.g. `binance`, `etoro`, `ibkr`, `elysium`, `deposits`).
- **Type** — MixedCase, with `_` substituting for spaces within multi-word type names. The strategy's mandate (e.g. `Swing`, `Scalping`, `BBD_Hedged`, `Develop_Hold`, `Hold`).

## Separators

- `-` separates the three structural parts.
- `_` substitutes for spaces within a single part.
Do not conflate them.

## No versioning in names

Project lifecycle (active, archived, superseded) is handled by Paperclip's status mechanism, not by names. Do not append `-v1`, `-v2`, etc. If a strategy genuinely needs to be replaced rather than evolved, archive the old project and create a new one with a name that reflects the new mandate.

## Examples

- `BTC-binance-BBD_Hedged` — Bitcoin, Binance account, buy-borrow-die with perpetual hedge.
- `PROPERTY-elysium-Develop_Hold` — Property, Elysium account, develop-and-hold.
- `EQUITY-etoro-Swing` — Equity, eToro, swing trading.
- `EQUITY-ibkr-Scalping` — Equity, IBKR, scalping.
- `CASH-deposits-Hold` — Cash, deposits account, idle hold.
- `PRECIOUS_METALS-binance-Hold` — Tokenised gold on Binance, hold mandate.

## Authority

The CEO consults this document when setting up a new strategy project. Only the Board may amend this convention.
