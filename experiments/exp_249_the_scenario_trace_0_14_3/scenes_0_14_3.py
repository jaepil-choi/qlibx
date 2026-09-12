# ruff: noqa: E501, RUF001 -- prose data: long lines and typographic characters are the content
# The 0.14.3 scenario stepper: the seven scenarios traced again on the stamped 0.14.3 tree, written
# for a reader who opens the page and walks through it -- every frame says in plain words what is
# happening and why, and keeps the function names and call numbers folded beneath. Every frame
# stands on a call the profiler recorded (traces: `README.md` beside this file; tools: `exp_230`,
# plus `exp_238/trace_worker.py`).
#
# Rendered by `exp_230/render.py`, which executes this file with `REPO` bound to the tree the traces
# were taken on. A frame names its trace and call index; the renderer fills in the definition line,
# the qualified name and the milliseconds from the trace, and reads the code window from the tree.
# A number that appears anywhere here appears in a trace, in a record the traced commands wrote, or
# in the output of `exp_238/probe_panel.py` / `probe_cubes.py` (the same project, the same numbers
# as the 0.13.0 and 0.14.2 pages: the runs are deterministic, showcase digest 83/83).

DECL = "experiments/exp_235_the_scenario_trace/declarations/"


def at(file: str, needle: str, n: int = 8, before: int = 0) -> list[str]:
    """`n` source lines of `file` starting `before` lines above the first line holding `needle`."""
    lines = (REPO / file).read_text(encoding="utf-8").splitlines()  # noqa: F821 - bound by render.py
    for index, line in enumerate(lines):
        if needle in line:
            start = max(0, index - before)
            return [item.rstrip() for item in lines[start : start + n]]
    raise KeyError((file, needle))


def W(story: str, calls: str | None = None) -> str:
    """A frame's prose: the plain story first, the trace's call order folded beneath it."""
    html = f'<p class="story">{story}</p>'
    if calls:
        html += f'<details class="tr"><summary>함수 이름과 호출 번호로 보면</summary><p>{calls}</p></details>'
    return html


def F(trace: str, idx: int, title: str, story: str, calls: str | None = None, **extra) -> dict:
    return {"trace": trace, "idx": idx, "title": title, "what": W(story, calls), **extra}


HEADER = {
    "title": "vqapr 0.14.3 시나리오 디버거",
    "storage_key": "vqapr-stepper-0143",
    "eyebrow": "vqapr 0.14.3 · develop ab699614 (records 246–248 포함) · 2026-09-11 · 실제 실행을 sys.setprofile로 추적한 결과",
    "h1": "vqapr 0.14.3 시나리오 디버거 — 사용자가 하는 일 여섯 가지 + 배치 하나, 프레임워크 안에서 한 프레임씩",
    "lede": (
        "<b>이 페이지는 vqapr이 실제로 무엇을 하는지를, 실제로 돌린 기록으로 보여 줍니다.</b> "
        "<code>vqapr new sample</code>이 만든 작은 프로젝트(종목 10개, 2022-01-03 ~ 2024-12-30, 거래일 735일)에서 사용자가 할 법한 일곱 가지를 차례로 합니다: "
        "① 데이터를 <b>등록</b>하고, ② 등록이 <b>거절</b>되는 두 경우를 보고, ③ 종목별 지표(5일 모멘텀)를 만드는 <b>DataModel</b>을 돌리고, "
        "④ 그 지표로 상위 3개는 사고 하위 3개는 파는 <b>factor 전략</b>을 돌리고, ⑤ 진입가를 <b>기억</b>해 3% 빠지면 파는 <b>stop-loss 전략</b>을 돌리고, "
        "⑥ ④가 남긴 비중을 읽어 <b>enhanced index</b>를 만들고, ⑦ ④와 ⑤를 <b>동시에</b>(<code>--jobs 2</code>) 돌립니다. "
        "<b>읽는 법:</b> 프레임마다 <b>위쪽 문장</b>은 지금 일어나는 일을 보통 말로 적은 것이고, <b>아래 접힌 곳</b>에 함수 이름과 호출 번호(<code>#idx</code>)와 ms가 있습니다. 위쪽만 읽어도 흐름이 이어지도록 썼습니다. "
        "0.14.3에서 새로 달라진 자리(콜백이 읽은 것을 한 번만 만들고, 집행표는 run 기간만큼만 읽고, 심장 박동은 초당 한 번)는 그 프레임에 <b>[0.14.3]</b>으로 표시했습니다. "
        "모든 번호와 ms는 <code>sys.setprofile</code>이 실제로 기록한 값이고, 스니펫은 그 시점의 소스 줄입니다 — 상상한 것은 없습니다(<code>experiments/exp_249_the_scenario_trace_0_14_3/</code>)."
    ),
    "facts": [
        {"k": "한 줄 요약", "v": "선언 → 문 → 얼리기 → 루프 → 기록", "s": "사용자는 YAML로 <b>선언</b>하고, 프레임워크는 파일을 <b>문</b>에서 실제로 열어 재고, run은 이름을 값으로 <b>얼린</b> 뒤 시계 두 개를 <b>돌리고</b>, 결과는 <b>기록</b>이 되며 그 표가 다시 dataset이 된다"},
        {"k": "데이터", "v": "10 × 735", "s": "종목 × 거래일. run들은 2022년 1~2월의 짧은 구간만 쓴다: DataModel 16일 · factor 10일 · stop-loss 37일 · enhanced 9일"},
        {"k": "명령 16개", "v": "호출 32 … 61,659", "s": "register 973 · 거절 427 · check(거절) 48,329 · 재등록 1,294 · DataModel run 8,158 · factor 24,374 · stop-loss 61,659 · enhanced 27,311 · list 1,081 · show 32 · 배치 driver 3,492 · worker 23,353"},
        {"k": "[0.14.3] 한 번만", "v": "20 → 10 · 15 → 7", "s": "factor run에서 콜백이 읽은 것(source refs)을 만드는 횟수 20 → 10, 전략에게 \"무엇을 읽나\"를 묻는 횟수 15 → 7 (기록 246)"},
        {"k": "[0.14.3] 기간만큼만", "v": "735 → 12", "s": "10일짜리 run이 3년 집행표에서 읽는 거래일 수. 전에는 표 전체(735)를 읽고 Python이 잘랐다 (기록 247). 3년짜리 check는 전과 같이 734"},
        {"k": "[0.14.3] 초당 한 번", "v": "utime 110 → 1/s", "s": "\"살아 있다\"는 표시(lock 파일 touch)를 record chunk마다 하던 것을 초당 한 번으로 (기록 248). 계산된 숫자는 하나도 안 바뀜: showcase digest 83/83"},
        {"k": "factor run", "v": "롱 3 · 숏 3", "s": "첫날 K000003 +23주 · K000008 +8 · K000009 +94 / K000004 −55 · K000005 −19 · K000006 −12, 현금 99,463,501.24 · NAV 100,000,000 (수수료 0)"},
        {"k": "stop-loss run", "v": "9 → 0", "s": "첫날 9종목 진입 → 손절이 이어져 02-22엔 K000008 하나 → 02-23에 52주 전량 매도 → 현금 84,184,068.92"},
    ],
    "fix": (
        "<strong>ms를 읽을 때.</strong> 프로파일러가 켜진 채 잰 값이라 절대치는 실제보다 큽니다(특히 generator를 많이 쓰는 코드). 같은 트레이스 안에서 <b>서로 비교</b>만 하십시오. "
        "이 판은 디스크 캐시가 식은 상태에서 떠서 등록의 첫 parquet 스캔(<code>check_span</code>)이 2,100 ms입니다 — 두 번째 표의 같은 단계는 17 ms입니다. "
        "구조를 견줄 땐 ms가 아니라 <b>호출 횟수</b>와 <b>같은 자리의 유무</b>를 보십시오."
    ),
    "glossary_title": "먼저 알아 두면 편한 낱말 열한 개",
    "glossary": [
        ("선언 (declaration)", "당신이 쓰는 YAML. \"이 parquet은 가격이다, 이 파일은 내 전략이다, 이 run은 이렇게 돌려라.\" 레시피에 해당한다."),
        ("등록부 (workspace)", "<code>.vqapr/workspace.yaml</code>. <code>register</code>가 쓰고 모든 명령이 맨 처음 펼쳐 읽는 장부. 코드에선 <code>Workspace</code>."),
        ("문 (door)", "물리 파일을 실제로 열어 재는 <b>한 곳</b>(<code>data/validation.py</code>): 컬럼 · 키 · 기간 · 값 · 집행 가격 · digest. 등록될 때 한 번 재고, 그 뒤엔 내용이 아니라 <b>digest</b>(지문)만 대조한다."),
        ("digest (지문)", "파일 바이트의 sha256. 파일이 한 바이트라도 바뀌면 지문이 달라져 읽는 쪽이 알아챈다."),
        ("얼리기 (freeze)", "등록부의 <i>이름</i>들을 실제 <i>값</i>(코드 지문, parquet 경로와 digest, 결정 시각 목록, 초기 계좌)으로 풀어 밀봉한 것 = <code>FrozenRun</code>. 도시락에 해당한다: run 도중 레시피(등록부)가 바뀌어도 도시락은 그대로다."),
        ("판정 (judgments) · 문 하나 (verify_run)", "\"이 run을 돌려도 되나\"에 답하는 예/아니오 여럿. <code>check</code>는 전부 모아 보여 주고 <code>run</code>은 첫 거절에서 멈춘다. 둘 다 <code>verify_run</code> 한 함수를 지나며 같은 사실(<code>RunFacts</code>)을 한 번만 읽는다."),
        ("두 시계", "<b>전략 시계</b>: 결정하는 시각(매일 08:00이나 09:00, 16:00). <b>시장 시계</b>: 집행표에 가격이 있는 시각(매일 15:30). 아침에 결정하고 오후에 체결·평가한다. 트레이스의 시각은 UTC라 06:30 = 15:30 KST."),
        ("창 (window) · panel", "전략이 읽는 데이터의 사각형: 시각 × 종목. panel은 그 행렬(float64) 한 벌이고, <code>matrix()</code>는 복사 없이 그 일부를 보는 view다. run의 기간 + lookback만큼만 읽는다."),
        ("memory", "전략의 <code>self.memory</code>. 엄격한 JSON. 매 결정 전에 복원되고 뒤에 저장된다. 이것만 믿을 수 있다 — 다른 self 속성은 기록이 재현하지 못한다."),
        ("의도서 (intent)", "전략이 돌려준 목표 비중에 프레임워크가 도장을 찍은 것. 체결 시각이 올 때까지 하나만 기다린다(pending). <code>Hold</code>면 없다."),
        ("봉투 (envelope)", "모든 명령이 stdout에 내는 JSON 한 덩어리. 성공이든 거절이든 모양이 같다: <code>ok · stage · failures[code · status · requirement · observed · fix]</code>."),
    ],
}

MAP = [
    ("①", "데이터 등록", "선언 → 문 → 등록부"),
    ("②", "등록 오류", "없는 컬럼 · 바뀐 파일"),
    ("③", "DataModel", "지표를 만들어 dataset으로"),
    ("④", "factor 전략", "롱 3 · 숏 3 · 비중 저장"),
    ("⑤", "stop-loss", "memory가 진입가를 든다"),
    ("⑥", "enhanced index", "저장된 비중을 읽는다"),
    ("⑦", "--jobs 배치", "worker도 판정 · cube 한 번"),
]

SCENES = [
    # ---------------------------------------------------------------- ① register
    {
        "id": "reg", "key": "①", "title": "데이터 등록",
        "sub": "vqapr register sample.yaml · 3,166 ms · 973 호출 (그중 2,100 ms는 식은 디스크의 첫 parquet 스캔)",
        "story": (
            "<b>무슨 일인가:</b> 당신이 YAML 한 장(<code>sample.yaml</code>)을 건넵니다. 거기엔 \"종목 명단은 이 파일, 가격은 이 parquet, 체결 가격은 저 parquet, 전략 코드는 이 파일, run은 이렇게\"가 적혀 있습니다. "
            "vqapr은 이 문서를 그대로 믿지 않습니다. 세관처럼 <b>파일을 실제로 열어</b> 적힌 대로인지 재고 지문(digest)을 남기고, 전략 코드를 <b>실제로 import</b>해 약속한 모양인지 본 다음에야 장부(등록부) 한 파일을 씁니다. "
            "뒤의 여섯 시나리오는 전부 이 장부 위에서 일어납니다."
        ),
        "frames": [
            F("01_register", 0, "명령줄이 register 핸들러를 고른다",
              "터미널에서 <code>vqapr register sample.yaml</code>을 칩니다. 프로그램은 어느 동사인지(register) 알아보고 프로젝트 폴더를 정한 뒤 register 담당에게 넘깁니다. 3,166 ms의 거의 전부는 그 담당 안에서 씁니다. 무엇이 잘못되든 결과는 같은 모양의 JSON 봉투로 나옵니다.",
              "<code>build_parser</code>(#1, 16.9 ms) → <code>_resolve_project_root</code>(#10) → <code>register.run</code>(#11, 3,145.6 ms) → <code>read_yaml_mapping</code>(#12, 22.6 ms) → <code>apply</code>(#13, 3,122.7 ms).",
              fn="main() → register.run()", code=at("src/vqapr/cli/main.py", "def main(", 14),
              mem={"argv": "['--project-root', '.../sample', 'register', '.../sample/sample.yaml']"}, disk={".vqapr/": "없음"}),
            F("01_register", 14, "장부는 마지막에 한 번만 쓴다 — 트랜잭션",
              "장부를 바로 고치지 않고 <b>장바구니</b>를 하나 엽니다. 명단 → 데이터 → 코드 → run 순서로 검사한 것을 장바구니에 담아 두었다가 맨 끝에 한 번에 씁니다. 중간에 하나라도 거절되면 장바구니째 버려서 장부는 한 글자도 안 바뀝니다. 순서가 이런 이유: run은 전략 이름과 데이터 이름을 가리키므로 그것들이 먼저 있어야 합니다.",
              "<code>Workspace.transaction</code>(#15, 0.6 ms) → <code>_require_declared_ids</code>(#25) → <code>_instruments</code>(#43, 432.7 ms) → datasets(#136 · #328) → components(#468 · #614) → runs(#877) → <code>commit</code>(#902).",
              fn="_apply() — 섹션 순서", code=at("src/vqapr/project/registration.py", 'for dataset_id, body in section("datasets")', 7),
              mem={"document": "dict (instruments 1, datasets 2, components 2, runs 1)", "transaction.staged": "[]"}),
            F("01_register", 46, "종목 명단부터 실제로 열어 본다",
              "종목 명단 parquet(10종목)을 엽니다. 파일이 없거나 필요한 컬럼이 없으면 예외로 터지는 게 아니라 \"무엇이 없다\"는 진단으로 돌아와 다른 거절 옆에 나란히 놓입니다. 413 ms는 10행짜리 표의 값이 아니라 이 프로세스가 parquet 라이브러리(pyarrow)를 처음 올리는 비용입니다.",
              "<code>verify_roster</code>(#46, 413.0 ms) → <code>build_roster</code>(#50, 1.5 ms: <code>instrument</code> ×10) → <code>Transaction.register_instruments</code>(#83).",
              fn="verify_roster()", code=at("src/vqapr/data/validation.py", "def verify_roster", 12),
              mem={"transaction.staged": "[instruments: stock 10, digest 875b5fe1…]"}),
            F("01_register", 136, "가격 parquet을 열어 여섯 가지를 잰다 — 문",
              "선언은 \"<code>available_at</code>이 시각이고 <code>close</code>가 숫자이고 (시각, 종목)이 겹치지 않는다\"고 말합니다. 문은 파일을 열어 순서대로 확인합니다: ① 컬럼과 타입이 맞나 → ② 키에 빈 값·중복이 없나 → ③ 첫 날과 끝 날은 언제인가 → ④ 숫자에 NaN·무한대가 없나 → ⑤ 체결 가격 역할이 있나(이 표엔 없음) → ⑥ 지문(sha256). "
            "여기가 이 파일이 <b>내용으로</b> 검사되는 유일한 자리입니다. 뒤의 모든 명령은 지문만 대조합니다. 2,100 ms는 이 프로세스의 첫 duckdb 스캔(디스크 캐시가 식음)이고 두 번째 표의 같은 단계는 17 ms입니다.",
              "<code>verify_source</code>(#136, 2,457.1 ms) → <code>describe</code>(#137, 209.6 ms) → <code>check_schema</code>(#149, 15.3 ms) → <code>check_key</code>(#192, 92.8 ms) → <code>check_span</code>(#213, 2,100.6 ms) → <code>check_values</code>(#224, 37.0 ms) → <code>check_execution_prices</code>(#276, 0.003 ms) → <code>physical_digest</code>(#278, 0.9 ms) → <code>Transaction.register_dataset</code>(#282) → <code>spoken</code>(#288).",
              fn="verify_source() — 여섯 단계", code=at("src/vqapr/data/validation.py", "def verify_source", 14),
              mem={"measured.span": "2022-01-03 15:30 ~ 2024-12-30 15:30 +09:00", "measured.source_digest": "18bb7017…"}),
            F("01_register", 436, "집행표는 한 가지를 더 잰다 — 거래 가능한 날엔 가격이 있나",
              "체결에 쓸 표(<code>sample-execution</code>)는 \"이 컬럼이 거래 가능 여부다\"라고 선언했습니다. 그래서 문이 한 가지를 더 묻습니다: 거래 가능하다고 적힌 행마다 가격이 양수인가? 답(<code>['close']</code>)을 장부에 적어 두면, 나중에 run이 \"close로 체결\"이라고 할 때 표를 다시 뒤지지 않고 이 답만 봅니다.",
              "<code>verify_source</code>(#328, 128.6 ms) → <code>check_schema</code>(#338, 17.8 ms) → <code>check_key</code>(#370, 20.6 ms) → <code>check_span</code>(#391, 16.7 ms) → <code>check_values</code>(#402, 18.8 ms) → <b><code>check_execution_prices</code>(#436, 35.7 ms)</b> → <code>physical_digest</code>(#453, 0.6 ms) → <code>register_dataset</code>(#459).",
              fn="check_execution_prices()", code=at("src/vqapr/data/validation.py", "def check_execution_prices", 14),
              mem={"measured.execution_prices": "('close',)", "measured.source_digest": "49e4b4ab…"}),
            F("01_register", 552, "전략과 거래소 코드는 실제로 import해서 약속한 모양인지 본다",
              "전략 파일(<code>reversal_5d.py</code>)의 지문을 찍고, 실제로 import해서 \"전략이라면 있어야 할 메서드가 맞는 시그니처로 있나\"를 봅니다. 거래소 코드도 같은 길입니다. 옛날 시그니처로 쓴 코드는 여기서 이름을 대며 거절됩니다. 오늘은 둘 다 통과해 장바구니에 담깁니다.",
              "<code>_component</code>(#468, 21.9 ms) → <code>fingerprint_component</code>(#472, 0.8 ms) → <code>conformance</code>(#552, 15.9 ms) → <code>_check_methods</code>(#599) → <code>register_component</code>(#608) · 거래소 <code>_component</code>(#614, 32.2 ms) → <code>conformance</code>(#722, 24.1 ms) → <code>register_component</code>(#812).",
              fn="conformance()", code=("def", 10),
              mem={"transaction.staged": "[instruments, sample-prices, sample-execution, sample-reversal-5d, sample-exchange]"}),
            F("01_register", 902, "run을 담고, 장부를 한 번에 쓴다",
              "마지막으로 run 선언(어느 전략, 어느 데이터, 언제부터 언제까지, 초기 현금)을 담습니다. 그리고 사람 말로 푼 문장이 봉투에 들어갑니다: \"<i>dataset 'sample-prices'의 행은 available_at 시각부터 알 수 있고 그보다 먼저는 아니다</i>\", \"<i>run 'sample-run'은 결정 다음 첫 체결 시각 15:30에 close 가격으로 체결한다</i>\". "
              "commit이 잠금을 잡고 장부를 한 번 읽어 담아 둔 것을 합친 뒤 <b>한 번</b> 씁니다. 디스크에 처음으로 <code>.vqapr/workspace.yaml</code>이 생깁니다.",
              "<code>register_run</code>(#877) → <code>RunDefinition.spoken</code>(#889) → <code>Transaction.commit</code>(#902, 28.8 ms) → <code>Workspace._write</code>(#924, 23.6 ms) → <code>_write_roster</code>(#963) → <code>success</code>(#967).",
              fn="Transaction.commit()", code=("def", 16),
              disk={".vqapr/workspace.yaml": "datasets 2 (source_digest · execution_prices) · components 2 · runs 1", ".vqapr/instruments.json": "stock 10, digest 875b5fe1…"}),
        ],
        "remember": [
            "파일은 등록될 때 문에서 한 번 잰다: 컬럼 → 키 → 기간 → 값 → 체결 가격 → 지문. 그 결과가 장부에 남는다.",
            "명단 · 가격표 · 집행표 · 코드, 넷 다 실제로 열어 본 뒤에야 장부를 쓴다. 쓰기는 마지막에 한 번.",
        ],
    },
    # ---------------------------------------------------------------- ② registration errors
    {
        "id": "err", "key": "②", "title": "등록 오류 — 없는 컬럼, 바뀐 파일",
        "sub": "register bad.yaml · 70 ms · 427 호출 (거절) — check sample-run · 2,776 ms · 48,329 호출 (거절) — register sample.yaml 다시 · 903 ms · 1,294 호출",
        "story": (
            "<b>무슨 일인가:</b> 실수를 두 가지 저지릅니다. 먼저 파일에 <b>없는 컬럼</b>(<code>adj_close</code>)을 선언한 dataset을 등록해 봅니다 — 문이 파일을 열어 보고 \"그런 컬럼 없다\"고 이름을 대며 거절하고, 장부는 그대로입니다. "
            "다음엔 등록이 끝난 뒤 집행표 parquet을 <b>다른 내용으로 덮어씁니다</b>(마지막 날을 뺀 유효한 파일). <code>check</code>는 표를 다시 뒤지지 않고 지문 하나를 대조해 \"파일이 바뀌었다\"고 막고, 고치는 법까지 말합니다: 같은 선언으로 다시 등록하라. 그러면 잰 값만 새로 갈립니다."
        ),
        "frames": [
            F("02_register_bad", 396, "문이 파일을 열어 첫 단계에서 멈춘다",
              "선언은 \"<code>observations.parquet</code>에 <code>adj_close</code>가 있다\"고 말합니다. 문이 파일의 컬럼 목록을 읽어 대조합니다: 없습니다. 그 뒤 단계(키 · 기간 · 값 · 지문)는 돌지 않습니다 — 컬럼이 틀린 파일에 키를 묻는 건 뜻이 없으니까요.",
              "<code>_dataset</code>(#354) → <code>verify_source</code>(#383, 20.2 ms) → <code>describe</code>(#384, 15.7 ms) → <code>check_schema</code>(#396, 4.3 ms) → <code>Diagnosis.ok</code>(#411) = False → <code>raise_if_failed</code>(#412).",
              fn="check_schema()", code=at("src/vqapr/data/validation.py", "def check_schema", 12),
              mem={"observed": "available_at, close, high, instrument, low, open, volume"}),
            F("02_register_bad", 417, "거절 봉투: 무엇이 · 왜 · 어떻게 고치나 — 그리고 장부는 그대로",
              "봉투 한 장이 나옵니다. code <code>dataset.field_missing</code>(400) · 요구 \"<i>fields[adj_close]가 말한 컬럼 'adj_close'가 있어야 한다</i>\" · 관찰 \"<i>있는 컬럼은 available_at, close, high, …</i>\" · 고치는 법 \"<i>adj_close 컬럼을 넣거나 있는 컬럼을 가리켜라</i>\" · 위치 <code>datasets.sample-adjusted.fields[adj_close]</code>. "
              "<code>mutation: false</code> — 장바구니는 열렸지만 쓰이지 않았습니다. exit 1.",
              "<code>raise_if_failed</code>(#412) → <code>envelope.failure</code>(#417, stage register) → <code>emit</code>(#426) → exit 1.",
              fn="envelope.failure()", code=("def", 10),
              disk={".vqapr/workspace.yaml": "바뀌지 않음 (mutation: false)"}),
            F("03_check_changed", 336, "check는 문 하나를 지난다 — verify_run",
              "집행표가 바뀐 채로 <code>check sample-run</code>. check는 장부를 열고 run 선언을 꺼내 <b>verify_run</b> 한 함수에 넘깁니다. 이 함수가 두 가지를 한 번의 읽기로 합니다: 판정 여럿을 <b>모아서</b> 답하기(check가 보여 줄 것)와 얼리기 시도(run이 쓸 것). "
              "둘은 같은 사실 그릇(<code>RunFacts</code>)에서 읽으므로 같은 것을 두 번 읽지 않습니다. 돌아오는 답(<code>RunVerdict</code>)엔 거절 · 답하지 못한 판정 · 얼린 run 또는 얼리기가 낸 거절이 함께 들어 있습니다.",
              "<code>check</code>(#12, 2,753.8 ms) → <code>Workspace.open</code>(#14, 25.2 ms) → <code>run_definition</code>(#334) → <code>verify_run</code>(#336, 2,727.7 ms) → <code>RunFacts.__init__</code>(#337) → <code>judgments</code>(#338, 2,720.6 ms) → … → <code>preflight_run</code>(#48207, 6.9 ms) → <code>Failure.as_dict</code>(#48314) → <code>emit</code>(#48328).",
              fn="verify_run() — 문 하나", code=at("src/vqapr/flow/declaration/verify.py", "facts = RunFacts(workspace, definition)", 10, before=1),
              mem={"verdict": "failures 1 (dataset.source_changed) · blocked 1 (judgment.blocked: execution_ordering) · frozen None · refusal VqaprError"}),
            F("03_check_changed", 338, "판정 일곱 개가 차례로 답한다 — 사실은 한 번만 읽는다",
              "판정은 일곱입니다: 종목 집합 · 명단 · 기간 · <b>집행 순서</b> · 읽을 dataset들 · 비중 · 출력. 집행 순서 판정이 \"결정 시각 목록(agenda)을 달라\"고 하자 그릇이 처음이라 만듭니다 — 이 run은 3년짜리라 734일, 2,338 ms(그중 집행표의 시각 열 읽기는 일부, 나머지는 하루마다 결정 시각 객체를 만드는 Python 시간). "
              "그 뒤 얼리기가 같은 agenda를 물으면 그릇이 <b>돌려주기만</b> 합니다. 예전엔 여기서 또 한 번 2초를 썼습니다. <b>[0.14.3]</b> 시각 열을 run 기간만큼만 읽게 됐지만 이 run은 3년 전체라 읽는 양은 그대로입니다(④에서 달라집니다).",
              "<code>judgments</code>(#338) → <code>_judge_universe</code>(#350) · <code>_judge_roster</code>(#352, 1.3 ms) · <code>_judge_period</code>(#359) · <code>_judge_execution_ordering</code>(#361, 2,553.7 ms) → <code>RunFacts.agenda</code>(#362) → <code>_once</code>(#363) → <code>derived_agenda</code>(#365, 2,338.4 ms) → <code>_session_bounds</code>(#366) … <code>inclusive_slice</code>(#42207, 208.8 ms) → <code>RunFacts.execution_table</code>(#45876, 6.0 ms) · <code>_judge_member_datasets</code>(#45918, 119.3 ms) · <code>_judge_weights</code>(#48204) · <code>_judge_outputs</code>(#48206).",
              fn="RunFacts._once() — 한 번 읽고 나눠 준다", code=at("src/vqapr/flow/declaration/preflight.py", "def _once(", 10),
              tip="여기서 큰 것은 표 스캔이 아니라 agenda 만들기(2.3 s, 프로파일러 아래)입니다. 프로파일러 없이 재면 이 check는 약 0.1 s입니다(기록 240)."),
            F("03_check_changed", 361, "집행 순서 판정은 run이 실제로 걷는 날들만 묻는다",
              "이 판정은 \"결정마다 그 다음에 체결할 시각이 있나\"를 봅니다. 예전엔 날짜 범위의 상위집합을 그대로 돌아서, end가 체결과 결정 사이에 놓인 옳은 선언이 500으로 죽었습니다(testbed 보고 099, 기록 237). 이제 얼리기가 쓰는 것과 같은 조각(<code>inclusive_slice(start, end)</code>)만 돕니다. 이 run은 end가 23:59:59라 잘리는 건 없지만, 자리가 트레이스에 보입니다.",
              "<code>_judge_execution_ordering</code>(#361) → <code>RunFacts.agenda</code>(#362) → … → <code>OperationAgenda.inclusive_slice</code>(#42207, 208.8 ms) → <code>RunFacts.execution_table</code>(#45876, 6.0 ms) → <code>Workspace.require_verified</code>(#45880).",
              fn="_judge_execution_ordering() — inclusive_slice", code=at("src/vqapr/flow/declaration/judgments.py", "inclusive_slice(", 12, before=3)),
            F("03_check_changed", 45891, "표를 다시 뒤지지 않는다 — 지문 하나를 대조한다",
              "집행표를 쓰려면 장부에 \"이 dataset은 아직 등록 때 그대로인가\"를 물어야 합니다. 장부에 적힌 지문 <code>49e4b4ab…</code>와 지금 파일의 지문 <code>bf30cb34…</code>(0.9 ms)가 다릅니다 → <code>dataset.source_changed</code>(412): \"<i>run이 읽는 바이트는 등록이 잰 바이트여야 한다</i>\", 고치는 법 \"<i>vqapr register &lt;선언 파일&gt;로 다시 등록하라</i>\". "
              "그릇은 실패도 기억합니다: 뒤에 얼리기가 같은 표를 물으면 저장해 둔 같은 예외를 다시 던집니다(6.9 ms) — 다시 해시하지 않습니다.",
              "<code>RunFacts.execution_table</code>(#45876) → <code>Workspace.require_verified</code>(#45880, 5.8 ms) → <code>physical_digest</code>(#45889, 0.9 ms) → <code>require_verified</code>(#45891, 4.3 ms) → 거절 · 판정을 blocked로 감싼다 → <code>_judge_member_datasets</code>(#45918) … <code>preflight_run</code>(#48207, 6.9 ms: 저장된 예외).",
              fn="require_verified()", code=at("src/vqapr/data/validation.py", "def require_verified", 14),
              mem={"registered": "49e4b4abef4f…", "file now": "bf30cb34b1ca…"},
              caution="봉투: checked [workspace, run, judgments, preflight] · passed [workspace, run] · failures [dataset.source_changed] · blocked [judgment.blocked: \"execution_ordering이 답하지 못했다\", cause에 예외 전체]. 답하지 못한 판정과 그 원인은 따로따로 실린다(오너 결정 2026-09-04)."),
            F("04_register_again", 643, "같은 선언으로 다시 등록한다 — 잰 값만 다시 잰다",
              "<code>register sample.yaml</code>을 다시 칩니다. 선언은 한 글자도 안 바뀌었고 파일만 다릅니다. 문이 두 표를 다시 잽니다(가격표 182.5 ms · 집행표 113.1 ms): 기간, 지문(<code>bf30cb34…</code>), 체결 가격. 장바구니에 담을 때 기존 등록과 비교합니다.",
              "<code>_apply</code>(#14, 856.1 ms) → <code>verify_source</code>(#451, 182.5 ms) → <code>_merge_dataset</code>(#601) · <code>verify_source</code>(#643, 113.1 ms) → <code>_merge_dataset</code>(#778).",
              fn="verify_source() 다시", code=("def", 8)),
            F("04_register_again", 778, "선언한 반쪽이 같으면 잰 반쪽만 갈아 끼운다",
              "등록엔 두 반쪽이 있습니다. 당신이 쓴 반쪽(컬럼 · 키 · 단위)과 문이 잰 반쪽(기간 · 지문 · 체결 가격). 비교기는 \"기존 등록의 잰 반쪽을 새 측정으로 바꾸면 새 등록과 같은가\"를 봅니다. 같다 → 선언은 그대로이니 받아들입니다. 컬럼 이름 하나라도 달랐다면 \"이미 등록된 이름\"(409)으로 거절했을 겁니다. "
              "이 페이지의 run들은 원본 파일로 되돌린 뒤 한 번 더 등록한 상태에서 돌았습니다.",
              "<code>_merge_dataset</code>(#778) → … <code>Transaction.commit</code>(#1217, 16.3 ms) → <code>Workspace._write</code>(#1245, 11.3 ms) → <code>success</code>(#1288).",
              fn="_merge_dataset() — remeasured", code=at("src/vqapr/project/merge.py", "remeasured = replace(", 12, before=6),
              disk={".vqapr/workspace.yaml": "sample-execution.source_digest: 49e4b4ab… → bf30cb34… (그 뒤 원본으로 되돌려 한 번 더 등록)"}),
        ],
        "remember": [
            "거절 봉투는 code · 요구 · 관찰 · 고치는 법 · 위치를 들고, 장부는 안 바뀐다.",
            "등록 뒤 파일이 바뀌면 지문 하나로 알아챈다. 고치는 법은 같은 선언으로 다시 등록하는 것.",
        ],
    },
    # ---------------------------------------------------------------- ③ datamodel
    {
        "id": "dm", "key": "③", "title": "DataModel — 지표를 만들어 dataset으로",
        "sub": "register features.yaml · 74 ms · 647 호출 — run sample-features-run · 1,431 ms · 8,158 호출 · 16일 · 108행",
        "story": (
            "<b>무슨 일인가:</b> <code>features.py</code>의 <code>SampleFeatures</code>는 날마다 종목별 <b>5일 모멘텀</b>(여섯 종가 중 마지막 ÷ 첫 번째 − 1)을 계산하는 DataModel입니다. 사고파는 게 없으니 이 run엔 전략 시계(매일 16:00)만 있고 시장 시계가 없습니다. "
            "첫 나흘은 종가가 여섯 개가 안 돼 빈 목록, 2022-01-10부터 종목당 한 행(K000010은 이 구간에 종가 여섯 개가 없어 빠짐). run이 끝나면 108행(12일 × 9종목)이 parquet이 되고 <b>①과 똑같은 문</b>을 지나 dataset <code>sample-features</code>로 등록됩니다. 다음 run은 이것을 벤더 표와 똑같이 읽습니다."
        ),
        "frames": [
            F("06_run_features", 470, "run도 같은 문을 지난다 — 판정하고 얼린다",
              "장부를 열고 run 선언을 꺼내 <code>verify_run</code>에 넘깁니다(164 ms): 판정 151 ms, 얼리기 12 ms. 얼리기는 모델을 import해 \"무엇을 읽나\"를 묻는데, 이 import는 판정이 이미 한 것을 그릇에서 받습니다. <b>[0.14.3]</b> 집행표가 없는 datamodel run은 <code>days_from</code>의 가격표에서 거래일을 읽는데, 이제 run 기간 ± 1일(18일)만 읽습니다 — 전에는 735일 전부.",
              "<code>_run_one</code>(#12) → <code>Workspace.open</code>(#14, 28.6 ms) → <code>verify_run</code>(#470, 164.0 ms) → <code>judgments</code>(#472, 151.4 ms) → <code>preflight_run</code>(#1754, 11.9 ms) → <code>_freeze_datamodel</code>(#1766, 8.3 ms) → <code>_freeze_sources</code>(#1959, 1.6 ms).",
              fn="verify_run()", code=at("src/vqapr/flow/declaration/verify.py", "facts = RunFacts(workspace, definition)", 10, before=1),
              mem={"거래일 읽기": "_local_date ×18 (0.14.2: ×735)"}),
            F("06_run_features", 1972, "얼리기 — 읽을 dataset이 등록 때 그대로인지 지문으로 확인",
              "이 모델이 읽는 <code>sample-prices</code>가 아직 등록 때 파일인지 지문 한 번으로 봅니다(1.2 ms). 같습니다. 얼린 run에 그 지문이 들어가 \"이 run은 이 바이트를 읽었다\"가 기록에 남습니다. 파일 내용은 여기서도 읽지 않습니다.",
              "<code>_freeze_sources</code>(#1959) → <code>Workspace.require_verified</code>(#1961, 1.2 ms) → <code>require_verified</code>(#1972, 0.05 ms).",
              fn="require_verified()", code=at("src/vqapr/data/validation.py", "def require_verified", 14),
              mem={"frozen.source_digests": "{sample-prices-source: 18bb7017…}"}),
            F("06_run_features", 2012, "문이 만든 것을 run이 그대로 받는다 — RunResources",
              "얼린 run은 기록에 적히는 <b>값</b>이라 살아 있는 모델 객체를 들 수 없습니다. 그래서 예전엔 run이 시작하며 모델을 다시 import했습니다. 이제 문이 이미 든 객체와 잘라 둔 기간을 <code>RunResources</code>라는 봉지에 담아 함께 넘기고(0.4 ms — 새로 읽는 건 없음), run은 그것을 씁니다. 다른 run의 봉지면 거절합니다.",
              "<code>RunResources.of</code>(#2012, 0.4 ms) → <code>RunVerdict.require_ready</code>(#2020) → <code>run</code>(#2022, 1,221.0 ms, resources=…) → <code>_run_datamodels</code>(#2030) → <code>_run_datamodel</code>(#2077) → <code>_run_member</code>(#2115, 1,211.5 ms).",
              fn="RunResources.of()", code=at("src/vqapr/flow/declaration/verify.py", "def of(cls, facts: RunFacts, frozen: FrozenRun)", 12),
              mem={"resources": "datamodel=SampleFeatures 인스턴스(판정이 import한 것) · strategy None · exchange None"}),
            F("06_run_features", 2118, "데이터 창고가 run의 기간을 안다",
              "run 하나의 도구들(스캔 세션 · 데이터 창고 · 기록 쓰기 · 창 만들기)을 만듭니다. 창고(store)는 이 run의 기간(01-04 ~ 01-25)과 모델이 읽겠다고 선언한 것들을 받아 두고, 뒤의 모든 읽기를 그 범위로 자릅니다. 3년 표에서 3주만 읽는 이유가 여기 있습니다.",
              "<code>_run_member</code>(#2115) → <code>_horizon</code>(#2118) → <code>DuckDbObservationStore.__init__</code> → <code>body</code>(#2130, 1,204.5 ms) → <code>RunOutput.__init__</code>(#2133) → <code>datamodel_loop</code>(#2137).",
              fn="_horizon() → DuckDbObservationStore(horizon=…)", code=at("src/vqapr/flow/orchestration.py", "horizon=_horizon(frozen)", 10, before=4),
              mem={"horizon": "(2022-01-04 00:00, 2022-01-25 23:00) +09:00", "requirements": "[sample-prices.close, RowsLookback(rows=6)]"}),
            F("06_run_features", 2137, "루프는 하나, 시장 시계만 없다",
              "전략 run과 <b>같은</b> 루프 클래스(<code>RunLoop</code>)를 씁니다. 다른 건 두 가지뿐: 부품이 DataModel용이고, 시장 시계가 없습니다. 조립하면서 모델의 <code>inputs()</code>를 <b>한 번</b> 물어 무엇을 읽을지 알아 둡니다. 루프가 열리고 16개의 결정 시각을 차례로 처리합니다.",
              "<code>datamodel_loop</code>(#2137, 4.7 ms) → <code>SampleFeatures.inputs</code>(#2139) → <code>RunLoop.run</code>(#2253, 966.9 ms) → <code>start</code>(#2254) → <code>events</code>(#2257) → <code>RunLoop.handle</code> ×16 (#2395 …) → <code>finish</code>(#7726).",
              fn="datamodel_loop()", code=at("src/vqapr/flow/run/loop.py", "def datamodel_loop", 12)),
            F("06_run_features", 2474, "첫 창 — 어디부터 어디까지 읽을지 먼저 정한다",
              "2022-01-04 16:00, 모델이 처음으로 \"종가를 달라\"고 합니다. 창고는 읽기 전에 범위를 정합니다: 여섯 행이 필요하니 run 시작(01-04) 앞의 가장 이른 날을 원천의 날짜 격자에서 세고(하한 01-03 15:30), 상한은 run 끝(01-25 23:00). 그 사이만 스캔합니다(462.7 ms — 이 프로세스의 첫 스캔). 예전(0.12.0)엔 여기서 3년 전체를 읽었습니다.",
              "<code>compute</code>(#2438) → <code>_DeclaredReads.read</code>(#2439) → <code>ModelWindow.panel</code>(#2458) → <code>panel_window</code>(#2459, 739.3 ms) → <code>_scan_bounds</code>(#2474, 61.4 ms) → <code>observation_table</code>(#3222, 462.7 ms) → <code>Panel.from_table</code>(#3259).",
              fn="_scan_bounds() — lookback 하한", code=at("src/vqapr/data/store.py", "for lookback in lookbacks:", 10, before=2),
              mem={"bounds": "2022-01-03 15:30 ~ 2022-01-25 23:00 +09:00 (probe_panel.py로 잰 값)"}),
            F("06_run_features", 3259, "panel — 날짜 × 종목 행렬 한 벌",
              "스캔이 준 표(시각 · 종목 · 종가)를 (17일 × 10종목) 숫자 행렬 하나로 접습니다. 없는 칸은 NaN. 이 뒤 16번의 계산은 전부 이 행렬의 일부를 <b>복사 없이</b> 봅니다(view). 210 ms는 이 프로세스에서 numpy 행렬을 처음 만드는 비용이고, ④·⑥의 같은 자리는 1 ms입니다.",
              "<code>Panel.from_table</code>(#3259, 210.4 ms) → <code>placement</code>(#3260, 207.8 ms) → <code>dense_block</code>(#3262, 0.6 ms) → <code>PanelWindow.matrix</code>(#3271, 0.08 ms).",
              fn="Panel.from_table() — 블록", code=at("src/vqapr/data/panel.py", "blocks[name] = dense_block(", 10, before=6),
              mem={"panel.blocks['close'].shape": "(17, 10)", "panel.bounds": "01-03 15:30 ~ 01-25 23:00"}),
            F("06_run_features", 2438, "첫날 — 종가가 두 개뿐이라 빈 목록",
              "저자 코드입니다. <code>window.matrix()</code>로 행렬을 보니 01-04 16:00에 알 수 있는 행은 2개(01-03 · 01-04). 여섯 개가 필요하니 <code>[]</code>를 돌려줍니다. 프레임워크는 빈 목록을 그대로 받습니다. 이 첫 계산 740 ms는 거의 전부 위의 첫 스캔이고, 다음 날부터는 2 ms입니다.",
              "<code>RunLoop.handle</code>(#2395, 742.5 ms) → <code>_window_factory.at</code>(#2402, 01-04 16:00) → <code>SampleFeatures.compute</code>(#2438, 740.4 ms) → … → <code>PanelWindow.matrix</code>(#3271) → <code>RunOutput.append</code>(#3279, rows=[]). 둘째 날 <code>compute</code>(#3325, 2.0 ms).",
              fn="SampleFeatures.compute() — 저자 코드", code=at(DECL + "features.py", "closes = window.matrix()", 12, before=1), author=True,
              mem={"closes.shape": "(2, 10) — 날 2 × 종목 10", "returned": "[]"}),
            F("06_run_features", 3628, "다섯째 날 — 종목 9개의 모멘텀을 한 식으로",
              "2022-01-10 16:00. 여섯 행이 찼습니다. <code>closes[-1] / closes[0] - 1</code>이 열마다(종목마다) 한 번에 계산되고, 여섯 값이 다 있는 열만 행으로 나갑니다: 9행(K000010은 열이 비어 빠짐). 이번 계산은 3.4 ms. "
              "행의 시각(<code>available_at</code>)은 저자가 아니라 프레임워크가 찍습니다(16:00): \"이 값은 이 시각에야 알 수 있다\"는 뜻이라서요.",
              "<code>RunLoop.handle</code>(#3585, 28.3 ms) → <code>_window_factory.at</code>(#3592, 01-10 16:00) → <code>compute</code>(#3628, 3.4 ms) → <code>RunOutput.append</code>(#3927, 13.8 ms, rows=[{available_at: 2022-01-10 16:00+09:00, instrument: 'K000001', momentum_5d: …}, …]).",
              fn="SampleFeatures.compute() — 행 9", code=at(DECL + "features.py", "momentum = closes[-1]", 8, before=2), author=True,
              mem={"rows this session": "9", "rows so far": "9 → 16일째에 108"}),
            F("06_run_features", 7760, "출력이 dataset이 된다 — 같은 문을 지나서",
              "16일이 끝나면 모은 행을 parquet으로 굳히고(94 ms) 그 파일을 <b>①에서 벤더 표가 지난 바로 그 문</b>에 넣습니다(105 ms): 컬럼 · 키 · 기간(01-10 ~ 01-25) · 값 · 지문. 통과하면 장부에 <code>sample-features</code>가 \"어느 run의 어느 코드 버전이 만들었다\"와 함께 적힙니다. 프레임워크가 만든 표라고 문을 건너뛰지 않습니다. 봉투는 rows 108 · sessions 16.",
              "<code>RunLoop.finish</code>(#7726) → <code>RunOutput.register</code>(#7760, 217.1 ms) → <code>_seal</code>(#7789, 94.1 ms) → <code>verify_source</code>(#7791, 105.1 ms) → <code>Transaction.commit</code>(#7922, 14.3 ms) → <code>freeze_datamodel_record</code>(#7989, 13.8 ms) → <code>RunRecordWriter._seal</code>(#8131) → <code>read_datamodel_record</code>(#8145) → <code>success</code>(#8152).",
              fn="RunOutput.register()", code=("def", 14),
              disk={".vqapr/materialized/sample-features/all.parquet": "108행 (available_at · instrument · momentum_5d)", ".vqapr/runs/sample-features-run/": "run.json · datamodels/sample-features@20c2acad/datamodel.json", ".vqapr/workspace.yaml": "datasets + sample-features (source_digest 54f8fd04…)"}),
        ],
        "remember": [
            "run은 verify_run 한 번으로 판정받고 얼려지며, 문이 import한 모델을 그대로 받는다.",
            "읽기는 run 기간 + lookback만큼만. 출력 parquet도 등록될 때 같은 문을 지난다.",
        ],
    },
    # ---------------------------------------------------------------- ④ factor strategy
    {
        "id": "factor", "key": "④", "title": "factor 전략 — 롱 3 · 숏 3",
        "sub": "register factor.yaml · 100 ms · 1,058 호출 — run sample-factor-run · 1,924 ms · 24,374 호출 · 10일 · 이벤트 20 (0.14.2는 27,853 호출)",
        "story": (
            "<b>무슨 일인가:</b> <code>factor.py</code>의 <code>SampleFactor</code>는 ③이 만든 모멘텀 표를 <b>벤더 표와 똑같이</b> 한 줄로 선언해 읽고(최신 행 하나), 상위 3종목은 사고 하위 3종목은 팝니다(각 1/6, 달러 중립). "
            "공매도가 있으니 거래소가 SIGNED 상장을 허용해야 합니다 — <code>exchange_signed.py</code>가 그것입니다. run은 2022-01-12 ~ 01-25, 매일 아침 8시에 결정하고 오후 3시 반에 체결. 끝나면 비중이 <code>sample-factor-weights</code>로 저장됩니다(⑥이 읽습니다). "
            "<b>[0.14.3]</b>이 가장 잘 보이는 run입니다: 시각 열을 735일이 아니라 12일만 읽고, 콜백이 읽은 것을 한 번만 만들며, \"무엇을 읽나\"를 매 결정마다 묻지 않습니다."
        ),
        "frames": [
            F("08_run_factor", 722, "verify_run — 판정이 읽고, 얼리기는 받는다",
              "판정 일곱 중 무거운 건 집행 순서(122 ms)입니다: 결정 시각 목록을 만들려고 집행표의 시각 열을 읽습니다. <b>[0.14.3]</b> 읽는 범위가 run 기간 ± 1일(01-11 ~ 01-26)이라 12일만 옵니다 — 0.14.2는 3년치 735일을 읽고 Python이 잘랐습니다. "
              "이어서 얼리기(20.9 ms)가 같은 agenda를 물으면 그릇이 0.05 ms에 돌려줍니다. 얼리기는 전략을 새 인스턴스에 한 번 더 만들어 초기 memory가 JSON인지 증명하고(의도된 두 번째 import), agenda와 체결 목표를 얼립니다.",
              "<code>verify_run</code>(#722, 156.3 ms) → <code>judgments</code>(#724, 134.5 ms) → <code>_judge_execution_ordering</code>(#748, 121.9 ms) → <code>RunFacts.agenda</code>(#749) → <code>derived_agenda</code>(#752, 111.7 ms) → <code>evaluation_times</code>(#754, 85.4 ms) → <code>distinct_values</code>(#762, 84.5 ms: 12 instants) · <code>_judge_member_datasets</code>(#1639, 6.1 ms) · <code>_judge_weights</code>(#1766) · <code>_judge_outputs</code>(#1856) → <code>preflight_run</code>(#1857, 20.9 ms) → <code>RunFacts.agenda</code>(#1861, 0.04 ms) → <code>_freeze_strategy</code>(#1905, 14.8 ms) → <code>_validate_initial_model_state</code>(#1912) → <code>_freeze_agenda</code>(#2002) → <code>_validate_execution_targets</code>(#2090).",
              fn="verify_run()", code=("def", 16),
              mem={"거래일 읽기": "_local_date ×12 (0.14.2: ×734)", "facts settled": "agenda · execution_table · horizon · component:sample-factor · exchange"}),
            F("08_run_factor", 2245, "얼리기 — 읽을 표와 집행표를 지문으로 묶는다",
              "이 전략이 읽는 <code>sample-features</code>는 다른 run이 만든 표지만 여기선 벤더 표와 똑같이 취급됩니다: 지문 한 번(1.3 ms). 집행표는 등록 때 적어 둔 \"체결 가능한 가격 컬럼\" 목록에 <code>close</code>가 있는지만 봅니다. 얼린 run은 두 지문을 들고 불변식을 검사합니다.",
              "<code>_freeze_sources</code>(#2244, 1.9 ms) → <code>_validate_requirement</code>(#2245) → <code>Workspace.require_verified</code>(#2246, 1.3 ms) → <code>FrozenRun.__post_init__</code>(#2278, 1.1 ms).",
              fn="_validate_requirement()", code=at("src/vqapr/flow/declaration/preflight.py", "def _validate_requirement", 14)),
            F("08_run_factor", 2306, "전략 · 거래소 · 기간을 다시 만들지 않는다 — RunResources",
              "문이 든 전략 객체 · 거래소 · 규칙(없음) · 체결 기간을 봉지 하나에 담습니다. 세 번의 조회가 각각 0.05 ms — 만드는 게 아니라 꺼내는 겁니다. 예전엔 run이 여기서 전략을 다시 import하고 첫 의도서에서 집행표를 다시 스캔했습니다.",
              "<code>RunResources.of</code>(#2306, 0.7 ms) → <code>RunFacts.component</code>(#2313, 0.045 ms) · <code>exchange</code>(#2315) · <code>horizon</code>(#2318) → <code>RunVerdict.require_ready</code>(#2320) → <code>run</code>(#2322, 1,699.1 ms).",
              fn="RunResources.of()", code=at("src/vqapr/flow/declaration/verify.py", "def of(cls, facts: RunFacts, frozen: FrozenRun)", 12),
              mem={"resources": "strategy=SampleFactor · exchange=AcademicExchange(SIGNED) · rules=() · horizon=01-12 15:30 ~ 01-25 15:30"}),
            F("08_run_factor", 2331, "run 시작 — 종목 명단은 얼리지 않고 그때그때 읽는다",
              "run이 시작하며 종목 명단을 <b>새로</b> 읽습니다(387 ms). 얼리지 않는 건 일부러입니다(이슈 009): 명단은 날마다 자라고, 새 이름을 안 쓰는 run까지 아침마다 막을 이유가 없어서요. 대신 그날 명단의 지문을 기록에 적습니다. 387 ms는 10행짜리 표의 값이 아니라 프로세스가 pyarrow를 처음 올리는 비용입니다(⑦의 worker에선 21 ms). "
              "그 다음 계좌(현금 1억, SIGNED) · 규칙 자리 · 루프를 조립하고, <b>[0.14.3]</b> 콜백 담당이 전략에게 \"무엇을 읽나\"를 <b>여기서 한 번</b> 묻습니다.",
              "<code>run</code>(#2322) → <code>registered_roster</code>(#2331, 387.5 ms) → <code>verify_roster</code>(#2337, 384.8 ms) → <code>build_roster</code>(#2341) → <code>_run_strategy</code>(#2451, 1,300.0 ms) → <code>CallbackHandler.__init__</code>(#2844, 0.6 ms) → <code>SampleFactor.inputs</code>(#2845) → <code>ComplianceHandler.__init__</code>(#2924) → <code>RunLoop.__init__</code>(#2926) → <code>Account.bind</code>(#2928) → <code>RunLoop.run</code>(#2929, 1,124.8 ms).",
              fn="registered_roster()", code=at("src/vqapr/flow/roster.py", "def registered_roster", 12),
              tip="inputs()는 run 전체에서 7번 불린다: 검증의 import 둘 · 판정 · 얼리기 · run 시작의 요구 목록 · 콜백 담당 조립 — 그리고 결정마다는 0번. 0.14.2엔 결정마다 한 번씩 10번이 더 있었다(기록 246)."),
            F("08_run_factor", 3245, "아침 8시 — 모멘텀 표를 어디까지 읽을지",
              "2022-01-12 08:00, 첫 결정. 전략이 모멘텀 표의 최신 행 하나를 달라고 합니다. 창고는 run 시작 앞의 격자 한 칸(01-11 16:00)부터 run 끝(01-25 23:59:59)까지만 스캔하고(5.1 ms) (11일 × 10종목) 행렬 하나를 만듭니다(1.4 ms).",
              "<code>decide</code>(#3203) → <code>panel_window</code> → <code>_scan_bounds</code>(#3245, 18.1 ms) → <code>observation_table</code>(#3270, 5.1 ms) → <code>Panel.from_table</code>(#3307, 1.4 ms) → <code>PanelWindow.matrix</code>.",
              fn="_scan_bounds()", code=("def", 12),
              mem={"bounds": "2022-01-11 16:00 ~ 2022-01-25 23:59:59 +09:00", "panel.blocks['momentum_5d'].shape": "(11, 10)"}),
            F("08_run_factor", 3203, "한 행을 읽고 여섯 이름을 고른다 — 그리고 읽은 것을 한 번만 적는다",
              "저자 코드. 창은 01-11 16:00의 행(전날 저녁에 알 수 있던 값) 하나 × 종목 10. 정렬해서 하위 3(K000004 · 5 · 6)에 −1/6, 상위 3(K000003 · 8 · 9)에 +1/6. <code>Rebalance.signed</code>는 부호가 방향입니다. "
              "<b>[0.14.3]</b> 결정이 돌아오면 프레임워크는 \"이 콜백이 실제로 어떤 표의 어떤 지문을 읽었나\"(source refs)를 <b>한 번</b> 만들어(5.0 ms) 의도서 도장과 증거 양쪽에 씁니다. 0.14.2는 같은 걸 두 번 만들었습니다(콜백당 2회 → 1회, 이 run 20 → 10). 그 뒤 도장을 찍고 받아들여 계좌 · memory · 대기 의도서를 한 번에 publish합니다.",
              "<code>RunLoop.handle</code>(#3095, 62.9 ms, agenda 01-12 08:00) → <code>StrategyPart.dispatch</code>(#3096) → <code>CallbackHandler.dispatch</code>(#3098) → <code>SampleFactor.decide</code>(#3203, 35.1 ms) → <b><code>_callback_actual_source_refs</code>(#3432, 5.0 ms) → <code>_actual_source_refs</code>(#3437)</b> → <code>_stamp_intent</code>(#3538, 1.2 ms) → <code>_accept_intent</code>(#3605, 0.9 ms) → <code>_candidate_callback_state</code>(#3677, 3.9 ms) → <code>_callback_evidence</code>(#3760, 0.4 ms) → <code>RunStateRepository.publish</code>(#3795, 2.5 ms). 둘째 날: <code>decide</code>(#5251, 7.2 ms) → refs(#5417) → 도장(#5523).",
              fn="SampleFactor.decide() — 저자 코드", code=at(DECL + "factor.py", "ranked = sorted(", 10, before=3), author=True,
              mem={"weights": "K000003 +0.1667 · K000008 +0.1667 · K000009 +0.1667 · K000004 −0.1667 · K000005 −0.1667 · K000006 −0.1667", "pending": "intent 1 (계좌 v0 기준)", "source refs": "콜백당 1회 (0.14.2: 2회)"}),
            F("08_run_factor", 3832, "오후 3시 반 — 숏 셋이 실제로 팔린다",
              "시장 시계 01-12 15:30(트레이스엔 UTC 06:30). 기다리던 의도서가 때가 되어 주문을 계획합니다(비중 → 주 수, 16.8 ms). SIGNED 상장이라 음수 주 수가 통과합니다. 체결: K000003 +23 · K000008 +8 · K000009 +94, K000004 <b>−55</b> · K000005 <b>−19</b> · K000006 <b>−12</b>(close 가격, 학술 프로파일이라 수수료 0). 계좌 v1: 현금 99,463,501.24, NAV 1억.",
              "<code>RunLoop.handle</code>(#3824, 76.2 ms, MarketEvent) → <code>MarketClock.at</code>(#3825) → <code>fill</code>(#3832, 54.4 ms) → <code>plan_orders</code>(#3920, 16.8 ms) → <code>AcademicExchange.execute</code>(#4300, 8.5 ms) → <code>Account.append</code>(#4545, 1.4 ms) → <code>commit_append</code>(#4778).",
              fn="ExecutionHandler.fill()", code=("def", 12),
              mem={"account v1": "롱 3 · 숏 3 · cash 99,463,501.24 · NAV 100,000,000.00"}),
            F("08_run_factor", 4815, "같은 시각에 이어서 — 평가하고, 규칙이 보고, 다음으로",
              "체결 직후 보유를 종가로 평가합니다(16.7 ms). compliance 규칙이 없으니 \"규칙이 본다\"는 자리는 0.004 ms에 지나갑니다 — 자리는 있고 할 일이 없을 뿐입니다. 시장 시각 한 점은 늘 이 순서입니다: 발생 → 체결 → 평가 → 판정. 이 run엔 열 점.",
              "<code>ValuationHandler.mark</code>(#4815, 16.7 ms) → <code>Account.mark</code>(#4925, 1.4 ms) → <code>ComplianceHandler.observe</code>(#5115, 0.004 ms) → 다음 아침 <code>RunLoop.handle</code>(#5141, 31.8 ms).",
              fn="ValuationHandler.mark()", code=("def", 10)),
            F("08_run_factor", 23873, "run이 끝나면 비중이 dataset이 된다 — 역시 같은 문",
              "10일(계좌 v10, 주문 73 · 체결 54)이 끝나면 기록을 굳히고(표 3: account · fill · weight) 비중 60행을 <code>sample-factor-weights</code>로 냅니다. 각 행의 시각은 그 결정의 시각(08:00). 이 파일도 문(73.6 ms)을 지나 등록됩니다. "
              "<b>[0.14.3]</b> 기록을 쓰는 동안 \"살아 있다\"는 표시(lock 파일 touch)는 chunk마다가 아니라 초당 한 번입니다 — 트레이스엔 <code>heartbeat</code> 호출이 그대로 보이지만 그 안의 파일 touch가 줄었습니다(기록 248).",
              "<code>RunLoop.finish</code>(#23515) → <code>RunRecordWriter._seal</code>(#23681, 26.3 ms) → <code>_publish_allocation</code>(#23735, 107.4 ms) → <code>RunOutput.register</code>(#23873, 95.6 ms) → <code>verify_source</code>(#23899, 73.6 ms) → <code>Transaction.commit</code>(#24030, 15.4 ms).",
              fn="RunOutput.register()", code=("def", 8),
              disk={".vqapr/runs/sample-factor-run/strategies/sample-factor@9bba20c4/": "strategy.json · tables/vqapr.{account,fill,weight}/all.parquet", ".vqapr/materialized/sample-factor-weights/all.parquet": "60행 (available_at 01-12 08:00 ~ 01-25 08:00 · instrument · weight ±0.1667)"}),
        ],
        "remember": [
            "한 사실은 한 번 읽고 나눠 쓴다 — 선언 쪽(RunFacts)도, 콜백 쪽(source refs · inputs)도.",
            "Rebalance.signed는 부호가 방향. 숏은 SIGNED 상장과 SIGNED 계좌가 있어야 체결된다.",
        ],
    },
    # ---------------------------------------------------------------- ⑤ stop-loss with memory
    {
        "id": "stop", "key": "⑤", "title": "stop-loss — memory가 진입가를 든다",
        "sub": "register stoploss.yaml · 101 ms · 1,112 호출 — run sample-stoploss-run · 7,305 ms · 61,659 호출 · 37일 · 이벤트 74 (0.14.2는 68,066 호출)",
        "story": (
            "<b>무슨 일인가:</b> <code>stoploss.py</code>의 <code>SampleStopLoss</code>는 첫날 종가가 있는 종목을 전부 같은 비중으로 사고, 각 종목의 <b>진입가를 <code>self.memory</code>에 적어 둡니다</b>. 그 뒤 날마다 최신 종가를 진입가와 견줘 3% 넘게 빠진 종목은 팔고 날짜를 적습니다. "
            "memory는 엄격한 JSON이고 매 결정 전에 복원되고 뒤에 저장됩니다 — 같은 run을 다시 돌리면 같은 손절이 같은 날 납니다. 이 합성 데이터는 잘 빠져서 손절이 이어지고, 02-22엔 K000008 하나, 02-23에 전량 매도, 그 뒤는 현금만."
        ),
        "frames": [
            F("10_run_stoploss", 6407, "결정 전 — 비어 있는 memory가 전략에 복원된다",
              "2022-01-04 08:00, 첫 콜백. 프레임워크가 현재 상태의 memory(첫날이라 <code>{}</code>)와 payload(빈 바이트)를 전략 객체에 넣습니다. 전략은 하나의 객체로 run 전체를 살지만 <b>믿을 건 이 복원된 memory뿐</b>입니다 — 다른 self 속성은 기록이 재현하지 못합니다.",
              "<code>verify_run</code>(#881, 263.6 ms) … <code>RunLoop.run</code>(#5863, 6,357.5 ms) → <code>checkpoint</code>(#6375) → <code>_visible_callback_state</code>(#6388) → <code>_restore_callback_state</code>(#6407: <code>strategy.memory = {}</code> · <code>load_payload(b'')</code>) → 창 → 계좌 view → decide.",
              fn="_restore_callback_state()", code=at("src/vqapr/flow/run/callback.py", "def _restore_callback_state", 4),
              mem={"strategy.memory": "{}"}),
            F("10_run_stoploss", 6524, "첫 창 — 38일짜리 행렬 하나가 run 전체를 든다",
              "run 시작(01-04) 앞 한 칸(01-03 15:30)부터 끝(02-28)까지, 38일 × 10종목 행렬 하나를 만듭니다. 37번의 결정이 전부 이 행렬의 일부를 봅니다. 둘째 날의 범위 계산은 0.16 ms — 같은 창, 같은 행렬.",
              "<code>SampleStopLoss.decide</code>(#6488, 67.0 ms) → <code>_DeclaredReads.read</code>(#6489, 61.8 ms) → <code>ModelWindow.panel</code>(#6508) → <code>panel_window</code>(#6509, 60.9 ms) → <code>_scan_bounds</code>(#6524, 52.3 ms) → … 둘째 날 <code>panel_window</code>(#9888, 1.1 ms) → <code>_scan_bounds</code>(#9901, 0.16 ms).",
              fn="_scan_bounds()", code=("def", 8),
              mem={"bounds": "2022-01-03 15:30 ~ 2022-02-28 23:59:59 +09:00", "panel.blocks['close'].shape": "(38, 10)"}),
            F("10_run_stoploss", 6488, "첫 결정 — 9종목에 들어가고 진입가 9개를 적는다",
              "저자 코드. 최신 종가(01-03)가 있는 종목은 9개(K000010은 아직 없음). \"처음이다\" 플래그가 없으니 <code>entry</code>에 종가 9개를 적고 플래그를 세웁니다. 아무도 3%를 안 깼으니 9종목 같은 비중(투자 90%). 플래그를 따로 두는 이유: 나중에 <code>entry</code>가 비었을 때 \"처음\"으로 오해해 다시 사지 않으려고요.",
              "<code>SampleStopLoss.decide</code>(#6488, 67.0 ms) → <code>read</code>(#6489) → <code>matrix</code> → <code>Rebalance.of</code>.",
              fn="SampleStopLoss.decide() — 저자 코드", code=at(DECL + "stoploss.py", "entry: dict[str, float]", 12), author=True,
              mem={"self.memory": "{entry: {K000001: …, …, K000009: …} 9개, stopped: {}, entered: true}"}),
            F("10_run_stoploss", 7723, "결정 후 — 읽은 것 한 번, memory 정리 한 번, 저장 한 번",
              "결정이 돌아오면 순서대로: <b>[0.14.3]</b> 읽은 것(source refs)을 한 번 만들고(3.8 ms) → 의도서에 도장 → 받아들임 → memory를 엄격한 JSON으로 <b>한 번</b> 정리(Decimal · datetime · set이 있으면 여기서 거절; 기록 239) → 계좌 · memory · 대기 의도서를 한 번에 저장(v1). 그리고 15:30에 9종목이 체결됩니다.",
              "<b><code>_callback_actual_source_refs</code>(#7442, 3.8 ms)</b> → <code>_stamp_intent</code>(#7540, 1.3 ms) → <code>_accept_intent</code>(#7627) → <code>_candidate_callback_state</code>(#7723, 6.7 ms) → <code>RunStateRepository.prepare_callback</code>(#7899, 0.9 ms) → <code>publish</code>(#7919, 1.6 ms) → <code>_deliver</code>(#7920) · <code>ExecutionHandler.fill</code>(#7956, 62.1 ms) → <code>execute</code>(#8637, 11.5 ms) → <code>mark</code>(#9333, 17.4 ms).",
              fn="_candidate_callback_state()", code=at("src/vqapr/flow/run/callback.py", "def _candidate_callback_state", 10),
              mem={"root": "v1 (account v0 · memory entry 9 · pending 1)", "source refs": "이 run 37회 (0.14.2: 71회)"}),
            F("10_run_stoploss", 9867, "둘째 날 — 복원된 memory로 첫 손절",
              "01-05 08:00. 복원된 memory에 진입가 9개가 있습니다. 최신 종가(01-04)를 견주니 K000005가 −3%를 넘겼습니다 → <code>stopped['K000005'] = '2022-01-05'</code>, <code>entry</code>에서 지웁니다. 남은 8종목 같은 비중; 15:30에 K000005를 팝니다. "
              "이어지는 날들(보유 종목 수): 9 → 8(01-05) → 7(01-06) → 5(01-11) → 4(01-19) → 3(01-24) → 2(01-25) → 1(01-26 ~ 02-22, K000008 하나).",
              "<code>_restore_callback_state</code>(#9784) → <code>SampleStopLoss.decide</code>(#9867, 6.6 ms) → <code>_stamp_intent</code>(#10123) → <code>_accept_intent</code>(#10204) → <code>_candidate_callback_state</code>(#10292, 6.0 ms) → <code>prepare_callback</code>(#10468) · <code>fill</code>(#10525, 55.1 ms).",
              fn="SampleStopLoss.decide() — 손절", code=at(DECL + "stoploss.py", "for name, price in list(entry.items())", 6), author=True,
              mem={"self.memory": "{entry: 8, stopped: {K000005: '2022-01-05'}, entered: true}"}),
            F("10_run_stoploss", 57395, "마지막 종목이 깨지면 — 전량 매도는 Hold가 아니라 빈 Rebalance",
              "02-23 08:00. K000008이 02-22 종가로 −3%를 넘겼습니다. <code>entry</code>가 비었고 계좌엔 K000008 52주가 있습니다. <code>Hold</code>는 \"아무것도 하지 마라\"라 포지션이 그대로 남습니다. 그래서 \"목표 비중 없음, 현금 100%\"를 돌려줍니다. 15:30에 <b>K000008 −52</b>가 1,441,901.11에 체결되고 계좌(v34)는 현금 84,184,068.92뿐입니다.",
              "<code>decide</code>(#57395, 3.4 ms) → <code>MarketClock.at</code> → <code>fill</code>(#57834, 18.3 ms) → <code>AcademicExchange.execute</code>(#57956, 1.6 ms) → <code>Account.append</code>.",
              fn="SampleStopLoss.decide() — 마지막", code=at(DECL + "stoploss.py", "if any(quantity != 0", 5, before=3), author=True,
              mem={"self.memory": "{entry: {}, stopped: 9개, entered: true}", "account v34": "positions {} · cash 84,184,068.92"}),
            F("10_run_stoploss", 58517, "그 뒤 — Hold, 기다리는 의도서 없음, 오후엔 평가만",
              "02-24 08:00부터 <code>entry</code>도 포지션도 없습니다 → <code>Hold</code>(\"모든 종목이 손절선을 깼다, 현금으로 둔다\"). 기다리는 의도서가 없으니 15:30의 체결 단계는 0.003 ms에 지나가고 평가만 합니다(9.5 ms). run은 74 이벤트, 계좌 v34로 끝나고 비중 dataset이 문을 지나 등록됩니다.",
              "<code>decide</code>(#58517, 2.7 ms) → Hold · <code>AccrualHandler.accrue</code>(#58895) → <code>fill</code>(#58898, 0.003 ms, due=None) → <code>ValuationHandler.mark</code>(#58899, 9.5 ms) … <code>_publish_allocation</code> → <code>RunOutput.register</code> → <code>verify_source</code>.",
              fn="SampleStopLoss.decide() — Hold", code=at(DECL + "stoploss.py", "return va.Hold(", 1, before=0), author=True,
              disk={".vqapr/runs/sample-stoploss-run/strategies/sample-stoploss@bb45a6ab/": "strategy.json · tables 3 (weight 표 33일분, 02-23부터 없음)", ".vqapr/materialized/sample-stoploss-weights/all.parquet": "등록됨"},
              tip="strategy.json엔 memory dict가 없다. 트레이스에 보이는 건 매 콜백의 복원 → 결정 → 한 번의 정리 → 저장이고, 기록엔 그 상태의 ref가 남는다."),
        ],
        "remember": [
            "memory는 결정 전에 복원되고 뒤에 한 번 정리되어 저장된다. 첫 콜백엔 {}. JSON이 아닌 것은 여기서 거절된다.",
            "\"처음인가\"는 별도 플래그로 기억한다. 포지션을 다 비우려면 Hold가 아니라 빈 Rebalance.",
        ],
    },
    # ---------------------------------------------------------------- ⑥ enhanced index
    {
        "id": "ei", "key": "⑥", "title": "enhanced index — 저장된 비중을 읽는다",
        "sub": "register enhanced.yaml · 115 ms · 1,315 호출 — run sample-enhanced-run · 2,095 ms · 27,311 호출 · 9일 — list datasets 96 ms · show run 20 ms",
        "story": (
            "<b>무슨 일인가:</b> <code>enhanced.py</code>의 <code>SampleEnhancedIndex</code>는 ④가 저장한 비중(<code>sample-factor-weights</code>)을 <b>alpha로 읽고</b>, 종가가 있는 종목의 같은 비중(1/9)에 그 alpha의 절반을 더한 뒤 0 아래를 잘라 냅니다 — 롱온리 enhanced index. "
            "④가 08:00에 정한 비중을 알 수 있게 된 뒤인 09:00에 결정합니다. 두 표를 각각 자기 기간으로 읽습니다(가격 10 × 10, alpha 10 × 10). 마지막으로 <code>list datasets</code>와 <code>show run</code>으로 이 프로젝트에 무엇이 남았는지 봅니다: dataset 6개, 그중 4개가 run이 만든 것."
        ),
        "frames": [
            F("12_run_enhanced", 2574, "얼리기 — 저장된 alpha가 dataset으로 묶인다",
              "읽을 것 둘: <code>sample-factor-weights</code>(④가 만든 표)와 <code>sample-prices</code>(벤더 표). 둘 다 같은 한 줄 — 지문 확인(1.7 · 1.4 ms). run이 만든 표와 벤더 표가 <b>여기서 같은 취급</b>을 받는다는 것이 이 시나리오의 요점입니다.",
              "<code>verify_run</code>(#1040, 161.1 ms) → … <code>_freeze_sources</code>(#2573, 3.9 ms) → <code>_validate_requirement</code>(#2574) → <code>Workspace.require_verified</code>(#2575, 1.7 ms) · <code>_validate_requirement</code>(#2593, 1.4 ms).",
              fn="_validate_requirement()", code=("def", 14),
              mem={"frozen.source_digests": "{materialized-sample-factor-weights: …, sample-prices-source: 18bb7017…}"}),
            F("12_run_enhanced", 3581, "9시 — 두 창을 읽고 기본 비중에 alpha를 얹는다",
              "2022-01-13 09:00. 가격 창: 01-12 15:30부터 (10 × 10) 행렬 → 종목 9개 → 기본 1/9 = 0.111. alpha 창: 01-12 08:00부터 (10 × 10) 행렬 → 01-13 08:00의 factor 비중(±1/6)의 절반 → K000003 · 8 · 9엔 +0.083, K000004 · 5 · 6엔 −0.083. 합이 1이 되게 정규화합니다. 첫 결정 78 ms(두 표의 첫 스캔), 다음 날 10 ms.",
              "<code>_window_factory.at</code>(#3511, 01-13 09:00) → <code>SampleEnhancedIndex.decide</code>(#3581, 78.0 ms) → prices: <code>observation_table</code>(#4365, 4.3 ms) → <code>from_table</code>(#4402, 1.1 ms) → alpha: <code>observation_table</code>(#4477, 3.6 ms) → <code>from_table</code>(#4514, 0.7 ms) → <code>Rebalance.of</code>. 둘째 날 <code>decide</code>(#7079, 10.1 ms).",
              fn="SampleEnhancedIndex.decide() — 저자 코드", code=at(DECL + "enhanced.py", "tilted = {", 6, before=0), author=True,
              mem={"panels": "prices (10 × 10) 01-12 15:30 ~ · alpha (10 × 10) 01-12 08:00 ~ (probe_panel.py)"}),
            F("12_run_enhanced", 5193, "3시 반 — 롱온리 체결, 그리고 아홉 날",
              "첫 체결 62 ms. 9일 동안 이벤트 18, 계좌 v9. 끝나면 비중이 <code>sample-enhanced-weights</code>로 나가고 문(<code>RunOutput.register</code>, 103.6 ms)을 지나 등록됩니다.",
              "<code>MarketClock.at</code> → <code>fill</code>(#5193, 62.1 ms) … <code>_publish_allocation</code>(#26568, 115.2 ms) → <code>RunOutput.register</code>(#26748, 103.6 ms) → <code>verify_source</code>.",
              fn="ExecutionHandler.fill()", code=("def", 8)),
            F("13_list_datasets", 12, "list datasets — 여섯, 그중 넷은 run이 만들었다",
              "장부를 열어(63 ms) dataset 목록을 냅니다: <code>sample-prices</code> · <code>sample-execution</code>(벤더), <code>sample-features</code>(③), <code>sample-factor-weights</code>(④), <code>sample-stoploss-weights</code>(⑤), <code>sample-enhanced-weights</code>(⑥). 어느 run의 어느 코드 버전(<code>sample-factor@9bba20c4</code>)이 만들었는지가 이름 옆에 있습니다.",
              "<code>list_.run</code>(#11, 64.1 ms) → <code>Workspace.open</code>(#12, 63.2 ms) → <code>Workspace._read</code>(#15) → <code>datasets</code>(#1061) → <code>_summarize</code> ×6(#1069 …) → <code>success</code>(#1075, count 6).",
              fn="Workspace.open()", code=("def", 8)),
            F("14_show_run_enhanced", 18, "show run — 기록만 읽는다, 32호출 20 ms",
              "<code>show run sample-enhanced-run</code>은 기록(<code>run.json</code>)만 읽습니다: 읽은 표 둘과 각각의 지문, 거래소 코드의 지문, 체결 조건(close · 15:30 · Asia/Seoul), 초기 계좌, 기간. 이 run이 어떤 바이트를 읽었는지가 기록에 있으니 나중에 파일이 바뀌어도 \"그때 무엇이었나\"는 남습니다.",
              "<code>main</code>(#0, 19.4 ms) → <code>show.run</code>(#11, 2.2 ms) → <code>run_ids</code>(#12) → <code>read_run_record</code>(#18, 0.5 ms) → <code>record_view</code>(#21) → <code>strategy_refs</code>(#22) → <code>datamodel_refs</code>(#25) → <code>success</code>(#26).",
              fn="read_run_record()", code=("def", 8),
              disk={".vqapr/": "workspace.yaml · instruments.json · materialized/ 4 · runs/ 4"}),
        ],
        "remember": [
            "run이 저장한 비중은 dataset이다: 다음 run이 한 줄로 읽고, 얼리기는 지문으로 묶고, 읽기는 자기 기간만큼.",
            "list · show는 장부와 기록만 읽는다. 기록은 읽은 파일의 지문을 든다.",
        ],
    },
    # ---------------------------------------------------------------- ⑦ --jobs batch
    {
        "id": "batch", "key": "⑦", "title": "--jobs 배치 — worker도 판정, cube 한 번",
        "sub": "run sample-factor-run sample-stoploss-run --jobs 2 --force · 1,887 ms · 3,492 호출 (driver) — worker 하나를 따로 추적: 1,531 ms · 23,353 호출",
        "story": (
            "<b>무슨 일인가:</b> ④와 ⑤를 <b>한 배치</b>로 동시에 돌립니다(<code>--jobs 2</code>; 기록이 이미 있으니 <code>--force</code>). 지휘자(driver)는 일꾼(worker)을 띄우기 <b>전에</b> 각 run이 무엇을 읽는지 한 번 묻고, 서로가 만드는 걸 읽지는 않는지 보고, 읽을 표를 미리 <b>한 번 구워 둡니다</b>(cube: 전 종목 × 전 기간 행렬 파일). "
            "일꾼은 자기 기간만큼을 그 파일의 일부로 메모리에 <b>매핑</b>해 읽습니다 — 스캔이 없습니다. 배치가 끝나면 구운 파일은 지워집니다. 일꾼도 단일 run과 똑같이 <code>verify_run</code>을 지나 판정을 받습니다(0.13.0까지는 받지 않았습니다). "
            "지휘자의 트레이스는 프로세스 경계에서 끝나므로 일꾼 쪽은 같은 일꾼 함수를 같은 프로파일러 아래서 따로 돌려 얻었습니다."
        ),
        "frames": [
            F("15_run_batch", 12, "지휘자 — 무엇을 읽는지 한 번 묻고, 서로 독립인지 본다",
              "run이 둘이고 jobs가 2니 배치 경로입니다. 장부를 열고(59 ms) run마다 부품을 올려 \"무엇을 읽나\"를 <b>한 번씩</b> 묻습니다 — factor는 <code>sample-features</code>, stop-loss는 <code>sample-prices</code>. 그 답으로 둘이 서로가 만드는 걸 읽지 않는지 봅니다(0.2 ms). 병렬이면 순서를 약속할 수 없으니 읽는 쪽이 있으면 배치 전체를 거절합니다.",
              "<code>run</code>(#11) → <code>_run_each_in_workers</code>(#12, 1,869.6 ms) → <code>Workspace.open</code>(#15, 59.0 ms) → <code>batch_reads</code>(#1064, 9.0 ms) → <code>_reads</code>(#1067, 4.8 ms · #1157, 4.0 ms) → <code>require_independent_batch</code>(#1235, 0.2 ms) → <code>batch_cubes</code>(#1244).",
              fn="_run_each_in_workers()", code=at("src/vqapr/cli/run.py", "with batch_cubes(workspace, targets, reads) as cubes:", 12, before=6),
              mem={"targets": "[sample-factor-run, sample-stoploss-run]", "reads": "factor → sample-features[momentum_5d] · stop-loss → sample-prices[close]"}),
            F("15_run_batch", 1244, "굽기 전에 — 묵은 것을 치우고, 잠그고",
              "<code>.vqapr/cubes/</code> 아래에 이 배치의 폴더를 만들고 잠금 파일에 pid를 적습니다. 먼저 이전 배치가 남긴 묵은 폴더(잠금이 10분 넘게 갱신 안 된 것)를 치우고, 30초마다 잠금을 만지는 스레드가 \"살아 있다\"고 표시합니다. 그리고 굽기.",
              "<code>batch_cubes</code>(#1244, 579.9 ms) → <code>_bake_for_batch</code>(#1246, 573.6 ms) → <code>source_digest</code>(#1256) → <code>bake</code>(#1259, 465.6 ms: sample-features) → <code>source_digest</code>(#1358) → <code>bake</code>(#1361, 102.6 ms: sample-prices).",
              fn="batch_cubes()", code=("def", 14),
              disk={".vqapr/cubes/<pid>-<hex>/": "cube.lock (pid)"}),
            F("15_run_batch", 1361, "굽기 — 가격표의 close를 전 종목 × 전 기간으로 한 번",
              "표마다 한 번: 종목 전부(10)를 세고, 등록된 기간 전체를 스캔하고, (735 × 10) 숫자 행렬로 접어 <code>close.npy</code>(58,928 B)로 저장합니다. 옆에 어느 칸에 값이 있었나(<code>present.npy</code>), 날짜 목록, 종목 목록, 원천의 지문(<code>cube.json</code>). 앞의 <code>sample-features</code>는 12 × 9. 구울 수 없는 표(문자열 필드 등)는 조용히 빠지고 그 일꾼은 스캔합니다.",
              "<code>bake</code>(#1259, 465.6 ms: sample-features) → <code>distinct_values</code>(#1260, 31.4 ms) → <code>placement</code>(#1313, 8.0 ms) · <code>bake</code>(#1361, 102.6 ms: sample-prices) → <code>distinct_values</code>(#1362, 16.7 ms) → <code>placement</code>(#1417, 2.9 ms) → <code>dense_block</code> → <code>open_cube</code>.",
              fn="bake()", code=at("src/vqapr/data/cube.py", "instants, keep, rows, cols = placement(table, names, keyed)", 12, before=0),
              disk={".vqapr/cubes/<batch>/sample-prices/": "close.npy (735, 10) float64 58,928 B · present.npy (735, 10) bool 7,478 B · instants.npy (735,) · instruments.json 10 · cube.json", ".vqapr/cubes/<batch>/sample-features/": "momentum_5d.npy (12, 9) 992 B · present.npy · instants.npy (12,) · instruments.json 9 · cube.json (probe_cubes.py)"}),
            F("15_run_batch", 2904, "일꾼을 띄운다 — 여기서 지휘자의 트레이스는 경계를 만난다",
              "두 run이 두 프로세스에 하나씩 갑니다. 넘기는 건 문자열과 bool뿐(프로젝트 경로, run 이름, 저장소, force, cube 폴더). 1,182 ms 동안 지휘자는 기다립니다. 이 프로파일러는 이 프로세스의 것이라 일꾼 안의 호출은 여기 없습니다 — 다음 두 프레임은 일꾼을 따로 추적한 것입니다.",
              "<code>in_workers</code>(#2904, 1,182.3 ms) — 안쪽 호출 없음(다른 프로세스).",
              fn="in_workers()", code=("def", 10)),
            F("16_worker_factor", 16, "일꾼 — 문 하나를 지나고 판정을 받는다",
              "일꾼 프로세스는 장부를 열고(1 ms — 이미 데워진 파일) 자기 run을 <code>verify_run</code>에 넘깁니다: 판정 200 ms · 얼리기 23 ms · 봉지 0.7 ms. 판정이 거절하면 <code>check</code>와 같은 code로 거절되고 기록은 안 쓰입니다. 0.13.0까지 일꾼은 판정 없이 얼렸습니다 — check가 거절한 run을 배치가 돌리는 사고(이슈 015)가 거기서 났습니다. 그 뒤는 단일 run과 같습니다.",
              "<code>run_registered_strategy</code>(#0, 1,528.0 ms) → <code>Workspace.open</code>(#1, 1.0 ms) → <code>verify_run</code>(#16, 223.6 ms) → <code>judgments</code>(#18, 199.6 ms) → <code>preflight_run</code>(#1229, 23.0 ms) → <code>_freeze_strategy</code>(#1281) → <code>_freeze_sources</code>(#1620) → <code>RunResources.of</code>(#1682, 0.7 ms) → <code>require_ready</code>(#1696) → <code>registered_roster</code>(#1698, 20.7 ms) → <code>_run_strategy</code>(#1743, 1,282.0 ms) → <code>RunLoop.run</code>(#2224, 1,137.2 ms).",
              fn="run_registered_strategy() — worker", code=at("src/vqapr/flow/orchestration.py", "def run_registered_strategy", 12)),
            F("16_worker_factor", 2590, "일꾼 — 스캔 대신 구운 파일을 매핑한다",
              "일꾼의 첫 결정(01-12 08:00). 범위는 평소처럼 정하고(13 ms), 그 다음이 다릅니다: 창고에 cube 폴더가 있으니 <code>cube.json</code>의 원천 지문이 일꾼이 방금 확인한 지문과 같은지 본 뒤(1.8 ms), <code>momentum_5d.npy</code>를 메모리 매핑으로 열어 자기 기간의 행만 잘라 씁니다(2.3 ms). "
              "run이 선언한 종목(10)이 cube의 종목(9)과 달라 한 번 모으기(gather)를 합니다(11 × 10, K000010 열은 NaN). 이 트레이스 어디에도 스캔(<code>observation_table</code>)이 없습니다. 첫 결정 25 ms, 다음부터 6.6 ms.",
              "<code>SampleFactor.decide</code>(#2498, 25.1 ms) → <code>panel_window</code>(#2525, 19.4 ms) → <code>_scan_bounds</code>(#2540, 13.3 ms) → <code>open_cube</code>(#2564, 1.8 ms) → <code>panel_from_cube</code>(#2590, 2.3 ms) → <code>PanelWindow.matrix</code>(#2603) → <code>_callback_actual_source_refs</code>(#2716, 4.3 ms). 다음 날 <code>decide</code>(#4535, 6.6 ms).",
              fn="panel_from_cube()", code=at("src/vqapr/data/cube.py", "if whole and identical:", 8, before=2),
              mem={"cube": "sample-features: instants 12 · names 9 · digest 54f8fd04… = worker의 digest", "panel": "(11 × 10) gather — K000010 열 NaN"}),
            F("15_run_batch", 2905, "배치가 돌아오면 구운 파일은 없다 — 봉투는 run마다 하나",
              "일꾼 둘이 결과를 돌려주면 <code>batch_cubes</code>의 <code>finally</code>가 스레드를 멈추고 cube 폴더를 지웁니다(3.4 ms). 성공이든 거절이든 예외든 같습니다 — 쌓이는 게 없습니다. run마다 기록을 읽어 봉투를 만듭니다: factor 계좌 v10 · 주문 73 · 체결 54, stop-loss 계좌 v34 — ④·⑤와 같은 수. 봉투의 <code>jobs: 2</code>가 실제로 돈 프로세스 수입니다.",
              "<code>in_workers</code>(#2904) → <code>batch_cubes</code>(#2905, 3.4 ms: finally → rmtree) → <code>_worker_entry</code>(#2906, 16.0 ms: sample-factor-run) → <code>_strategy_envelope</code>(#2907) → <code>_worker_entry</code>(#3137, 18.5 ms: sample-stoploss-run) → <code>_runs_envelope</code>(#3482) → <code>success</code>(#3486).",
              fn="batch_cubes() — finally", code=at("src/vqapr/flow/orchestration.py", "_bake_for_batch(", 9, before=1),
              disk={".vqapr/cubes/": "비어 있음 (배치 폴더 삭제됨)", ".vqapr/runs/": "sample-factor-run · sample-stoploss-run 다시 씀 (--force)"}),
        ],
        "remember": [
            "일꾼도 verify_run을 지난다: check가 거절하는 run은 배치도 거절하고 기록을 쓰지 않는다.",
            "배치는 무엇을 읽는지 한 번 묻고, 표마다 cube를 한 번 굽고, 일꾼은 매핑한다. 끝나면 cube는 없다.",
        ],
    },
]

TABLE = {
    "title": "트레이스가 확인한 것 — 0.14.3의 자리와 그대로인 자리",
    "rows": [
        ["<b>[0.14.3] 콜백이 읽은 것은 한 번 만든다</b> (기록 246)",
         "08: <code>_callback_actual_source_refs</code> #3432 → <code>_stamp_intent</code> #3538 · <code>_callback_evidence</code> #3760 — 콜백당 1회, run 10회(0.14.2는 20). 10: 37회(0.14.2는 71). 16(worker): #2716. <code>inputs()</code>: 08 #2845(콜백 담당 조립) 한 번, 결정마다 0(0.14.2는 결정마다 1)",
         "한 사실은 한 번 읽고 나눠 쓴다 — 선언 쪽의 RunFacts와 같은 원칙이 콜백 안에도 있다"],
        ["<b>[0.14.3] 집행표의 날짜는 run 기간만큼만 읽는다</b> (기록 247)",
         "08: <code>distinct_values</code> #762 → 12 instants (<code>_local_date</code> ×12; 0.14.2는 ×734). 06: ×18 (×735). 10: ×38 (×734). 03(3년 run): ×734 그대로 — 기간이 표 전체다",
         "경계는 TIMESTAMPTZ 리터럴로 문장에 들어간다. 파라미터로 바인딩하면 프로세스의 첫 문장이 ~450 ms를 낸다(기록 247의 측정)"],
        ["<b>[0.14.3] 심장은 초당 한 번</b> (기록 248)",
         "<code>heartbeat</code> 호출 자체는 그대로(08 #3087 …): chunk마다 부른다. 그 안의 <code>os.utime</code>이 <code>LOCK_TOUCH_EVERY</code>(1 s)로 절제된다 — 프로파일러엔 vqapr 프레임만 잡혀 utime은 보이지 않고, 단위 테스트가 센다(20 chunk → 1회)",
         "죽은 run을 알아보는 기준은 120 s. 초당 한 번이면 백 번을 남기고 말한다"],
        ["<b>문 하나, 사실 한 번, run은 문이 만든 것을 받는다</b> (기록 240–242, 그대로)",
         "<code>verify_run</code>: 03 #336 · 06 #470 · 08 #722 · 10 #881 · 12 #1040 · 16 #16. <code>RunFacts.agenda</code>: 08 #749(읽음) → #1697 · #1861(0.05 ms). <code>RunResources.of</code>: 06 #2012 · 08 #2306 · 16 #1682. 실패한 읽기도 한 번: 03 #45889 해시 뒤 #48207 preflight는 저장된 예외",
         "check가 거절하는 것을 run과 worker도 거절한다. 선언은 명령당 한 번 읽힌다"],
        ["<b>읽기는 run 기간, 숫자는 행렬 한 벌, cube는 배치의 것</b> (기록 234–236, 그대로)",
         "<code>_scan_bounds</code>: 06 #2474 (17 × 10) · 08 #3245 (11 × 10) · 10 #6524 (38 × 10) · 12 (10 × 10 둘). <code>Panel.from_table</code>: 06 #3259 · 08 #3307. <code>verify_source</code>: 등록 01 #136 · #328 · 재등록 04 #451 · #643 · 출력 06 #7791 · 08 #23899. 16: <code>open_cube</code> #2564 → <code>panel_from_cube</code> #2590, <code>observation_table</code> 0번",
         "계산된 숫자는 하나도 다르지 않다: 체결 · 계좌 · 비중 dataset이 0.13.0 · 0.14.2 페이지와 같다(showcase digest 83/83)"],
        ["<b>run 시작의 명단 읽기는 설계다</b>",
         "<code>registered_roster</code> → <code>verify_roster</code>: 08 #2331 387.5 ms · 16(worker) #1698 20.7 ms. 각 프로세스의 첫 pyarrow 읽기이고, 매 run 새로 읽는다(이슈 009). 명단을 duckdb로 읽어도 그 import는 첫 record chunk가 낸다(한 콜백 캠페인의 결정 로그)",
         "값이 아니라 첫 import의 비용. run 경로에서 pyarrow를 빼는 것은 별개의 캠페인이다"],
        ["cold 읽기가 절대치를 지배한다",
         "등록의 <code>check_span</code> #213 2,100.6 ms(식은 디스크의 첫 duckdb 스캔; 두 번째 표는 #391 16.7 ms) · 명단 #46 413.0 ms(첫 pyarrow) · DataModel 첫 compute #2438 740.4 ms(스캔 462.7 + 첫 numpy 행렬 207.8) · 둘째 날부터 2 ms",
         "판끼리 절대치를 비교하지 말 것. 이 판은 로컬 디스크이되 캐시가 식은 상태였다"],
    ],
}
