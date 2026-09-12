# ruff: noqa: E501, RUF001 -- prose data: long lines and typographic characters are the content
# The 0.12.0 scenario stepper: six scenarios the owner named, every frame standing on a call the
# profiler recorded (traces: `README.md` beside this file; tools: `exp_230`).
#
# Rendered by `exp_230/render.py`, which executes this file with `REPO` bound to the tree the traces
# were taken on. A frame names its trace and call index; the renderer fills in the definition line,
# the qualified name and the milliseconds from the trace, and reads the code window from the tree.
# A number that appears anywhere here appears in a trace or in a record the traced commands wrote.

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
    """A frame's prose: the story first, the trace's call order folded beneath it."""
    html = f'<p class="story">{story}</p>'
    if calls:
        html += f'<details class="tr"><summary>트레이스에서 본 순서</summary><p>{calls}</p></details>'
    return html


def F(trace: str, idx: int, title: str, story: str, calls: str | None = None, **extra) -> dict:
    return {"trace": trace, "idx": idx, "title": title, "what": W(story, calls), **extra}


HEADER = {
    "title": "vqapr 0.12.0 시나리오 디버거",
    "storage_key": "vqapr-stepper-0120",
    "eyebrow": "vqapr 0.12.0 · develop (records 231–234) · 2026-09-10 · 실제 실행을 sys.setprofile로 추적한 결과",
    "h1": "vqapr 0.12.0 시나리오 디버거 — 사용자가 하는 일 여섯 가지, 프레임워크 안에서 한 프레임씩",
    "lede": (
        "<b>여섯 시나리오를 차례로 따라갑니다.</b> <code>vqapr new sample</code>이 만든 프로젝트(10종목, 2022-01-03 ~ 2024-12-30)에서 "
        "① 데이터를 <b>등록</b>하고, ② 등록이 <b>거절</b>되는 두 경우(파일에 없는 컬럼 · 등록 뒤에 바뀐 파일)를 보고, ③ <b>DataModel</b>을 돌려 firm characteristic(5일 모멘텀)을 dataset으로 쓰고, "
        "④ 그것을 읽는 <b>factor 전략</b>(상위 3 롱 · 하위 3 숏)을 돌리고, ⑤ <b>memory</b>로 진입가를 기억하는 <b>stop-loss 전략</b>을 돌리고, ⑥ ④가 저장한 alpha 비중을 읽어 <b>enhanced index</b>를 만듭니다. "
        "프레임마다 위에는 <b>지금 무슨 일이 일어나는지</b>를 보통 말로 적었고, 아래 접힌 곳에 트레이스가 기록한 호출 순서를 두었습니다. "
        "모든 <code>#idx</code>(그 명령 안에서 몇 번째 호출인지)와 <code>ms</code>는 <code>sys.setprofile</code>이 실제로 기록한 값이고, 스니펫은 그 시점의 소스 줄입니다 — "
        "상상한 것은 없습니다(<code>experiments/exp_235_the_scenario_trace/</code>)."
    ),
    "facts": [
        {"k": "데이터", "v": "10 × 735", "s": "종목 × 세션. 시나리오의 run 구간은 2022년 1~2월: datamodel 16세션 · factor 10 · stop-loss 37 · enhanced 9"},
        {"k": "명령 14개", "v": "호출 973 … 86,499", "s": "register 973 · register(거절) 427 · check(거절) 86,499 · register(재측정) 1,294 · run datamodel 12,820 · run factor 31,617 · run stop-loss 76,545 · run enhanced 34,410 · list datasets 1,081 · show run 32"},
        {"k": "문 하나", "v": "verify_source 6번", "s": "등록 2(가격표 · 집행표) · 재등록 2 · datamodel 출력 1 · 전략 배분 출력 3. 이후의 읽기는 전부 <code>require_verified</code>(digest 대조, 스캔 0)"},
        {"k": "factor run", "v": "롱 3 · 숏 3", "s": "10세션 · 주문 73 · 체결 54 · 첫날 K000003 +23 · K000008 +8 · K000009 +94 · K000004 −55 · K000005 −19 · K000006 −12 · 비중 dataset 60행"},
        {"k": "stop-loss run", "v": "9 → 0", "s": "37세션 · 첫날 9종목 진입, 3% 손절이 8번 발동해 2022-02-22엔 K000008 하나, 02-23에 전량 매도 → 현금 84,184,068.92 · memory에 entry 9 → 0 · stopped 9"},
        {"k": "enhanced run", "v": "0.111 ± 0.083", "s": "동일가중 1/9 에 factor 비중의 절반을 더한다: K000002·3·8 0.194 · K000004·5·9 0.028 · 나머지 0.111 (롱온리, 합 1)"},
    ],
    "fix": (
        "<strong>시간 읽는 법.</strong> ms는 프로파일러가 켜진 채 잰 값이라 절대치는 실제보다 큽니다. 같은 트레이스 안에서 <b>서로 비교</b>만 하십시오. "
        "한 프로세스에서 parquet을 <b>처음</b> 여는 호출이 유난히 큽니다(등록의 명단 읽기 418 ms · span 측정 149 ms, datamodel의 첫 compute 349 ms). 같은 질문을 두 번째 물을 땐 한 자릿수 ms입니다. "
        "0.11.0 페이지의 11.8 s짜리 <code>check</code>는 집행표를 세 번 스캔한 값이었고, 이제 그 자리는 digest 대조 3.9 ms입니다(②)."
    ),
    "glossary_title": "이 페이지에 나오는 낱말 — 먼저 읽어 두면 편합니다",
    "glossary": [
        ("선언 (declaration)", "당신이 쓰는 YAML. \"이 parquet은 가격이다, 이 파일은 내 전략이다, 이 run은 이렇게 돌려라\"."),
        ("등록부 (workspace)", "<code>.vqapr/workspace.yaml</code>. <code>register</code>가 쓰고, 모든 명령이 맨 처음 펼쳐 읽는다. 코드에선 <code>Workspace</code>."),
        ("문 (validation door)", "<code>data/validation.py</code>. 물리 파일은 등록될 때 <b>여기서 한 번</b> 잰다(스키마 · key · span · 값 · 집행 가격 · digest). 등록부는 잰 결과를 들고, 이후의 모든 읽기는 파일 <i>내용</i>이 아니라 <i>digest</i>를 대조한다(<code>require_verified</code>). 기록 234."),
        ("digest · 측정된 반쪽", "파일 바이트의 sha256. 등록의 선언된 반쪽(컬럼 · key · grain)은 사용자의 것, 측정된 반쪽(span · digest · 집행 가격)은 문의 것. 파일이 바뀌면 같은 선언으로 다시 등록해 측정만 갈아 끼운다."),
        ("검사·판정 (check · judgment)", "\"이 run을 돌려도 되나\"에 대한 예/아니오 하나하나. <code>check</code>는 모아서 답하고, <code>run</code>은 첫 거절에서 멈춘다."),
        ("얼리기 (freeze → FrozenRun)", "등록부에 적힌 <i>이름</i>들을 <i>실제 값</i>(코드 fingerprint, parquet 경로와 digest, 결정 시각들, 초기 계좌)으로 풀어 묶은 불변 스냅샷. 이 뒤로 등록부가 바뀌어도 run은 이것만 본다."),
        ("전략 시계 · 시장 시계", "agenda가 만드는 결정 시각(매일 08:00 또는 09:00)과 집행표에 행이 있는 시각(매일 15:30). 결정은 앞에서, 체결·평가·판정은 뒤에서만."),
        ("창 (window) · matrix()", "한 alias의 한 필드를 <i>시각 × 종목</i>으로 본 것. <code>window.matrix()</code>는 그것을 float 행렬 하나로 준다(마지막 행이 최신, 없는 값은 NaN). 종목 for loop 없이 한 식으로 계산한다. 기록 232."),
        ("DataModel · materialized dataset", "세션마다 종목별 행을 돌려주는 모델. run이 끝나면 그 행들이 <code>.vqapr/materialized/&lt;writes&gt;/all.parquet</code>이 되고 <b>같은 문을 지나</b> dataset으로 등록된다. 다음 run은 벤더 표와 똑같이 읽는다."),
        ("writes · 배분 dataset", "전략 run도 자기 비중(<code>vqapr.weight</code>)을 <code>writes</code>가 이름한 dataset으로 낸다. 다른 run이 그것을 alpha로 읽을 수 있다(⑥)."),
        ("memory", "전략의 <code>self.memory</code>. 엄격한 JSON. 매 <code>decide</code> 전에 복원되고 뒤에 정규화되어 publish된다. 첫 콜백엔 <code>{}</code>."),
        ("의도서 (intent) · pending", "전략이 돌려준 목표 비중에 프레임워크가 도장을 찍은 것. 체결 시각이 올 때까지 pending으로 하나만 기다린다. <code>Hold</code>면 pending 없음."),
        ("봉투 (envelope)", "모든 명령이 stdout에 내는 JSON 한 덩어리. 성공이든 거절이든 모양이 같다: <code>ok · stage · failures[code · status · requirement · observed · fix]</code>."),
    ],
}

MAP = [
    ("①", "데이터 등록", "선언 → 문 → 등록부"),
    ("②", "등록 오류", "없는 컬럼 · 바뀐 파일"),
    ("③", "DataModel", "firm characteristic → dataset"),
    ("④", "factor 전략", "롱 3 · 숏 3 · 비중 저장"),
    ("⑤", "stop-loss", "memory가 진입가를 든다"),
    ("⑥", "enhanced index", "저장된 alpha를 읽는다"),
]

SCENES = [
    # ---------------------------------------------------------------- ① register
    {
        "id": "reg", "key": "①", "title": "데이터 등록",
        "sub": "vqapr register sample.yaml · 808 ms · 973 호출",
        "story": (
            "<b>지금 하는 일:</b> 당신이 <code>sample.yaml</code>을 건넨다. 거기엔 종목 명단, 가격 parquet(<code>sample-prices</code>), 집행표 parquet(<code>sample-execution</code>), 전략 코드, 거래소 코드, run 하나가 적혀 있다. "
            "vqapr은 이 문서를 그대로 믿지 않는다 — parquet을 <b>한 문에서 실제로 열어</b> 선언과 맞는지 재고 digest를 남기고, 전략과 거래소 코드를 <b>실제로 import</b>해 계약대로인지 본 뒤, "
            "그제야 등록부(<code>.vqapr/workspace.yaml</code>) 한 파일을 쓴다. 이 페이지의 다른 다섯 시나리오는 전부 이 등록부 위에서 일어난다."
        ),
        "frames": [
            F("01_register", 0, "명령줄이 register 핸들러를 고른다",
              "<code>vqapr --project-root sample register sample.yaml</code>. argparse가 verb를 고르고 프로젝트 루트를 정한 뒤 핸들러를 부른다. 808 ms의 거의 전부(796.5 ms)는 핸들러 안에서 보낸다. 무엇이 잘못되든 결과는 같은 모양의 JSON 봉투다.",
              "<code>build_parser</code>(#1, 7.4 ms) → <code>_resolve_project_root</code>(#10) → <code>register.run</code>(#11, 796.5 ms) → <code>read_yaml_mapping</code>(#12, 32 ms) → <code>apply</code>(#13, 763.8 ms).",
              fn="main() → register.run()", code=at("src/vqapr/cli/main.py", "def main(", 14),
              mem={"argv": "['--project-root', '.../sample', 'register', '.../sample/sample.yaml']"}, disk={".vqapr/": "없음"}),
            F("01_register", 14, "트랜잭션을 열고, 섹션을 정해진 순서로 처리한다",
              "모르는 섹션 이름이 있으면 여기서 이름을 대며 거절한다(#25). 그 다음 <b>트랜잭션</b>을 연다 — 등록부의 스냅샷 위에 하나씩 올려 두었다가 맨 끝에 한 번에 쓰는 장치. 디스크는 아직 그대로다. "
              "처리 순서는 instruments → datasets → components → runs: 뒤의 것이 앞의 것을 이름으로 가리키기 때문이다(run은 전략 id와 dataset id를 든다).",
              "<code>Workspace.transaction</code>(#15, 0.6 ms) → <code>_require_declared_ids</code>(#25) → <code>_instruments</code>(#43, 421 ms) → datasets(#136 · #328) → components(#468 · #614) → runs(#877) → <code>commit</code>(#902).",
              fn="_apply() — 섹션 순서", code=at("src/vqapr/project/registration.py", 'for dataset_id, body in section("datasets")', 7),
              mem={"document": "dict (instruments 1, datasets 2, components 2, runs 1)", "transaction.staged": "[]"}),
            F("01_register", 46, "종목 명단도 같은 문을 지난다 — verify_roster",
              "명단 parquet(<code>instruments_stock.parquet</code>)은 문의 <code>verify_roster</code>가 연다. 없는 파일이나 컬럼이 빠진 표는 raise가 아니라 <b>Diagnosis</b>(<code>roster.table_missing</code> · <code>roster.table_invalid</code>)로 돌아와 다른 거절 옆에 놓인다. "
              "이 프로세스에서 parquet을 처음 여는 호출이라 417.7 ms — 뒤의 읽기들은 수십 ms다. 10종목이 <code>InstrumentRoster</code>가 되고 트랜잭션에 올라간다.",
              "<code>verify_roster</code>(#46, 417.7 ms) → <code>Diagnosis.ok</code>(#49) → <code>build_roster</code>(#50, 1.5 ms: <code>instrument</code> ×10) → <code>Transaction.register_instruments</code>(#83).",
              fn="verify_roster()", code=at("src/vqapr/data/validation.py", "def verify_roster", 12),
              mem={"transaction.staged": "[instruments: stock 10, digest 875b5fe1…]"}),
            F("01_register", 136, "가격 parquet을 열어 여섯 가지를 잰다 — verify_source",
              "선언은 \"<code>available_at</code>이 시각이고 <code>close</code>가 DOUBLE이고 (시각, 종목)이 유일하다\"고 말한다. 문은 믿지 않고 파일을 열어 순서대로 묻는다: "
              "<b>스키마</b>(선언한 컬럼이 다 있고 타입이 맞나, 14.0 ms) → <b>key</b>(null · 중복, 16.1 ms) → <b>span</b>(첫 시각과 끝 시각, 148.9 ms) → <b>값</b>(DOUBLE에 NaN · Inf가 없나, 15.0 ms) → <b>집행 가격</b>(이 표엔 execution 역할이 없어 0.002 ms) → <b>digest</b>(바이트의 sha256, 0.5 ms). "
              "돌아오는 등록은 span과 <code>source_digest</code>를 든다. 여기가 이 파일이 <b>내용으로</b> 검사되는 유일한 자리다 — 뒤의 모든 명령은 digest만 대조한다.",
              "<code>verify_source</code>(#136, 209.6 ms) → <code>check_schema</code>(#149) → <code>execution_role_failures</code>(#190) → <code>check_key</code>(#192) → <code>check_span</code>(#213) → <code>check_values</code>(#224) → <code>check_execution_prices</code>(#276) → <code>physical_digest</code>(#278) → <code>with_verification</code>(#280) → <code>Transaction.register_dataset</code>(#282) → <code>spoken</code>(#288).",
              fn="verify_source() — 여섯 단계", code=at("src/vqapr/data/validation.py", "def verify_source", 14),
              mem={"measured.span": "2022-01-03 15:30 ~ 2024-12-30 15:30 +09:00", "measured.source_digest": "18bb7017…"}),
            F("01_register", 436, "집행표는 한 가지를 더 잰다 — 어느 가격이 거래 가능한 행마다 양수인가",
              "<code>sample-execution</code>은 <code>execution: {is_tradable}</code> 역할을 선언했다. 같은 다섯 단계 뒤에 문은 <b>후보 가격 전부</b>에 대해 \"tradable인 행마다 유한하고 양수인가\"를 한 번에 묻고(13.2 ms) 답을 <code>execution_prices</code>로 등록에 남긴다 — 여기선 <code>['close']</code>. "
              "run이 나중에 <code>trade_price: close</code>를 고르면 preflight는 이 튜플을 조회할 뿐 표를 다시 스캔하지 않는다(0.11.0까지는 check와 run이 매번 스캔했다).",
              "<code>verify_source</code>(#328, 82.2 ms) → <code>check_schema</code>(#338) → <code>execution_role_failures</code>(#367) → <code>check_key</code>(#370) → <code>check_span</code>(#391) → <code>check_values</code>(#402) → <b><code>check_execution_prices</code>(#436, 13.2 ms)</b> → <code>physical_digest</code>(#453) → <code>register_dataset</code>(#459).",
              fn="check_execution_prices()", code=at("src/vqapr/data/validation.py", "def check_execution_prices", 14),
              mem={"measured.execution_prices": "('close',)", "measured.source_digest": "49e4b4ab…"}),
            F("01_register", 552, "전략과 거래소 코드는 실제로 import해서 계약을 본다",
              "<code>reversal_5d.py</code>를 fingerprint(바이트의 해시, #472)하고 import해 <code>StrategyModel</code>의 메서드 시그니처가 맞는지 본다(<code>conformance</code>, 5.7 ms). 거래소(<code>exchange.py</code>)도 같은 길(#614~#812). "
              "옛 시그니처로 쓴 규칙이 여기서 거절되는 것을 0.11.0 페이지가 보였다; 오늘은 둘 다 통과해 트랜잭션에 오른다.",
              "<code>_component</code>(#468, 10.6 ms) → <code>prepare_component</code>(#471) → <code>fingerprint_component</code>(#472) → <code>conformance</code>(#552) → <code>_check_methods</code>(#599) → <code>register_component</code>(#608) · 거래소 <code>_component</code>(#614) → <code>conformance</code>(#722) → <code>register_component</code>(#812).",
              fn="conformance()", code=("def", 10),
              mem={"transaction.staged": "[instruments, sample-prices, sample-execution, sample-reversal-5d, sample-exchange]"}),
            F("01_register", 902, "run을 올리고, 한 번에 쓴다",
              "run <code>sample-run</code>이 전략 id · dataset id · 거래소 id로 앞의 것들을 가리키고(#877), 사람 말로 푼 문장(<code>spoken</code>, #889)이 봉투에 들어간다: \"<i>dataset 'sample-prices': a row is knowable at its 'available_at' value and never earlier</i>\", \"<i>run 'sample-run' fills against dataset 'sample-execution': the first execution instant after the decision, at 15:30:00 Asia/Seoul, at its 'close' price</i>\". "
              "<code>commit</code>이 lock을 잡고 등록부를 한 번 읽고 올려 둔 것을 순서대로 합친 뒤 <b>한 번</b> 쓴다(8.1 ms). 디스크에 처음으로 <code>.vqapr/workspace.yaml</code>이 생기고, 두 dataset 항목엔 <code>source_digest</code>가, 집행표엔 <code>execution_prices: [close]</code>가 적힌다.",
              "<code>register_run</code>(#877) → <code>_merge_run</code>(#881) → <code>RunDefinition.spoken</code>(#889) → <code>Transaction.commit</code>(#902, 11.5 ms) → <code>_merge_component</code> ×2(#913 · #915) → <code>_merge_run</code>(#917) → <code>Workspace._write</code>(#924, 8.1 ms).",
              fn="Transaction.commit()", code=("def", 16),
              disk={".vqapr/workspace.yaml": "datasets 2 (source_digest · execution_prices) · components 2 · runs 1", ".vqapr/instruments.json": "stock 10, digest 875b5fe1…"}),
        ],
        "remember": [
            "물리 파일은 등록될 때 문에서 한 번 잰다: 스키마 → key → span → 값 → 집행 가격 → digest. 등록부가 잰 결과를 든다.",
            "명단 · 가격표 · 집행표 · 코드 — 넷 다 실제로 열어 본 뒤에야 등록부를 쓴다. 쓰기는 commit 한 번.",
        ],
    },
    # ---------------------------------------------------------------- ② registration errors
    {
        "id": "err", "key": "②", "title": "등록 오류",
        "sub": "register bad.yaml · 63 ms · 427 호출 (거절) — check sample-run · 3,624 ms · 86,499 호출 (거절) — register sample.yaml 다시 · 700 ms · 1,294 호출",
        "story": (
            "<b>지금 하는 일:</b> 두 가지 실수를 저지른다. 먼저 <code>bad.yaml</code>로 파일에 <b>없는 컬럼</b>(<code>adj_close</code>)을 선언한 dataset을 등록한다 — 문이 파일을 열어 보고 이름을 대며 거절하고, 등록부는 한 바이트도 바뀌지 않는다. "
            "다음엔 등록이 끝난 뒤 <code>execution.parquet</code>을 <b>다른 바이트로 덮어쓴다</b>(마지막 날을 뺀 유효한 파일). <code>check sample-run</code>은 표를 다시 스캔하지 않고 digest 하나를 대조해 <code>dataset.source_changed</code>로 막고, 고치는 법을 말한다: 같은 선언으로 다시 등록하라. 그렇게 하면 측정된 반쪽만 갈린다."
        ),
        "frames": [
            F("02_register_bad", 383, "문이 파일을 열어 선언과 대조한다 — 첫 단계에서 멈춘다",
              "<code>sample-adjusted</code>는 <code>observations.parquet</code>에 <code>adj_close</code> 컬럼이 있다고 말한다. <code>verify_source</code>가 파일의 스키마를 읽고(<code>describe</code>, 16.4 ms) <code>check_schema</code>가 선언과 맞춘다: 없다. 이 뒤의 단계(key · span · 값 · digest)는 돌지 않는다 — 스키마가 틀린 파일에 key를 묻는 것은 뜻이 없다.",
              "<code>verify_source</code>(#383, 19.6 ms) → <code>describe</code>(#384, 16.4 ms) → <code>check_schema</code>(#396, 3.0 ms) → <code>Diagnosis.ok</code>(#411) = False → <code>raise_if_failed</code>(#412).",
              fn="check_schema()", code=at("src/vqapr/data/validation.py", "def check_schema", 12),
              mem={"observed": "available_at, close, high, instrument, low, open, volume"}),
            F("02_register_bad", 417, "거절은 이름 · 관찰 · 고치는 법을 든 봉투다 — 그리고 등록부는 그대로다",
              "봉투 한 장: <code>dataset.field_missing</code> (400) · requirement \"<i>fields[adj_close] declares column 'adj_close', which must exist</i>\" · observed \"<i>available_at, close, high, instrument, low, open, volume</i>\" · fix \"<i>add column 'adj_close' to the prepared source, or point fields[adj_close] at a column it already has</i>\" · source <code>datasets.sample-adjusted.fields[adj_close]</code> · cause <code>data/validation.py:153 (check_schema)</code>. "
              "<code>mutation: false</code> — 트랜잭션은 열렸지만 commit되지 않았다. exit 1.",
              "<code>raise_if_failed</code>(#412) → <code>envelope.failure</code>(#417, stage register) → exit 1.",
              fn="envelope.failure()", code=("def", 10),
              disk={".vqapr/workspace.yaml": "바뀌지 않음 (mutation: false)"}),
            F("03_check_changed", 336, "파일이 바뀐 뒤의 check — 판정 하나하나가 답한다",
              "<code>execution.parquet</code>이 다른 바이트가 된 채로 <code>check sample-run</code>. <code>check</code>는 등록부를 열고(#14, 29 ms) 판정들을 <b>모아서</b> 묻는다: 종목 집합(#349) · 명단(#351) · 기간(#358) · <b>집행 순서</b>(#360) · 멤버의 dataset(#42238) · 비중(#44520) · 출력(#44522). "
              "집행 순서 판정은 먼저 agenda를 유도한다 — 3년짜리 run이라 735세션, 1,782 ms — 그리고 집행표를 묶는다.",
              "<code>check</code>(#12, 3,614 ms) → <code>Workspace.open</code>(#14) → <code>judgments</code>(#336, 1,900 ms) → <code>_judge_execution_ordering</code>(#360) → <code>derived_agenda</code>(#362, 1,782 ms) → <code>bound_execution_table</code>(#42201).",
              fn="judgments()", code=("def", 10),
              tip="이 트레이스에서 큰 것은 표 스캔이 아니라 agenda 유도다 — 그리고 preflight가 같은 agenda를 한 번 더 유도한다(#44533, 1,673 ms). 3년 run의 check 3.6 s 중 3.5 s가 그것이다. 다음 이슈 후보."),
            F("03_check_changed", 42210, "표를 다시 스캔하지 않는다 — digest 하나를 대조한다",
              "<code>bound_execution_table</code>은 등록부에 <code>require_verified('sample-execution')</code>을 묻는다. 등록이 든 digest <code>49e4b4ab…</code>와 지금 파일의 sha256 <code>bf30cb34…</code>(0.39 ms)가 다르다 → <code>dataset.source_changed</code> (412, stage freeze): "
              "\"<i>the bytes a run reads must be the bytes registration measured; every fact the registration carries (span, key, prices) was measured on them</i>\", fix \"<i>register dataset 'sample-execution' again so its facts are measured on the file as it is now</i>\". 0.11.0의 이 자리는 스키마 · key · 가격 스캔 11.5 s였다.",
              "<code>bound_execution_table</code>(#42201, 3.9 ms) → <code>Workspace.require_verified</code>(#42202) → <code>Workspace.dataset</code>(#42203) → <code>Workspace.source</code>(#42207) → <code>require_verified</code>(#42210, 3.6 ms) → <code>physical_digest</code>(#42211, 0.39 ms) → <code>Failure.bounded</code>(#42213).",
              fn="require_verified()", code=at("src/vqapr/data/validation.py", "def require_verified", 14),
              mem={"registered": "49e4b4abef4f…", "file now": "bf30cb34b1ca…"},
              caution="판정 하나가 답하지 못하면 봉투는 그것을 <code>blocked</code>(judgment.blocked, cause에 예외 전체)에 두고, 원인 거절은 <code>failures</code>에 둔다. checked 4 · passed [workspace, run] · failures [dataset.source_changed]. 실패한 대조는 memo되지 않아 preflight가 한 번 더 해시한다(#86465, 4.5 ms)."),
            F("04_register_again", 643, "같은 선언으로 다시 등록한다 — 측정만 다시 한다",
              "<code>register sample.yaml</code>을 다시. 선언은 한 글자도 바뀌지 않았고 파일만 다르다. 문이 두 표를 다시 잰다(가격표 162 ms · 집행표 86 ms): span, digest(<code>bf30cb34…</code>), 집행 가격. 트랜잭션에 올라갈 때 <code>_merge_dataset</code>이 기존 등록과 비교한다.",
              "<code>verify_source</code>(#451, 162.4 ms) → <code>physical_digest</code>(#593) → <code>register_dataset</code>(#597) → <code>_merge_dataset</code>(#601) · <code>verify_source</code>(#643, 86.3 ms) → <code>physical_digest</code>(#768) → <code>register_dataset</code>(#774) → <code>_merge_dataset</code>(#778).",
              fn="verify_source() 다시", code=("def", 8)),
            F("04_register_again", 778, "선언된 반쪽이 같으면 측정된 반쪽을 갈아 끼운다",
              "<code>_merge_dataset</code>은 기존 등록의 span · aggregated · digest · 집행 가격을 새 측정으로 바꾼 사본이 새 등록과 <b>같은지</b> 본다. 같다 → 선언은 그대로이고 측정만 바뀐 것이니 받아들인다. 컬럼 이름 하나라도 달랐다면 <code>dataset.registered</code>(409)로 거절했을 것이다. "
              "0.12.0 이전엔 span이 다르면 여기서 거절돼 \"register again\"이 되지 않는 명령이었다. commit이 등록부를 다시 쓴다(#1245, 8.1 ms). 이 뒤의 run들은 이 digest를 대조한다.",
              "<code>_merge_dataset</code>(#778) → … <code>Transaction.commit</code>(#1217, 12.1 ms) → <code>_merge_dataset</code> ×2(#1230 · #1232: 재생) → <code>Workspace._write</code>(#1245).",
              fn="_merge_dataset() — remeasured", code=at("src/vqapr/project/merge.py", "remeasured = replace(", 12, before=6),
              disk={".vqapr/workspace.yaml": "sample-execution.source_digest: 49e4b4ab… → bf30cb34… (이 페이지의 run들은 원본 바이트로 되돌린 뒤 한 번 더 등록한 상태에서 돌았다)"}),
        ],
        "remember": [
            "등록이 거절되면 봉투가 code · requirement · observed · fix · source를 들고, 등록부는 바뀌지 않는다.",
            "등록 뒤에 파일이 바뀌면 읽는 쪽이 digest 하나로 알아채고, 고치는 법은 같은 선언으로 다시 등록하는 것이다.",
        ],
    },
    # ---------------------------------------------------------------- ③ datamodel
    {
        "id": "dm", "key": "③", "title": "DataModel → firm characteristic",
        "sub": "register features.yaml · 71 ms · 647 호출 — run sample-features-run · 1,151 ms · 12,820 호출 · 16세션 · 108행",
        "story": (
            "<b>지금 하는 일:</b> <code>features.py</code>의 <code>SampleFeatures</code>는 세션마다 종목별 <b>5일 모멘텀</b>(여섯 종가 중 마지막 ÷ 첫 번째 − 1)을 돌려주는 DataModel이다. run은 전략 시계만 돈다(매일 16:00, 시장 시계 없음). "
            "첫 다섯 세션은 창이 덜 차서 빈 목록, 2022-01-10부터 종목당 한 행. run이 끝나면 108행이 <code>.vqapr/materialized/sample-features/all.parquet</code>이 되고 <b>①과 같은 문</b>을 지나 dataset <code>sample-features</code>로 등록된다 — 다음 시나리오의 전략이 벤더 표처럼 읽는다."
        ),
        "frames": [
            F("06_run_features", 7415, "얼리기 — 읽을 dataset의 identity를 대조한다",
              "run을 돌리기 전에 preflight가 판정을 다시 하고(#3898) 등록부의 이름들을 값으로 얼린다. 이 모델이 읽는 <code>sample-prices</code>는 <code>require_verified</code> 한 번(0.95 ms): 등록의 digest와 파일이 같다. FrozenRun에 그 digest가 들어간다(<code>source_digests</code>).",
              "<code>preflight_run</code>(#470, 441.9 ms) → <code>preflight_run</code>(#3898, 178.7 ms) → <code>_freeze_datamodel</code>(#7185) → <code>_freeze_agenda</code>(#7228) → <code>_freeze_sources</code>(#7415) → <code>Workspace.require_verified</code>(#7417) → <code>require_verified</code>(#7425, 0.6 ms) → <code>freeze_run_record</code>(#7475).",
              fn="_freeze_sources()", code=("def", 12),
              mem={"frozen.source_digests": "{sample-prices-source: 18bb7017…}"}),
            F("06_run_features", 7621, "같은 RunLoop, 시장 시계 없이",
              "<code>_run_member</code>가 멤버 하나의 자원(스캔 세션 · store · writer · 창)을 만들고 <code>datamodel_loop</code>가 <code>RunLoop(part=DataModelPart, market=None)</code>을 조립한다. 전략 run과 같은 클래스 — 다른 것은 Part와 시장 시계뿐이다(기록 231).",
              "<code>_run_member</code>(#7600, 652.8 ms, member_kind='datamodel') → <code>datamodel_loop</code>(#7621, 4.7 ms) → <code>RunLoop.run</code>(#7737, 543 ms) → <code>RunOutput.open</code>(#7740) → <code>RunLoop.handle</code> ×16.",
              fn="datamodel_loop()", code=at("src/vqapr/flow/run/loop.py", "def datamodel_loop", 12)),
            F("06_run_features", 7922, "첫 세션 — 창을 행렬로 읽고, 아직 여섯 행이 아니라 빈 목록",
              "2022-01-04 16:00. <code>context.read('prices', 'close')</code>가 창을 만들고 <code>window.matrix()</code>가 시각 × 종목 float 행렬을 준다. 이 프로세스의 첫 parquet 읽기라 349 ms(그중 <code>observation_table</code> 337.7 ms; 행렬로 접는 <code>Panel.from_table</code>은 8.6 ms). "
              "행이 2개뿐이라(01-03 · 01-04) <code>LOOKBACK=6</code>에 못 미쳐 <code>[]</code>를 돌려준다. 프레임워크는 빈 목록을 그대로 받는다(<code>rows=[]</code>).",
              "<code>RunLoop.handle</code>(#7879, 351 ms) → <code>DataModelPart.dispatch</code>(#7880) → <code>SampleFeatures.compute</code>(#7922, 349 ms) → <code>panel_window</code>(#7943) → <code>observation_table</code>(#7960, 337.7 ms) → <code>Panel.from_table</code>(#7998, 8.6 ms) → <code>PanelWindow.matrix</code>(#8007, 0.19 ms) → <code>derived_available_at</code>(#8014) → <code>RunOutput.append</code>(#8016, rows=[]).",
              fn="SampleFeatures.compute() — 저자 코드", code=at(DECL + "features.py", "closes = window.matrix()", 12, before=1), author=True,
              mem={"closes.shape": "(2, 10) — 세션 2 × 종목 10", "returned": "[]"}),
            F("06_run_features", 8352, "여섯 번째 세션 — 종목 10개의 모멘텀을 한 식으로",
              "2022-01-10 16:00. 창에 여섯 행이 찼다. <code>closes[-1] / closes[0] - 1.0</code>가 열마다(=종목마다) 한 번에 계산되고, 완전한 열만 행으로 나간다: K000001 −0.90% · K000002 −3.34% · K000003 +8.55% … 이번 compute는 1.8 ms — 창 읽기가 0.8 ms로 내려왔다. "
              "<code>available_at</code>은 저자가 아니라 프레임워크가 찍는다(16:00, 이 세션의 평가 시각): 이 값은 <b>이 시각에야</b> 알 수 있는 값이다.",
              "<code>RunLoop.handle</code>(#8309, 13.1 ms) → <code>compute</code>(#8352, 1.8 ms) → <code>matrix</code>(#8393) → <code>derived_available_at</code>(#8642) → <code>RunOutput.append</code>(#8644, rows=[{available_at: 2022-01-10 16:00+09:00, instrument: 'K000001', momentum_5d: …}, …]).",
              fn="SampleFeatures.compute() — 행 10", code=at(DECL + "features.py", "momentum = closes[-1]", 8, before=2), author=True,
              mem={"rows this session": "10", "rows so far": "10 → 세션 16에서 108"}),
            F("06_run_features", 12453, "출력이 dataset이 된다 — 같은 문을 지나서",
              "16세션이 끝나면 <code>RunOutput.register</code>가 모은 행을 <code>all.parquet</code>으로 굳히고(<code>_seal</code>) 그 파일을 <b>①의 <code>verify_source</code>에 그대로</b> 넣는다: 스키마 · key(available_at, instrument) · span(01-10 16:00 ~ 01-25 16:00) · 값 · digest <code>54f8fd04…</code>. 통과하면 등록부에 <code>sample-features</code>가 <code>produced_by: sample-features-run</code>, <code>produced_by_record: sample-features@20c2acad</code>와 함께 적힌다. "
              "프레임워크가 쓴 표라고 문을 건너뛰지 않는다.",
              "<code>RunOutput.register</code>(#12422, 86 ms) → <code>_seal</code>(#12451) → <code>verify_source</code>(#12453, 67 ms) → <code>check_schema</code>(#12462) → <code>check_key</code>(#12489) → <code>check_span</code>(#12510) → <code>check_values</code>(#12521) → <code>physical_digest</code>(#12555) → <code>register_dataset</code>(#12577) → <code>commit</code>(#12584) → <code>Workspace._write</code>(#12598).",
              fn="RunOutput.register()", code=("def", 14),
              disk={".vqapr/materialized/sample-features/all.parquet": "108행 (available_at · instrument · momentum_5d)", ".vqapr/runs/sample-features-run/": "run.json · datamodels/sample-features@20c2acad/datamodel.json", ".vqapr/workspace.yaml": "datasets + sample-features (source_digest 54f8fd04…)"}),
        ],
        "remember": [
            "DataModel은 세션마다 종목별 행을 돌려주고, available_at은 프레임워크가 그 세션의 시각으로 찍는다.",
            "출력 parquet도 등록될 때 같은 문을 지난다. 다음 run은 그것을 벤더 표와 구별하지 않는다.",
        ],
    },
    # ---------------------------------------------------------------- ④ factor strategy
    {
        "id": "factor", "key": "④", "title": "factor 전략",
        "sub": "register factor.yaml · 105 ms · 1,058 호출 — run sample-factor-run · 2,384 ms · 31,617 호출 · 10세션 · 이벤트 20",
        "story": (
            "<b>지금 하는 일:</b> <code>factor.py</code>의 <code>SampleFactor</code>는 ③이 만든 <code>sample-features.momentum_5d</code>를 <b>벤더 표처럼</b> 한 줄로 선언해 읽고(최신 행 하나), 상위 3종목 롱 · 하위 3종목 숏, 각 1/6씩(달러 중립, <code>Rebalance.signed</code>)을 돌려준다. "
            "숏이 있으니 거래소는 SIGNED 상장이 필요하다 — <code>exchange_signed.py</code>가 같은 열 종목을 <code>ListingAccess.SIGNED</code>로 든다. run은 2022-01-12 ~ 01-25, 계좌 mode SIGNED. 끝나면 비중이 <code>sample-factor-weights</code>로 저장된다(⑥이 읽는다)."
        ),
        "frames": [
            F("08_run_factor", 3637, "preflight — 읽을 dataset과 집행표를 identity로 묶는다",
              "이 전략이 읽는 <code>sample-features</code>는 다른 run이 쓴 표지만 preflight엔 다른 dataset과 똑같다: <code>require_verified</code>(0.6 ms). 집행표는 등록의 <code>execution_prices=['close']</code>에 <code>trade_price: close</code>가 있는지 <b>튜플 조회</b>로 본다 — 0.11.0의 가격 스캔이 있던 자리. 얼린 run은 세 digest(가격표 · 집행표 · feature 표)를 든다.",
              "<code>preflight_run</code>(#722, 808.6 ms) → <code>require_verified</code>(#3637) … <code>preflight_run</code>(#3959) → <code>require_verified</code>(#6941, 0.002 ms: 같은 workspace 객체라 memo) → <code>_freeze_sources</code>(#7391) → <code>require_verified</code>(#7401).",
              fn="_validate_requirement()", code=at("src/vqapr/flow/declaration/preflight.py", "def _validate_requirement", 14)),
            F("08_run_factor", 8490, "아침 8시 — feature 한 행을 읽고 여섯 이름을 고른다",
              "2022-01-12 08:00. <code>call.read('features', 'momentum_5d')</code>는 01-11 16:00의 행(전날 저녁에 알 수 있던 값)을 창으로 준다 — 행 하나 × 종목 10. 정렬해서 하위 3(K000004 · K000005 · K000006)에 −1/6, 상위 3(K000003 · K000008 · K000009)에 +1/6. "
              "<code>Rebalance.signed(weights, gross=1)</code>: 부호가 방향이고 gross 1이면 롱 0.5 · 숏 0.5. 이 decide는 12.8 ms(feature 표 첫 읽기 7 ms 포함), 다음 날은 7.4 ms.",
              "<code>RunLoop.handle</code>(#8370, 45.5 ms) → <code>StrategyPart.dispatch</code>(#8371) → <code>SampleFactor.decide</code>(#8490, 12.8 ms) → <code>panel_window</code>(#8517, 7.1 ms) → <code>observation_table</code>(#8534) → <code>Panel.from_table</code>(#8572) → <code>Rebalance.signed</code>(#8596, 4.2 ms) → <code>RunStateRepository.publish</code>(#9230).",
              fn="SampleFactor.decide() — 저자 코드", code=at(DECL + "factor.py", "ranked = sorted(", 10, before=3), author=True,
              mem={"weights": "K000003 +0.1667 · K000008 +0.1667 · K000009 +0.1667 · K000004 −0.1667 · K000005 −0.1667 · K000006 −0.1667", "pending": "intent 1 (계좌 v0 기준)"}),
            F("08_run_factor", 9277, "오후 3시 반 — 숏 셋이 실제로 팔린다",
              "시장 시계 01-12 15:30. pending 의도서가 due가 되고 <code>ExecutionHandler.fill</code>이 주문을 계획한다(<code>plan_orders</code>, 15.7 ms: 비중 → 수량, 정수 주). SIGNED 상장이라 음수 수량이 통과한다. 체결: K000003 +23 · K000008 +8 · K000009 +94, K000004 <b>−55</b> · K000005 <b>−19</b> · K000006 <b>−12</b> (close 가격, 학술 프로파일이라 수수료 0). 계좌 v1.",
              "<code>MarketClock.at</code>(#9270, 71.2 ms) → <code>accrue</code>(#9274) → <code>fill</code>(#9277, 48.3 ms) → <code>plan_orders</code>(#9364, 15.7 ms) → <code>AcademicExchange.execute</code>(#9744, 8.6 ms) → <code>requested_rows</code>(#9752) → <code>Account.append</code>(#9989) → <code>_fill_rows</code>(#10101) → <code>_publish_account_commit</code>(#10228).",
              fn="ExecutionHandler.fill()", code=("def", 12),
              mem={"account v1": "롱 3 · 숏 3 · cash ≈ 100.0M (달러 중립: 산 만큼 팔았다)"}),
            F("08_run_factor", 10261, "평가 → 판정 → 마감 — 규칙이 없어도 자리는 있다",
              "같은 시각에 이어서: 보유를 close로 평가하고(<code>mark</code>, 17.8 ms), compliance 규칙이 없으니 <code>observe</code>는 0.004 ms, <code>close</code>가 이 시각의 상태를 publish한다. 시장 시계 한 점은 늘 이 다섯 단계(발생 → 체결 → 평가 → 판정 → 마감)다 — 이 run엔 열 점.",
              "<code>ValuationHandler.mark</code>(#10261) → <code>mark_fill</code>(#10262) → <code>ValuationService.mark</code>(#10291) → <code>Account.mark</code>(#10371) → <code>publish_marked</code>(#10523) → <code>ComplianceHandler.observe</code>(#10569, 0.004 ms) → <code>ExecutionHandler.close</code>(#10570) → <code>publish_infallible</code>(#10585).",
              fn="ValuationHandler.mark()", code=("def", 10)),
            F("08_run_factor", 31142, "run이 끝나면 비중이 dataset이 된다 — 역시 같은 문",
              "10세션(계좌 v10, 주문 73 · 체결 54 · no_trade 19)이 끝나면 record를 굳히고(<code>_seal</code>, 표 3: account · fill · weight) <code>_publish_allocation</code>이 <code>vqapr.weight</code> 60행을 <code>sample-factor-weights</code>로 낸다: 각 행의 <code>available_at</code>은 그 결정의 시각(08:00). 이 파일도 <code>verify_source</code>를 지나 등록된다(digest <code>76a9b69b…</code>).",
              "<code>RunRecordWriter._seal</code>(#30924, 18.1 ms) → <code>_write_parquet</code> ×3 → <code>_publish_allocation</code>(#30978, 100.8 ms) → <code>RunOutput.register</code>(#31116) → <code>verify_source</code>(#31142, 70.3 ms) → <code>physical_digest</code>(#31244) → <code>register_dataset</code>(#31266) → <code>commit</code>(#31273) → <code>_write</code>(#31287) → <code>success</code>(#31611).",
              fn="_publish_allocation()", code=("def", 8),
              disk={".vqapr/runs/sample-factor-run/strategies/sample-factor@9bba20c4/": "strategy.json · tables/vqapr.{account,fill,weight}/all.parquet", ".vqapr/materialized/sample-factor-weights/all.parquet": "60행 (available_at 01-12 08:00 ~ 01-25 08:00 · instrument · weight ±0.1667)"}),
        ],
        "remember": [
            "다른 run이 만든 dataset을 읽는 선언은 벤더 표를 읽는 선언과 같은 한 줄이다.",
            "Rebalance.signed는 부호가 방향이다. 숏은 SIGNED 상장과 SIGNED 계좌가 있어야 체결된다.",
        ],
    },
    # ---------------------------------------------------------------- ⑤ stop-loss with memory
    {
        "id": "stop", "key": "⑤", "title": "stop-loss — memory",
        "sub": "register stoploss.yaml · 164 ms · 1,424 호출 — run sample-stoploss-run · 9,742 ms · 76,545 호출 · 37세션 · 이벤트 74",
        "story": (
            "<b>지금 하는 일:</b> <code>stoploss.py</code>의 <code>SampleStopLoss</code>는 첫 세션에 종가가 있는 모든 종목을 동일가중으로 사고 각 종목의 <b>진입 종가를 <code>self.memory</code>에 적는다</b>. 그 뒤 세션마다 최신 종가를 기억한 진입가와 견줘 3% 넘게 빠진 종목은 버리고 <code>stopped</code>에 날짜를 적는다. "
            "memory는 엄격한 JSON이고 매 decide 전에 복원되고 뒤에 publish된다 — 같은 run을 다시 돌리면 같은 손절이 같은 날 난다. 이 합성 패널은 잘 빠져서 8번 손절이 나고, 02-22엔 K000008 하나, 02-23에 전량 매도, 그 뒤는 현금."
        ),
        "frames": [
            F("10_run_stoploss", 13317, "decide 전 — memory {}가 전략에 복원된다",
              "2022-01-04 08:00, 첫 콜백. 프레임워크가 지금 root의 model memory(첫 세션이라 <code>{}</code>)와 payload(빈 바이트)를 전략 인스턴스에 넣는다. 전략은 하나의 인스턴스로 run 전체를 살지만, <b>믿을 것은 이 복원된 memory뿐</b>이다 — 다른 self 속성은 record가 재현하지 못한다.",
              "<code>StrategyPart.dispatch</code>(#13291, 68.5 ms) → <code>_visible_callback_state</code>(#13298) → <code>_restore_callback_state</code>(#13317: <code>strategy.memory = {}</code> · <code>load_payload(b'')</code>) → <code>_strategy_window</code> → <code>_callback_account_view</code> → <code>_account_history</code> → decide.",
              fn="_restore_callback_state()", code=at("src/vqapr/flow/run/callback.py", "def _restore_callback_state", 4),
              mem={"strategy.memory": "{}"}),
            F("10_run_stoploss", 13410, "첫 decide — 9종목에 진입하고 진입가 9개를 memory에 적는다",
              "최신 종가(01-03의 것)가 있는 종목은 9개(K000010은 아직 없다). <code>entered</code> 플래그가 없으니 <code>entry</code>에 9개의 종가를 적고 플래그를 세운다. 아무도 3%를 깨지 않았으니 9종목 동일가중 <code>Rebalance.of(long=…, invested='0.9')</code>. "
              "플래그를 따로 둔 이유: 나중에 <code>entry</code>가 비었을 때 \"처음\"으로 오해해 다시 사지 않기 위해서다(그렇게 쓴 첫 판은 02-24에 9종목을 다시 샀다).",
              "<code>SampleStopLoss.decide</code>(#13410, 21.4 ms) → <code>_DeclaredReads.read</code> → <code>panel_window</code>(#13431, 13.4 ms) → <code>matrix</code> → <code>Rebalance.of</code>(#13501, 6.0 ms).",
              fn="SampleStopLoss.decide() — 저자 코드", code=at(DECL + "stoploss.py", "entry: dict[str, float]", 12), author=True,
              mem={"self.memory": "{entry: {K000001: 145993.43, …, K000009: 170809.66}, stopped: {}, entered: true}"}),
            F("10_run_stoploss", 13892, "decide 후 — memory가 정규화되고 의도서와 함께 publish된다",
              "돌아온 memory를 <code>normalize_memory</code>가 엄격한 JSON으로 확인하고(Decimal · datetime · set이 있으면 여기서 거절), payload와 함께 model state ref를 만든다. 의도서(9종목 비중)에 도장을 찍고(<code>_stamp_intent</code>) 받아들인 뒤(<code>_accept_intent</code>) 계좌 · memory · pending을 <b>한 번</b>에 publish한다(root v1).",
              "<code>_stamp_intent</code>(#13618, 6.1 ms) → <code>_accept_intent</code>(#13796) → <code>_record_defaults</code> → <code>_candidate_callback_state</code>(#13892, 9.7 ms: <code>normalize_memory</code> · <code>save_payload</code> · <code>prepare_model_state</code>) → <code>_callback_evidence</code> → <code>_prepare_callback_publication</code> → <code>RunStateRepository.publish</code>(#14310, 4.1 ms).",
              fn="_candidate_callback_state()", code=at("src/vqapr/flow/run/callback.py", "def _candidate_callback_state", 10),
              mem={"root": "v1 (account v0 · memory entry 9 · pending 1)"}),
            F("10_run_stoploss", 16291, "둘째 날 — 복원된 memory로 첫 손절",
              "01-05 08:00. 복원된 memory(#16196)에 진입가 9개가 있다. 최신 종가(01-04)를 견주면 K000005가 −3.0%를 넘겼다 → <code>stopped['K000005'] = '2022-01-05'</code>, <code>entry</code>에서 지운다. 남은 8종목 동일가중. "
              "이어지는 세션들: 01-06 K000004 · 01-11 K000002 · K000006 · 01-19 K000007 · 01-24 K000001 · 01-25 K000009 · 01-26 K000003 → 02-22까지 K000008 하나(weight 표의 세션당 행 수 9 → 8 → 7 → 5 → 4 → 3 → 2 → 1).",
              "<code>StrategyPart.dispatch</code>(#16144, 75.5 ms) → <code>_restore_callback_state</code>(#16196) → <code>SampleStopLoss.decide</code>(#16291, 8.1 ms) → <code>Rebalance.of</code>(#16336) → <code>_candidate_callback_state</code>(#16703, 27.9 ms) → <code>publish</code>(#17121).",
              fn="SampleStopLoss.decide() — 손절", code=at(DECL + "stoploss.py", "for name, price in list(entry.items())", 6), author=True,
              mem={"self.memory": "{entry: 8, stopped: {K000005: '2022-01-05'}, entered: true}"}),
            F("10_run_stoploss", 71585, "마지막 이름이 깨지면 — 전량 매도는 Hold가 아니라 빈 Rebalance",
              "02-23 08:00. K000008이 02-22 종가로 −3%를 넘겼다. <code>entry</code>가 비었고 계좌엔 K000008 52주가 있다. <code>Hold</code>는 \"아무것도 하지 말라\"라 포지션이 그대로 남는다; 그래서 <code>Rebalance(target_weights={}, cash_weight=1)</code>을 돌려준다. 15:30에 <b>K000008 −52</b>가 체결되고 계좌는 현금 84,184,068.92뿐이다.",
              "<code>decide</code>(#71585, 3.0 ms) → <code>Rebalance.__init__</code>(#71634) → <code>_accept_intent</code>(#71766) → <code>publish</code>(#72208) · <code>MarketClock.at</code>(#72236) → <code>fill</code>(#72243, 21.4 ms) → <code>plan_orders</code>(#72282) → <code>execute</code>(#72365) → <code>Account.append</code>(#72420).",
              fn="SampleStopLoss.decide() — 마지막", code=at(DECL + "stoploss.py", "if any(quantity != 0", 5, before=3), author=True,
              mem={"self.memory": "{entry: {}, stopped: 9개, entered: true}", "account": "positions {} · cash 84,184,068.92"}),
            F("10_run_stoploss", 72950, "그 뒤 — Hold, pending 없음, 시장 시각은 평가만",
              "02-24 08:00부터 <code>entry</code>도 포지션도 없다 → <code>Hold</code>(\"every name has broken its stop; the book stays in cash\"). pending이 없으니 15:30의 <code>fill</code>은 <code>due=None</code>으로 0.005 ms에 지나가고 평가만 한다. run은 74 이벤트, 계좌 v34, 주문 111 · 체결 59 · no_trade 52로 끝나고 비중 dataset <code>sample-stoploss-weights</code>가 문을 지나 등록된다(#75918).",
              "<code>decide</code>(#72950, 2.6 ms) → Hold · <code>MarketClock.at</code>(#73452, 104 ms) → <code>fill</code>(#73459, 0.005 ms, due=None) … <code>_seal</code>(#75542) → <code>_publish_allocation</code>(#75670) → <code>RunOutput.register</code>(#75892) → <code>verify_source</code>(#75918, 93.9 ms) → <code>register_dataset</code>(#76042) → <code>success</code>(#76539).",
              fn="SampleStopLoss.decide() — Hold", code=at(DECL + "stoploss.py", "return va.Hold(", 1, before=0), author=True,
              disk={".vqapr/runs/sample-stoploss-run/strategies/sample-stoploss@bb45a6ab/": "strategy.json · tables 3 (weight 표 33세션분, 02-23부터 없음)", ".vqapr/materialized/sample-stoploss-weights/all.parquet": "등록됨"},
              tip="strategy.json에는 memory dict가 없다. 트레이스가 보이는 것은 매 콜백의 복원(#…_restore_callback_state) → 정규화(#…_candidate_callback_state) → publish이고, record에는 그 상태의 ref가 남는다."),
        ],
        "remember": [
            "memory는 decide 전에 복원되고 뒤에 정규화되어 publish된다. 첫 콜백엔 {}. JSON이 아닌 것은 여기서 거절된다.",
            "\"처음인가\"는 별도 플래그로 기억한다. 포지션을 다 비우려면 Hold가 아니라 빈 Rebalance를 돌려준다.",
        ],
    },
    # ---------------------------------------------------------------- ⑥ enhanced index
    {
        "id": "ei", "key": "⑥", "title": "enhanced index",
        "sub": "register enhanced.yaml · 109 ms · 1,315 호출 — run sample-enhanced-run · 2,534 ms · 34,410 호출 · 9세션 — list datasets 77 ms · show run 12 ms",
        "story": (
            "<b>지금 하는 일:</b> <code>enhanced.py</code>의 <code>SampleEnhancedIndex</code>는 ④가 저장한 <code>sample-factor-weights.weight</code>를 <b>alpha로 읽고</b>, 종가가 있는 종목의 동일가중(1/9)에 그 alpha의 절반을 더한 뒤 0 아래를 자른다 — 롱온리 enhanced index. "
            "run은 09:00에 결정한다(④의 08:00 비중이 알 수 있게 된 뒤). 마지막으로 <code>list datasets</code>와 <code>show run</code>으로 이 프로젝트에 무엇이 남았는지 읽는다: dataset 6개, 그중 4개가 run이 만든 것."
        ),
        "frames": [
            F("12_run_enhanced", 7625, "preflight — 저장된 alpha가 dataset으로 묶인다",
              "요구 둘: <code>sample-factor-weights</code>(source <code>materialized-sample-factor-weights</code>)와 <code>sample-prices</code>. 둘 다 <code>_validate_requirement</code> → <code>require_verified</code>(1.0 · 0.7 ms). run이 만든 표와 벤더 표가 여기서 같은 취급을 받는다는 것이 이 시나리오의 요점이다.",
              "<code>preflight_run</code>(#1040, 858.5 ms) → … <code>_freeze_sources</code>(#7624) → <code>_validate_requirement</code>(#7625) → <code>Workspace.require_verified</code>(#7626) → <code>require_verified</code>(#7634) · <code>_validate_requirement</code>(#7642) → <code>require_verified</code>(#7651).",
              fn="_validate_requirement()", code=("def", 14),
              mem={"frozen.source_digests": "{materialized-sample-factor-weights: 76a9b69b…, sample-prices-source: 18bb7017…}"}),
            F("12_run_enhanced", 8790, "9시 — 두 창을 읽고 벤치마크에 alpha를 얹는다",
              "2022-01-13 09:00. 종가 창(행 1)에서 종목 9개(K000010 없음) → 벤치마크 1/9 = 0.111. alpha 창(행 1: 01-13 08:00의 factor 비중 ±1/6)에서 K000003 · 8 · 9는 +0.0833, K000004 · 5 · 6은 −0.0833 → tilt: 0.194 · 0.028. <code>Rebalance.of(long=…, invested='1')</code>이 정규화한다(합 1). "
              "이 decide는 27.3 ms(두 표의 첫 읽기 11.8 · 6.9 ms), 다음 날은 9.7 ms.",
              "<code>StrategyPart.dispatch</code>(#8659, 72.4 ms) → <code>SampleEnhancedIndex.decide</code>(#8790, 27.3 ms) → <code>read</code>(#8791: prices) → <code>panel_window</code>(#8811) → <code>observation_table</code>(#8828) → <code>from_table</code>(#8866) → <code>matrix</code>(#8875) → <code>read</code>(#8880: alpha) → <code>panel_window</code>(#8901) → <code>matrix</code>(#8965) → <code>Rebalance.of</code>(#8970, 5.6 ms).",
              fn="SampleEnhancedIndex.decide() — 저자 코드", code=at(DECL + "enhanced.py", "tilted = {", 6, before=0), author=True,
              mem={"weights": "K000002 · K000003 · K000008 0.194 · K000004 · K000005 · K000009 0.028 · K000001 · K000006 · K000007 0.111"}),
            F("12_run_enhanced", 9909, "3시 반 — 롱온리 체결, 그리고 아홉 세션",
              "첫 체결은 67 ms(주문 9). 9세션 동안 이벤트 18, 주문 81 · 체결 41 · no_trade 40(비중이 거의 안 변하는 날은 주문이 0주로 계획된다), 계좌 v9. 끝나면 <code>sample-enhanced-weights</code>가 문을 지나 등록된다.",
              "<code>MarketClock.at</code>(#9902, 92.5 ms) → <code>fill</code>(#9909, 67.0 ms) → <code>select_snapshot</code>(#9923) … 다음 날 <code>decide</code>(#11829, 9.7 ms).",
              fn="ExecutionHandler.fill()", code=("def", 8)),
            F("13_list_datasets", 12, "list datasets — 여섯, 그중 넷은 run이 만들었다",
              "등록부를 열어(66 ms) dataset 목록을 낸다: <code>sample-prices</code> · <code>sample-execution</code>(벤더) · <code>sample-features</code>(produced_by <code>sample-features-run</code>, record <code>sample-features@20c2acad</code>) · <code>sample-factor-weights</code>(<code>sample-factor@9bba20c4</code>) · <code>sample-stoploss-weights</code>(<code>sample-stoploss@bb45a6ab</code>) · <code>sample-enhanced-weights</code>(<code>sample-enhanced@f174be27</code>). "
              "어느 run의 어느 코드 버전이 이 표를 썼는지가 이름 옆에 있다.",
              "<code>list_.run</code>(#11, 66.9 ms) → <code>Workspace.open</code>(#12, 66.1 ms) → <code>success</code>(stage workspace.list, count 6).",
              fn="Workspace.open()", code=("def", 8)),
            F("14_show_run_enhanced", 0, "show run — record만 읽는다, 32호출 12 ms",
              "<code>show run sample-enhanced-run</code>은 record(<code>run.json</code>)만 읽는다: 읽은 dataset 둘과 각각의 <code>source_digest</code>, 거래소 fingerprint, 집행 선언(close · 15:30 · Asia/Seoul), 초기 계좌, 기간 01-13 ~ 01-25, 기록 <code>sample-enhanced@f174be27</code>. 이 run이 어떤 바이트를 읽었는지가 record에 있으므로 나중에 파일이 바뀌어도 그때 무엇이었는지는 남는다.",
              "<code>main</code>(#0, 12 ms) → show 핸들러 → <code>run.json</code> 읽기 → <code>success</code>(stage run.show).",
              fn="main() → show run", code=at("src/vqapr/cli/main.py", "def main(", 8),
              disk={".vqapr/": "workspace.yaml · instruments.json · materialized/ 4 · runs/ 4"}),
        ],
        "remember": [
            "run이 저장한 비중은 dataset이다: 다음 run이 DatasetInput 한 줄로 읽고, preflight는 digest로 묶는다.",
            "list · show는 등록부와 record만 읽는다. record는 읽은 파일의 digest를 든다.",
        ],
    },
]

TABLE = {
    "title": "트레이스가 확인한 것 — 0.12.0이 바꾼 자리",
    "rows": [
        ["<b>물리 읽기의 문은 하나다</b> (기록 234)",
         "<code>verify_source</code>: 등록 #136 · #328 · 재등록 04 #451 · #643 · datamodel 출력 06 #12453 · 배분 출력 08 #31142 · 10 #75918 · 12(같은 자리). 그 밖의 읽기는 전부 <code>require_verified</code>: check 03 #42210 · preflight 06 #7425 · 08 #3637 · 12 #7634 · #7651",
         "스키마 · key · span · 값 · 집행 가격 · digest를 한 곳에서 한 번 잰다. 프레임워크가 쓴 표도 같은 문을 지난다"],
        ["<b>check는 표를 읽지 않는다</b>",
         "03: 바뀐 집행표의 거절이 <code>bound_execution_table</code> #42201 3.9 ms (0.11.0 페이지의 같은 자리 11,460 ms). 남은 3.6 s는 <code>derived_agenda</code> #362 1,782 ms + #44533 1,673 ms — 735세션 agenda를 judgments와 preflight가 <b>각각</b> 유도한다",
         "스캔 비용은 사라졌고, 이제 보이는 것은 같은 agenda의 두 번 유도다. 다음 이슈 후보"],
        ["<b>다시 등록하면 측정만 갈린다</b>",
         "04 #778 <code>_merge_dataset</code>: 선언된 반쪽이 같아 통과, digest 49e4b4ab… → bf30cb34…; 이후 run들의 <code>require_verified</code>가 그 digest를 대조해 통과",
         "거절문의 fix(\"register again\")가 되는 명령이다"],
        ["<b>창은 행렬이다</b> (기록 232 · 233)",
         "datamodel compute 첫 세션 349 ms(parquet 첫 읽기 #7960 337.7 ms) → 이후 1.8 ms · factor decide 12.8 → 7.4 ms · stop-loss decide 21.4 → 8.1 · 5.0 ms · enhanced decide 27.3 → 9.7 ms · <code>panel_window</code> 따뜻할 때 0.8~1.0 ms",
         "종목 for loop이 없다. 열 종목이 삼천 종목과 같은 식이다"],
        ["<b>루프는 하나다</b> (기록 231)",
         "<code>RunLoop.run</code>: datamodel 06 #7737(market None, handle ×16) · factor 08 #8181(handle ×20) · stop-loss 10 #12723(×74) · enhanced 12 #8483(×18). 조립은 <code>datamodel_loop</code> #7621 · <code>strategy_loop</code> #8099 · #12479",
         "무엇이 다른지는 Part와 시장 시계의 유무뿐이다"],
        ["<b>memory는 복원 → 정규화 → publish</b>",
         "10: <code>_restore_callback_state</code> #13317 → decide #13410 → <code>_candidate_callback_state</code> #13892(<code>normalize_memory</code>) → <code>publish</code> #14310; 매 콜백 같은 순서(#16196 → #16291 → #16703 → #17121)",
         "전략이 self에 둔 다른 것은 record가 재현하지 못한다. 첫 콜백은 {}"],
        ["<b>run이 만든 표는 다른 표와 같다</b>",
         "12 #7625 <code>_validate_requirement</code>(materialized-sample-factor-weights) · 13 list datasets: produced_by · produced_by_record 넷 · 14 show run: 읽은 dataset의 source_digest",
         "DataModel 출력도 전략 비중도 dataset이고, 다음 run은 벤더 표와 구별하지 않는다"],
        ["cold 읽기가 절대치를 지배한다",
         "등록의 명단 #46 417.7 ms · span #213 148.9 ms · datamodel 첫 compute #7922 349 ms · enhanced 첫 decide 27.3 ms(두 표 첫 읽기) · 두 번째부터 한 자릿수 ms",
         "판끼리 절대치를 비교하지 말 것. 구조의 값은 상대 비교에 있다"],
    ],
}
