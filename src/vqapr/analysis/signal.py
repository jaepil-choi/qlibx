"""저장된 signal + 저장된 실현값 -> signal 품질.

구현할 것
    IC · RankIC · hit rate · decay 프로파일

왜 이것이 analysis에 있어도 되나
    IC는 저장된 signal과 저장된 실현값의 **상관**이지 return 주장이 아니다. 이 층의 규칙은
    "committed 기록만 읽는다"가 아니라 **"새 portfolio return을 만들지 않는다"**다.

**quantile spread와 signed basket return은 만들지 않는다.**
    basket 수익률을 뜻하는 지표는 signal 분석 결과가 아니라 execution spine을 지난 결과여야
    한다(PRD §2.2, §8.1). 여기서 계산하면 거래비용·체결 가능성·현금 제약을 통과하지 않은
    수치가 성과로 보고된다.

    PRD §8.1의 1층(IC·RankIC·rank-based diagnostic)은 여기, 3층(가상 execution)은 StrategyModel
    run이다. 그 경계가 이 파일의 존재 이유다.
"""
