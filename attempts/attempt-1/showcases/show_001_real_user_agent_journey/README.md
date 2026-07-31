# 실제 사용자·에이전트 여정

이 showcase는 `docs/qlibx-prd.md`의 public-surface 여정을 실제 등록 데이터로 재현한다.

```powershell
uv run python showcases/show_001_real_user_agent_journey/run.py
```

실행은 등록된 logical dataset을 bounded하게 읽고, research context 조회와 proposal, frozen run,
성공·실패·invalid publication, 두 stored alpha의 ensemble, enhanced-index construction, Qlib 0.9.7
signed execution, local extension, portable artifact와 report composition을 수행한다. Upstream source를
직접 읽거나 수정하지 않으며 showcase 표시용 산출물은 이 디렉터리의 `outputs/`에만 기록한다.

PnL 기준 증거는 `experiments/exp_003_event_time_qlib_pnl`을 참조한다.
