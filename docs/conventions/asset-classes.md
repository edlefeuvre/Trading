# Asset Classes

Asset class in INV is determined by **dominant risk driver**, not by wrapper, venue, or settlement medium. Tokenisation is a wrapper, not an asset class.

## The canonical list

- **EQUITY** — listed shares; equity-like exposure including REITs (despite property linkage) when their day-to-day P&L is driven by equity-market behaviour.
- **FIXED_INCOME** — bonds, treasuries, anything with a coupon and maturity.
- **CASH** — fiat deposits, money-market instruments, and stablecoins (e.g. USDT) where the risk is peg/redemption rather than directional price.
- **PRECIOUS_METALS** — gold, silver, etc., including tokenised forms. The risk is the metal's price; the wrapper is irrelevant.
- **BTC** — Bitcoin specifically. Treated as its own class given size and distinct risk profile.
- **CRYPTO** — other digital-native assets (ETH, other L1s, tokens). Distinct from BTC.
- **PROPERTY** — real estate, developments, contractual property positions.
- **PRIVATE** — private equity, illiquid holdings, non-listed contractual positions.
- **DERIVATIVE** — used only where the position's risk is genuinely about the derivative instrument itself (e.g. volatility strategies). Otherwise, derivatives are classified by their underlying — a BTC perpetual short is `BTC`, not `DERIVATIVE`, because its real exposure is to BTC.

## Tie-breaker rule

Some positions don't fit one box cleanly (a convertible bond is fixed income with embedded equity optionality; a REIT is equity but tracks property; tokenised gold is precious metals but settles like crypto).

**Classify by what drives the position's day-to-day P&L.** If a position's value moves with gold's price, it is `PRECIOUS_METALS` regardless of how it is held. If a position's value moves with equity markets, it is `EQUITY` regardless of any embedded options or sector linkage.

The classification is a useful approximation for risk aggregation, not a perfect taxonomy. When genuinely uncertain, record the classification *and* a note explaining the call, so future review can revisit it.

## Authority

Only the Board may amend this list or the tie-breaker rule.
