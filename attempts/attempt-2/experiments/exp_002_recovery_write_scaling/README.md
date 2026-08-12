# Recovery v1 write-scaling baseline

This concluded experiment serializes synthetic schema-v1 recovery points with one committed journal
entry, trace entry, and completed decision per session. It isolates the cumulative-history write
cost before the production v2 delta-chain change; it is not a production test or helper.

Run with:

```text
uv run python experiments/exp_002_recovery_write_scaling/bench_recovery_v1.py
```

Measured in the locked project environment on 2026-08-09:

| Sessions | Last point bytes | Total bytes | Serialization seconds |
| ---: | ---: | ---: | ---: |
| 10 | 2,754 | 18,063 | 0.000143 |
| 25 | 5,919 | 84,693 | 0.000331 |
| 50 | 11,194 | 301,243 | 0.001041 |
| 100 | 21,747 | 1,129,971 | 0.003849 |

Doubling from 50 to 100 sessions increased total bytes by 3.75x and the last point by 1.94x.
That is the cumulative-history signature the v2 chain removes from each new point.

## Post-change acceptance probe

`bench_recovery_v2.py` applies the same synthetic one-entry-per-session workload to the production
v2 payload shape. It is a serialization-shape check; behavioral chain restoration remains covered
by the production recovery tests.

| Sessions | Last point bytes | Total bytes | Serialization seconds |
| ---: | ---: | ---: | ---: |
| 10 | 937 | 10,074 | 0.000119 |
| 25 | 937 | 24,129 | 0.000089 |
| 50 | 937 | 47,554 | 0.000163 |
| 100 | 940 | 94,407 | 0.000331 |

The 100/50 total-byte ratio is 1.99, below the 2.5 acceptance ceiling. The last point changes by
three bytes only because the sequence crosses from two to three digits; it does not carry completed
session history.
