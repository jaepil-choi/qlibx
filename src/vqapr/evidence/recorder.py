"""write-only 기록 표면.

구현할 것
    Recorder (Protocol)
        append(table_id, row)
        append_batch(table_id, rows)

**읽는 메서드가 없다.**
    recorder는 되읽을 수 없다. 그래서 결과를 바꾸거나 checkpoint를 복원할 수 없고,
    `load_payload()`의 source가 아니며, diagnostic row가 남았다는 사실이 checkpoint 완료를
    증명하지 않는다.

두 종류가 공유한다
    DataModel과 StrategyModel 모두 `self.recorder`를 쓴다. StrategyModel 쪽에만 있는 자리에
    두지 않는다(architecture §4.4).

왜 DataModel에도 필요한가
    출력으로 표현할 수 없는 것이 있다. **모양이 다르다** — 출력은 살아남은 종목당 한 행이고,
    "이 30종목을 왜 뺐는가"는 카디널리티도 key도 다르다.

    recorder는 출력이 아니다. compute()가 반환한 Rows만 등록된 dataset이 되고 기록은 별도
    table로 간다. 둘을 섞으면 소비자가 진단 행까지 데이터로 읽는다.

execution 단계에 free-form 기록을 두지 않는다
    stage 집합에 EXECUTION이 있는 것과 execution 코드에 recorder를 주는 것은 다르다. 체결 쪽
    진단은 이미 구조화되어 있다(`exchange/fills.py`, `orders/batches.py`).

기록 테이블은 return의 출처가 될 수 없다
    진단 테이블에 weight와 수익률을 적고 그것으로 성과를 보고하면 척추를 우회한다(PRD §5.3).
"""
