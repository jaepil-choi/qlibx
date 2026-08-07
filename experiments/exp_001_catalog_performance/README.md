# Catalog performance experiment

This experiment measures DuckDB connection, statement, recovery-scan, and ObservationStore costs.
Absolute seconds are machine- and load-dependent; compare call counts, ratios, and before/after runs made on the same tree.

Run from the repository root with the project `.venv`. On PowerShell, set `PYTHONPATH` only for the profiled command:

```powershell
$env:PYTHONPATH = 'experiments/exp_001_catalog_performance'
.venv/Scripts/python.exe -m pytest tests -q -s -p qxprof
.venv/Scripts/python.exe -m pytest tests -q -s -p qxprof2
Remove-Item Env:PYTHONPATH
```

```powershell
.venv/Scripts/python.exe experiments/exp_001_catalog_performance/bench_publish.py 800 operation
.venv/Scripts/python.exe experiments/exp_001_catalog_performance/bench_publish.py 800 session
.venv/Scripts/python.exe experiments/exp_001_catalog_performance/probe_conn.py
.venv/Scripts/python.exe experiments/exp_001_catalog_performance/probe_cold.py
.venv/Scripts/python.exe experiments/exp_001_catalog_performance/probe_sql.py
```

Generated captures belong only under `outputs/`. Implementation evidence copied into records must state the exact HEAD and command.

## Conclusion

The experiment is concluded and the four production changes are retained. On the same machine, a bounded 800-publish session ended at 19.5ms/publish versus 403.3ms with operation-per-connection behavior, total full-suite DuckDB connections fell 20.9%, and observation reads/normalizations fell by 68/140 calls while per-query physical verification remained in place. Exact evidence and limitations are in implementation records 046 through 049.