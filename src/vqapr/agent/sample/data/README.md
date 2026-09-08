# Sample panel — synthetic data

**This is not market data.** Every price, code and name here is synthetic. The panel was cut once
from a private KRX daily-price warehouse by `scripts/build_sample_panel.py` (record `172`) and
then transformed so that nothing in it can be matched back to a listed security:

- instrument codes are `K000001`..`K000010`, in the order the source names ranked by liquidity;
- company names (`instruments.csv`) are real names with one syllable or letter changed;
- every price is multiplied by a per-instrument scale drawn from [1.5, 2.5] and a per-observation
  jitter of ±0.3 %, so levels AND returns differ from the source;
- volumes are scaled per instrument.

What was kept is the shape a first run should meet: real KRX trading sessions from 2022-01-03 to
2024-12-30 (735 of them), one name that lists 200 sessions late (`K000010`), one that stops 250
sessions early (`K000009`) and stays tradable for three sessions after its last observation so a
position in it can be closed.

| file | rows | meaning |
|---|---|---|
| `observations.parquet` | 6,900 | `available_at` (UTC, the 15:30 KST close), `instrument`, `open`, `high`, `low`, `close` (decimal 18,4), `volume` |
| `execution.parquet` | 6,903 | `trade_at`, `instrument`, `is_tradable`, `close`: the venue table a run fills against |
| `instruments.csv` | 10 | `instrument`, `name` |
| `panel.json` | — | the counts above, the late lister and the delisted name, the generator and its seed |

`vqapr new sample --out DIR` copies these beside a strategy, an exchange and the declaration that
registers them.
