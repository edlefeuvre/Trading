```
PAPER · WEEKLY · TS01
Sun 06 Sep 2026 06:00 UTC · engine k=5 · 12m cutoff 06 Sep 2025
book $356 → ceiling $20.00/trade ($20 floor binds)

sym              n  12m  prior R   12m R  now  new  rule
SOLUSDC         74  27*   +0.219  +0.226    1    1  positive both
UNIUSDC         37  29*   +0.135  +0.171    1    1  positive both
ETHUSDC        116  49    +0.243  +0.053  0.5    1  positive both <-- CHANGE
LTCUSDC         95  39    -0.217  +0.459  0.5  0.5  positive one
BTCUSDC        102  32    -0.338  +0.285  0.5  0.5  positive one
WLDUSDC         89  35    -0.141  +0.161  0.5  0.5  positive one
XRPUSDC         79  32    -0.084  +0.086  0.5  0.5  positive one
LINKUSDC        81  41    -0.336  +0.035  0.5  0.5  positive one
DOGEUSDC        86  35    -0.391  +0.016  0.5  0.5  positive one
AVAXUSDC        97  35    +0.091  -0.011  0.5  0.5  positive one
ORDIUSDC        95  27*   +0.081  -0.017  0.5  0.5  positive one
ADAUSDC         44  24*   +0.756  -0.101  0.5  0.5  positive one
BCHUSDC         99  38    +0.165  -0.130  0.5  0.5  positive one
1000PEPEUSDC    77  36    +0.549  -0.136  0.5  0.5  positive one
AAVEUSDC        42  34    +0.414  -0.367  0.5  0.5  positive one
ZECUSDC         30  30       —    +0.213    0    0  under 12m history
BNBUSDC         89  30    -0.117  -0.127    0    0  positive neither
ENAUSDC         84  29*   -0.067  -0.139    0    0  positive neither
NEARUSDC        72  23*   -0.023  -0.189    0    0  positive neither
FILUSDC         57  24*   -0.557  -0.270    0    0  positive neither
SUIUSDC         88  36    -0.065  -0.314    0    0  positive neither

funded 15 of 21 · 513 setups in 12m ≈ 9.8/week · * = under 30 trades (provisional)
1 proposed change(s): ETHUSDC 0.5→1
apply with:  python -m strategies.TS01_CHoCH_ICT_15m_Binance_USDCp.src.weekly --apply   (then commit with a change-log row)
```
