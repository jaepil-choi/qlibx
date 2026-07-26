# qlib-extended workflow showcase

이 showcase는 synthetic data로 다음을 한 번에 검증한다.

- config-driven data loading
- 두 strategy의 process 병렬 실행
- deterministic alpha/backtest run ID와 동일 config cache reuse
- DuckDB catalog와 immutable Parquet artifacts
- 저장 alpha만 사용하는 weighted ensemble과 parent lineage
- Qlib execution/accounting backend
- HTML-only 기본 report와 optional PNG report

```powershell
uv run --group qlib python qlib-integration-codex\showcase\run_workflow.py
```

검증 결과는 `qlib-integration-codex/outputs/workflow_showcase/evidence.json`에 남는다.
