# ruff: noqa: E501, RUF001 -- prose data: long lines and typographic characters are the content
# The 0.13.0 scenario stepper: the owner's six scenarios and a seventh for what 0.13.0 changed
# (`--jobs` bakes a cube per dataset once), every frame standing on a call the profiler recorded
# (traces: `README.md` beside this file; tools: `exp_230`, plus `trace_worker.py` here).
#
# Rendered by `exp_230/render.py`, which executes this file with `REPO` bound to the tree the traces
# were taken on. A frame names its trace and call index; the renderer fills in the definition line,
# the qualified name and the milliseconds from the trace, and reads the code window from the tree.
# A number that appears anywhere here appears in a trace, in a record the traced commands wrote, or
# in the output of `probe_panel.py` / `probe_cubes.py` (the panel's block shape and the cube files,
# measured on the same project).

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
    "title": "vqapr 0.13.0 시나리오 디버거",
    "storage_key": "vqapr-stepper-0130",
    "eyebrow": "vqapr 0.13.0 · develop (records 235–237) · 2026-09-10 · 실제 실행을 sys.setprofile로 추적한 결과",
    "h1": "vqapr 0.13.0 시나리오 디버거 — 사용자가 하는 일 여섯 가지 + 배치 하나, 프레임워크 안에서 한 프레임씩",
    "lede": (
        "<b>일곱 시나리오를 차례로 따라갑니다.</b> <code>vqapr new sample</code>이 만든 프로젝트(10종목, 2022-01-03 ~ 2024-12-30, 735세션)에서 "
        "① 데이터를 <b>등록</b>하고, ② 등록이 <b>거절</b>되는 두 경우(파일에 없는 컬럼 · 등록 뒤에 바뀐 파일)를 보고, ③ <b>DataModel</b>을 돌려 firm characteristic(5일 모멘텀)을 dataset으로 쓰고, "
        "④ 그것을 읽는 <b>factor 전략</b>(상위 3 롱 · 하위 3 숏)을 돌리고, ⑤ <b>memory</b>로 진입가를 기억하는 <b>stop-loss 전략</b>을 돌리고, ⑥ ④가 저장한 alpha 비중을 읽어 <b>enhanced index</b>를 만들고, "
        "⑦ ④와 ⑤를 <code>--jobs 2</code>로 <b>한 배치</b>에 돌립니다. 0.12.0 페이지와 같은 여섯 시나리오 위에서 0.13.0이 바꾼 두 자리가 보입니다: "
        "panel이 등록 span(735세션)이 아니라 <b>run의 horizon</b>만큼만 스캔되고(③~⑥, 기록 235), 배치는 dataset마다 cube를 <b>한 번 굽고</b> worker가 그것을 memory-map 합니다(⑦, 기록 236). "
        "프레임마다 위에는 <b>지금 무슨 일이 일어나는지</b>를 보통 말로 적었고, 아래 접힌 곳에 트레이스가 기록한 호출 순서를 두었습니다. "
        "모든 <code>#idx</code>(그 명령 안에서 몇 번째 호출인지)와 <code>ms</code>는 <code>sys.setprofile</code>이 실제로 기록한 값이고, 스니펫은 그 시점의 소스 줄입니다 — "
        "상상한 것은 없습니다(<code>experiments/exp_238_the_scenario_trace_0_13_0/</code>)."
    ),
    "facts": [
        {"k": "데이터", "v": "10 × 735", "s": "종목 × 세션(등록 span). run 구간은 2022년 1~2월: datamodel 16세션 · factor 10 · stop-loss 37 · enhanced 9"},
        {"k": "panel = horizon", "v": "17 · 11 · 38 · 10 행", "s": "run마다 실제로 든 (시각 × 종목) 블록: datamodel 17×10 · factor 11×10 · stop-loss 38×10 · enhanced 10×10 + 10×10. 0.12.0은 넷 다 735×10이었다(기록 235)"},
        {"k": "명령 16개", "v": "호출 32 … 90,168", "s": "register 973 · register(거절) 427 · check(거절) 90,168 · register(재측정) 1,294 · run datamodel 13,673 · factor 31,759 · stop-loss 77,553 · enhanced 35,341 · list 1,081 · show 32 · <code>--jobs 2</code> 배치(driver) 3,659 · worker 27,442"},
        {"k": "cube 한 번", "v": "735 × 10 · 58,928 B", "s": "배치가 <code>sample-prices.close</code>를 전 종목 × 등록 span으로 한 번 굽고(128 ms), worker는 <code>panel_from_cube</code>로 map 한다 — worker 트레이스에 <code>observation_table</code>이 없다. 배치가 끝나면 디렉터리는 없다(기록 236)"},
        {"k": "factor run", "v": "롱 3 · 숏 3", "s": "10세션 · 주문 73 · 체결 54 · 첫날 K000003 +23 · K000008 +8 · K000009 +94 · K000004 −55 · K000005 −19 · K000006 −12 · 비중 dataset 60행"},
        {"k": "stop-loss run", "v": "9 → 0", "s": "37세션 · 첫날 9종목 진입, 3% 손절이 이어져 02-22엔 K000008 하나, 02-23에 전량 매도 → 현금 84,184,068.92 · memory에 entry 9 → 0"},
        {"k": "enhanced run", "v": "0.111 ± 0.083", "s": "동일가중 1/9 에 factor 비중의 절반을 더한다: K000002·3·8 0.194 · K000004·5·9 0.028 · 나머지 0.111 (롱온리, 합 1)"},
    ],
    "fix": (
        "<strong>시간 읽는 법.</strong> ms는 프로파일러가 켜진 채 잰 값이라 절대치는 실제보다 큽니다. 같은 트레이스 안에서 <b>서로 비교</b>만 하십시오. "
        "이 판의 프로젝트는 네트워크 홈 디렉터리(CIFS) 위에 있어 프로세스의 <b>첫</b> parquet 읽기가 유난히 큽니다(등록의 명단 읽기 14,246 ms, datamodel의 첫 compute 1,395 ms — 그중 numpy 블록을 처음 만드는 <code>placement</code> 800 ms). 같은 질문을 두 번째 물을 땐 한 자릿수 ms입니다. "
        "구조의 값은 상대 비교에 있습니다: ⑦의 worker는 같은 첫 decide를 <b>스캔 없이</b> 73 ms에 끝냅니다."
    ),
    "glossary_title": "이 페이지에 나오는 낱말 — 먼저 읽어 두면 편합니다",
    "glossary": [
        ("선언 (declaration)", "당신이 쓰는 YAML. \"이 parquet은 가격이다, 이 파일은 내 전략이다, 이 run은 이렇게 돌려라\"."),
        ("등록부 (workspace)", "<code>.vqapr/workspace.yaml</code>. <code>register</code>가 쓰고, 모든 명령이 맨 처음 펼쳐 읽는다. 코드에선 <code>Workspace</code>."),
        ("문 (validation door)", "<code>data/validation.py</code>. 물리 파일은 등록될 때 <b>여기서 한 번</b> 잰다(스키마 · key · span · 값 · 집행 가격 · digest). 이후의 모든 읽기는 파일 <i>내용</i>이 아니라 <i>digest</i>를 대조한다(<code>require_verified</code>). 기록 234."),
        ("digest · 측정된 반쪽", "파일 바이트의 sha256. 등록의 선언된 반쪽(컬럼 · key · grain)은 사용자의 것, 측정된 반쪽(span · digest · 집행 가격)은 문의 것. 파일이 바뀌면 같은 선언으로 다시 등록해 측정만 갈아 끼운다."),
        ("검사·판정 (check · judgment)", "\"이 run을 돌려도 되나\"에 대한 예/아니오 하나하나. <code>check</code>는 모아서 답하고, <code>run</code>은 첫 거절에서 멈춘다."),
        ("얼리기 (freeze → FrozenRun)", "등록부에 적힌 <i>이름</i>들을 <i>실제 값</i>(코드 fingerprint, parquet 경로와 digest, 결정 시각들, 초기 계좌)으로 풀어 묶은 불변 스냅샷. 이 뒤로 등록부가 바뀌어도 run은 이것만 본다."),
        ("horizon (run의 지평)", "<code>[start, end]</code>. 0.13.0부터 store가 이것을 들고, panel은 \"start에서 가장 이른 lookback 하한 ~ end\"만 스캔한다(<code>_scan_bounds</code>). 1년 run은 10년 원천에서 1년 + lookback만 든다. 기록 235."),
        ("창 (window) · matrix() · 블록", "한 alias의 한 필드를 <i>시각 × 종목</i>으로 본 것. panel은 숫자 필드마다 float64 행렬 <b>한 벌</b>(블록)을 들고, <code>window.matrix()</code>는 그 행렬의 <b>view</b>(복사 없음, 마지막 행이 최신, 없는 값은 NaN)다. 기록 232 · 235."),
        ("cube", "<code>--jobs</code> 배치가 dataset마다 굽는 디렉터리: 숫자 필드마다 <code>.npy</code> 하나(전 종목 × 등록 span) + <code>instants.npy</code> + <code>instruments.json</code> + <code>present.npy</code> + <code>cube.json</code>(원천 digest). worker는 <code>np.load(mmap_mode='r')</code>로 map 하고, 배치가 끝나면 디렉터리는 지워진다. 기록 236."),
        ("전략 시계 · 시장 시계", "agenda가 만드는 결정 시각(매일 08:00 또는 09:00)과 집행표에 행이 있는 시각(매일 15:30). 결정은 앞에서, 체결·평가·판정은 뒤에서만."),
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
    ("③", "DataModel", "horizon panel → dataset"),
    ("④", "factor 전략", "롱 3 · 숏 3 · 비중 저장"),
    ("⑤", "stop-loss", "memory가 진입가를 든다"),
    ("⑥", "enhanced index", "저장된 alpha를 읽는다"),
    ("⑦", "--jobs 배치", "cube 한 번 · worker는 map"),
]

SCENES = [
    # ---------------------------------------------------------------- ① register
    {
        "id": "reg", "key": "①", "title": "데이터 등록",
        "sub": "vqapr register sample.yaml · 15,060 ms · 973 호출 (그중 14,246 ms는 이 세션의 첫 parquet 읽기)",
        "story": (
            "<b>지금 하는 일:</b> 당신이 <code>sample.yaml</code>을 건넨다. 거기엔 종목 명단, 가격 parquet(<code>sample-prices</code>), 집행표 parquet(<code>sample-execution</code>), 전략 코드, 거래소 코드, run 하나가 적혀 있다. "
            "vqapr은 이 문서를 그대로 믿지 않는다 — parquet을 <b>한 문에서 실제로 열어</b> 선언과 맞는지 재고 digest를 남기고, 전략과 거래소 코드를 <b>실제로 import</b>해 계약대로인지 본 뒤, "
            "그제야 등록부(<code>.vqapr/workspace.yaml</code>) 한 파일을 쓴다. 이 페이지의 다른 여섯 시나리오는 전부 이 등록부 위에서 일어난다. 0.12.0과 같은 973 호출, 같은 순서다 — 0.13.0은 등록을 바꾸지 않았다."
        ),
        "frames": [
            F("01_register", 0, "명령줄이 register 핸들러를 고른다",
              "<code>vqapr --project-root sample register sample.yaml</code>. argparse가 verb를 고르고 프로젝트 루트를 정한 뒤 핸들러를 부른다. 15,060 ms의 거의 전부(15,040.8 ms)는 핸들러 안에서 보낸다. 무엇이 잘못되든 결과는 같은 모양의 JSON 봉투다.",
              "<code>build_parser</code>(#1, 5.9 ms) → <code>_resolve_project_root</code>(#10) → <code>register.run</code>(#11, 15,040.8 ms) → <code>read_yaml_mapping</code>(#12, 22.3 ms) → <code>apply</code>(#13, 15,018.3 ms).",
              fn="main() → register.run()", code=at("src/vqapr/cli/main.py", "def main(", 14),
              mem={"argv": "['--project-root', '.../sample', 'register', '.../sample/sample.yaml']"}, disk={".vqapr/": "없음"}),
            F("01_register", 14, "트랜잭션을 열고, 섹션을 정해진 순서로 처리한다",
              "모르는 섹션 이름이 있으면 여기서 이름을 대며 거절한다(#25). 그 다음 <b>트랜잭션</b>을 연다 — 등록부의 스냅샷 위에 하나씩 올려 두었다가 맨 끝에 한 번에 쓰는 장치. 디스크는 아직 그대로다. "
              "처리 순서는 instruments → datasets → components → runs: 뒤의 것이 앞의 것을 이름으로 가리키기 때문이다(run은 전략 id와 dataset id를 든다).",
              "<code>Workspace.transaction</code>(#15, 1.5 ms) → <code>_require_declared_ids</code>(#25) → <code>_instruments</code>(#43, 14,268.6 ms) → datasets(#136 · #328) → components(#468 · #614) → runs(#877) → <code>commit</code>(#902).",
              fn="_apply() — 섹션 순서", code=at("src/vqapr/project/registration.py", 'for dataset_id, body in section("datasets")', 7),
              mem={"document": "dict (instruments 1, datasets 2, components 2, runs 1)", "transaction.staged": "[]"}),
            F("01_register", 46, "종목 명단도 같은 문을 지난다 — verify_roster",
              "명단 parquet(<code>instruments_stock.parquet</code>)은 문의 <code>verify_roster</code>가 연다. 없는 파일이나 컬럼이 빠진 표는 raise가 아니라 <b>Diagnosis</b>(<code>roster.table_missing</code> · <code>roster.table_invalid</code>)로 돌아와 다른 거절 옆에 놓인다. "
              "이 프로세스 — 이 세션 — 에서 parquet을 처음 여는 호출이라 14,246.3 ms(프로젝트가 CIFS 네트워크 홈 위에 있다). 0.12.0 판에선 같은 자리가 418 ms였고, 뒤의 읽기들은 이 판에서도 수십~수백 ms다. 10종목이 <code>InstrumentRoster</code>가 되고 트랜잭션에 올라간다.",
              "<code>verify_roster</code>(#46, 14,246.3 ms) → <code>Diagnosis.ok</code>(#49) → <code>build_roster</code>(#50, 1.4 ms: <code>instrument</code> ×10) → <code>Transaction.register_instruments</code>(#83).",
              fn="verify_roster()", code=at("src/vqapr/data/validation.py", "def verify_roster", 12),
              mem={"transaction.staged": "[instruments: stock 10, digest 875b5fe1…]"}),
            F("01_register", 136, "가격 parquet을 열어 여섯 가지를 잰다 — verify_source",
              "선언은 \"<code>available_at</code>이 시각이고 <code>close</code>가 DOUBLE이고 (시각, 종목)이 유일하다\"고 말한다. 문은 믿지 않고 파일을 열어 순서대로 묻는다: "
              "<b>스키마</b>(선언한 컬럼이 다 있고 타입이 맞나, 23.9 ms) → <b>key</b>(null · 중복, 149.1 ms) → <b>span</b>(첫 시각과 끝 시각, 107.2 ms) → <b>값</b>(DOUBLE에 NaN · Inf가 없나, 37.7 ms) → <b>집행 가격</b>(이 표엔 execution 역할이 없어 0.003 ms) → <b>digest</b>(바이트의 sha256, 4.1 ms). "
              "돌아오는 등록은 span과 <code>source_digest</code>를 든다. 여기가 이 파일이 <b>내용으로</b> 검사되는 유일한 자리다 — 뒤의 모든 명령은 digest만 대조한다.",
              "<code>verify_source</code>(#136, 349.7 ms) → <code>describe</code>(#137, 26.5 ms) → <code>check_schema</code>(#149) → <code>check_key</code>(#192) → <code>check_span</code>(#213) → <code>check_values</code>(#224) → <code>check_execution_prices</code>(#276) → <code>physical_digest</code>(#278) → <code>with_verification</code>(#280) → <code>Transaction.register_dataset</code>(#282) → <code>spoken</code>(#288).",
              fn="verify_source() — 여섯 단계", code=at("src/vqapr/data/validation.py", "def verify_source", 14),
              mem={"measured.span": "2022-01-03 15:30 ~ 2024-12-30 15:30 +09:00", "measured.source_digest": "18bb7017…"}),
            F("01_register", 436, "집행표는 한 가지를 더 잰다 — 어느 가격이 거래 가능한 행마다 양수인가",
              "<code>sample-execution</code>은 <code>execution: {is_tradable}</code> 역할을 선언했다. 같은 다섯 단계 뒤에 문은 <b>후보 가격 전부</b>에 대해 \"tradable인 행마다 유한하고 양수인가\"를 한 번에 묻고(29.6 ms) 답을 <code>execution_prices</code>로 등록에 남긴다 — 여기선 <code>['close']</code>. "
              "run이 나중에 <code>trade_price: close</code>를 고르면 preflight는 이 튜플을 조회할 뿐 표를 다시 스캔하지 않는다.",
              "<code>verify_source</code>(#328, 174.2 ms) → <code>check_schema</code>(#338, 24.2 ms) → <code>check_key</code>(#370, 31.8 ms) → <code>check_span</code>(#391, 25.2 ms) → <code>check_values</code>(#402, 31.0 ms) → <b><code>check_execution_prices</code>(#436, 29.6 ms)</b> → <code>physical_digest</code>(#453, 4.1 ms) → <code>register_dataset</code>(#459).",
              fn="check_execution_prices()", code=at("src/vqapr/data/validation.py", "def check_execution_prices", 14),
              mem={"measured.execution_prices": "('close',)", "measured.source_digest": "49e4b4ab…"}),
            F("01_register", 552, "전략과 거래소 코드는 실제로 import해서 계약을 본다",
              "<code>reversal_5d.py</code>를 fingerprint(바이트의 해시, #472)하고 import해 <code>StrategyModel</code>의 메서드 시그니처가 맞는지 본다(<code>conformance</code>, 47.6 ms). 거래소(<code>exchange.py</code>)도 같은 길(#614~#812). "
              "옛 시그니처로 쓴 규칙이 여기서 거절되는 것을 0.11.0 페이지가 보였다; 오늘은 둘 다 통과해 트랜잭션에 오른다.",
              "<code>_component</code>(#468, 63.7 ms) → <code>prepare_component</code>(#471) → <code>fingerprint_component</code>(#472, 5.7 ms) → <code>conformance</code>(#552) → <code>_check_methods</code>(#599) → <code>register_component</code>(#608) · 거래소 <code>_component</code>(#614, 55.2 ms) → <code>conformance</code>(#722, 36.7 ms) → <code>register_component</code>(#812).",
              fn="conformance()", code=("def", 10),
              mem={"transaction.staged": "[instruments, sample-prices, sample-execution, sample-reversal-5d, sample-exchange]"}),
            F("01_register", 902, "run을 올리고, 한 번에 쓴다",
              "run <code>sample-run</code>이 전략 id · dataset id · 거래소 id로 앞의 것들을 가리키고(#877), 사람 말로 푼 문장(<code>spoken</code>, #889)이 봉투에 들어간다: \"<i>dataset 'sample-prices': a row is knowable at its 'available_at' value and never earlier</i>\", \"<i>run 'sample-run' fills against dataset 'sample-execution': the first execution instant after the decision, at 15:30:00 Asia/Seoul, at its 'close' price</i>\". "
              "<code>commit</code>이 lock을 잡고 등록부를 한 번 읽고 올려 둔 것을 순서대로 합친 뒤 <b>한 번</b> 쓴다(48.1 ms). 디스크에 처음으로 <code>.vqapr/workspace.yaml</code>이 생기고, 두 dataset 항목엔 <code>source_digest</code>가, 집행표엔 <code>execution_prices: [close]</code>가 적힌다.",
              "<code>register_run</code>(#877) → <code>_merge_run</code>(#881) → <code>RunDefinition.spoken</code>(#889) → <code>Transaction.commit</code>(#902, 67.1 ms) → <code>_merge_dataset</code> ×2(#909 · #911) → <code>_merge_component</code> ×2(#913 · #915) → <code>Workspace._write</code>(#924, 48.1 ms) → <code>_write_roster</code>(#963) → <code>success</code>(#967).",
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
        "sub": "register bad.yaml · 96 ms · 427 호출 (거절) — check sample-run · 4,271 ms · 90,168 호출 (거절) — register sample.yaml 다시 · 1,175 ms · 1,294 호출",
        "story": (
            "<b>지금 하는 일:</b> 두 가지 실수를 저지른다. 먼저 <code>bad.yaml</code>로 파일에 <b>없는 컬럼</b>(<code>adj_close</code>)을 선언한 dataset을 등록한다 — 문이 파일을 열어 보고 이름을 대며 거절하고, 등록부는 한 바이트도 바뀌지 않는다. "
            "다음엔 등록이 끝난 뒤 <code>execution.parquet</code>을 <b>다른 바이트로 덮어쓴다</b>(마지막 날을 뺀 유효한 파일). <code>check sample-run</code>은 표를 다시 스캔하지 않고 digest 하나를 대조해 <code>dataset.source_changed</code>로 막고, 고치는 법을 말한다: 같은 선언으로 다시 등록하라. 그렇게 하면 측정된 반쪽만 갈린다. "
            "이 판의 <code>check</code>는 기록 237(집행 순서 판정이 run 안의 occurrence만 묻는다; 트레이스를 뜬 작업 트리에 있었고 아직 커밋 전이었다)을 지나므로 0.12.0 판보다 호출이 3,669개 많다 — <code>inclusive_slice</code> 한 번이다."
        ),
        "frames": [
            F("02_register_bad", 396, "문이 파일을 열어 선언과 대조한다 — 첫 단계에서 멈춘다",
              "<code>sample-adjusted</code>는 <code>observations.parquet</code>에 <code>adj_close</code> 컬럼이 있다고 말한다. <code>verify_source</code>가 파일의 스키마를 읽고(<code>describe</code>, 22.8 ms) <code>check_schema</code>가 선언과 맞춘다: 없다. 이 뒤의 단계(key · span · 값 · digest)는 돌지 않는다 — 스키마가 틀린 파일에 key를 묻는 것은 뜻이 없다.",
              "<code>verify_source</code>(#383, 26.7 ms) → <code>describe</code>(#384, 22.8 ms) → <code>check_schema</code>(#396, 3.7 ms) → <code>Diagnosis.ok</code>(#411) = False → <code>raise_if_failed</code>(#412).",
              fn="check_schema()", code=at("src/vqapr/data/validation.py", "def check_schema", 12),
              mem={"observed": "available_at, close, high, instrument, low, open, volume"}),
            F("02_register_bad", 417, "거절은 이름 · 관찰 · 고치는 법을 든 봉투다 — 그리고 등록부는 그대로다",
              "봉투 한 장: <code>dataset.field_missing</code> (400) · requirement \"<i>fields[adj_close] declares column 'adj_close', which must exist</i>\" · observed \"<i>available_at, close, high, instrument, low, open, volume</i>\" · fix \"<i>add column 'adj_close' to the prepared source, or point fields[adj_close] at a column it already has</i>\" · source <code>datasets.sample-adjusted.fields[adj_close]</code> · cause <code>data/validation.py:153 (check_schema)</code>. "
              "<code>mutation: false</code> — 트랜잭션은 열렸지만 commit되지 않았다. exit 1.",
              "<code>raise_if_failed</code>(#412) → <code>envelope.failure</code>(#417, stage register) → exit 1.",
              fn="envelope.failure()", code=("def", 10),
              disk={".vqapr/workspace.yaml": "바뀌지 않음 (mutation: false)"}),
            F("03_check_changed", 336, "파일이 바뀐 뒤의 check — 판정 하나하나가 답한다",
              "<code>execution.parquet</code>이 다른 바이트가 된 채로 <code>check sample-run</code>. <code>check</code>는 등록부를 열고(#14, 36 ms) 판정들을 <b>모아서</b> 묻는다: 종목 집합(#349) · 명단(#351, 17.4 ms) · 기간(#358) · <b>집행 순서</b>(#360) · 멤버의 dataset(#45907) · 비중(#48189) · 출력(#48191). "
              "집행 순서 판정은 먼저 agenda를 유도한다 — 3년짜리 run이라 734세션(마지막 날을 뺀 집행표), 2,019.5 ms — 그리고 기록 237대로 <code>[start, end]</code>로 자른 뒤(<code>inclusive_slice</code>, 180.9 ms) 집행표를 묶는다.",
              "<code>check</code>(#12, 4,255.6 ms) → <code>Workspace.open</code>(#14) → <code>judgments</code>(#336, 2,355.6 ms) → <code>_judge_execution_ordering</code>(#360, 2,209.6 ms) → <code>derived_agenda</code>(#362, 2,019.5 ms) → <code>inclusive_slice</code>(#42201, 180.9 ms) → <code>bound_execution_table</code>(#45870).",
              fn="judgments()", code=("def", 10),
              tip="이 트레이스에서 큰 것은 표 스캔이 아니라 agenda 유도다 — 그리고 preflight가 같은 agenda를 한 번 더 유도한다(#48202, 1,838.8 ms). 4.3 s 중 3.9 s가 그것이다. 0.12.0 판에서 발견해 보고서로 남긴 것이고 아직 열려 있다."),
            F("03_check_changed", 360, "집행 순서 판정은 run이 걷는 것과 같은 조각을 묻는다 (기록 237)",
              "0.12.0까지 이 판정은 <code>derived_agenda</code>가 돌려준 <b>날짜 상위집합</b>을 그대로 순회했다. end가 마지막 체결과 마지막 결정 사이(예: 16:00)에 놓인 옳은 선언에서 end 뒤의 occurrence가 <code>select_target</code>에 들어가 <code>ValueError</code>로 죽었고, 답하지 못한 판정은 500 <code>judgment.blocked</code>가 됐다(testbed 보고 099). "
              "이제 판정은 preflight가 얼리는 것과 같은 <code>inclusive_slice(start, end)</code>를 순회한다. 이 sample-run의 end는 23:59:59라 잘리는 것은 없지만, 자리 자체가 트레이스에 보인다.",
              "<code>_judge_execution_ordering</code>(#360) → <code>once</code>(#361) → <code>derived_agenda</code>(#362) → … → <code>OperationAgenda.inclusive_slice</code>(#42201, 180.9 ms) → <code>bound_execution_table</code>(#45870, 9.0 ms).",
              fn="_judge_execution_ordering() — inclusive_slice", code=at("src/vqapr/flow/declaration/judgments.py", "inclusive_slice(", 12, before=3)),
            F("03_check_changed", 45879, "표를 다시 스캔하지 않는다 — digest 하나를 대조한다",
              "<code>bound_execution_table</code>은 등록부에 <code>require_verified('sample-execution')</code>을 묻는다. 등록이 든 digest <code>49e4b4abef4f…</code>와 지금 파일의 sha256 <code>34c1d63c3ab4…</code>(4.8 ms)가 다르다 → <code>dataset.source_changed</code> (412, stage freeze): "
              "\"<i>the bytes a run reads must be the bytes registration measured; every fact the registration carries (span, key, prices) was measured on them</i>\", fix \"<i>register dataset 'sample-execution' again so its facts are measured on the file as it is now</i>\".",
              "<code>bound_execution_table</code>(#45870, 9.0 ms) → <code>Workspace.require_verified</code>(#45871) → <code>require_verified</code>(#45879, 8.5 ms) → <code>physical_digest</code>(#45880, 4.8 ms) → <code>Failure.bounded</code>(#45882) · 판정을 blocked로 감싸는 <code>Failure.bounded</code>(#45898).",
              fn="require_verified()", code=at("src/vqapr/data/validation.py", "def require_verified", 14),
              mem={"registered": "49e4b4abef4f…", "file now": "34c1d63c3ab4…"},
              caution="판정 하나가 답하지 못하면 봉투는 그것을 <code>blocked</code>(judgment.blocked, cause에 예외 전체)에 두고, 원인 거절은 <code>failures</code>에 둔다. checked 4 · passed [workspace, run] · failures [dataset.source_changed]. 실패한 대조는 memo되지 않아 preflight가 한 번 더 해시한다(#90143, 2.9 ms)."),
            F("04_register_again", 643, "같은 선언으로 다시 등록한다 — 측정만 다시 한다",
              "<code>register sample.yaml</code>을 다시. 선언은 한 글자도 바뀌지 않았고 파일만 다르다. 문이 두 표를 다시 잰다(가격표 337 ms · 집행표 146 ms): span, digest(<code>34c1d63c…</code>), 집행 가격. 트랜잭션에 올라갈 때 <code>_merge_dataset</code>이 기존 등록과 비교한다.",
              "<code>verify_source</code>(#451, 337.2 ms) → <code>physical_digest</code>(#593) → <code>register_dataset</code>(#597) → <code>_merge_dataset</code>(#601) · <code>verify_source</code>(#643, 145.9 ms) → <code>physical_digest</code>(#768) → <code>register_dataset</code>(#774) → <code>_merge_dataset</code>(#778).",
              fn="verify_source() 다시", code=("def", 8)),
            F("04_register_again", 778, "선언된 반쪽이 같으면 측정된 반쪽을 갈아 끼운다",
              "<code>_merge_dataset</code>은 기존 등록의 span · aggregated · digest · 집행 가격을 새 측정으로 바꾼 사본이 새 등록과 <b>같은지</b> 본다. 같다 → 선언은 그대로이고 측정만 바뀐 것이니 받아들인다. 컬럼 이름 하나라도 달랐다면 <code>dataset.registered</code>(409)로 거절했을 것이다. "
              "commit이 등록부를 다시 쓴다(#1245, 37.1 ms). 이 페이지의 run들은 원본 바이트로 되돌린 뒤 한 번 더 등록한 상태(digest <code>49e4b4ab…</code>)에서 돌았다.",
              "<code>_merge_dataset</code>(#778) → … <code>Transaction.commit</code>(#1217, 51.9 ms) → <code>_merge_dataset</code> ×2(#1230 · #1232: 재생) → <code>Workspace._write</code>(#1245).",
              fn="_merge_dataset() — remeasured", code=at("src/vqapr/project/merge.py", "remeasured = replace(", 12, before=6),
              disk={".vqapr/workspace.yaml": "sample-execution.source_digest: 49e4b4ab… → 34c1d63c… (그 뒤 원본으로 되돌려 한 번 더 등록)"}),
        ],
        "remember": [
            "등록이 거절되면 봉투가 code · requirement · observed · fix · source를 들고, 등록부는 바뀌지 않는다.",
            "등록 뒤에 파일이 바뀌면 읽는 쪽이 digest 하나로 알아채고, 고치는 법은 같은 선언으로 다시 등록하는 것이다.",
        ],
    },
    # ---------------------------------------------------------------- ③ datamodel
    {
        "id": "dm", "key": "③", "title": "DataModel → firm characteristic",
        "sub": "register features.yaml · 168 ms · 647 호출 — run sample-features-run · 2,772 ms · 13,673 호출 · 16세션 · 108행",
        "story": (
            "<b>지금 하는 일:</b> <code>features.py</code>의 <code>SampleFeatures</code>는 세션마다 종목별 <b>5일 모멘텀</b>(여섯 종가 중 마지막 ÷ 첫 번째 − 1)을 돌려주는 DataModel이다. run은 전략 시계만 돈다(매일 16:00, 시장 시계 없음). "
            "첫 네 세션은 창이 덜 차서 빈 목록, 2022-01-10부터 종가 여섯 개가 다 있는 종목당 한 행(K000010은 이 구간에 여섯 종가가 없어 행이 없다). run이 끝나면 108행(12세션 × 9종목)이 <code>.vqapr/materialized/sample-features/all.parquet</code>이 되고 <b>①과 같은 문</b>을 지나 dataset <code>sample-features</code>로 등록된다. "
            "<b>0.13.0에서 바뀐 자리:</b> store가 run의 horizon을 들고, panel은 등록 span 735세션이 아니라 <b>17행</b>(01-03 ~ 01-25, 여섯 행 lookback 포함)만 든다."
        ),
        "frames": [
            F("06_run_features", 7425, "얼리기 — 읽을 dataset의 identity를 대조한다",
              "run을 돌리기 전에 preflight가 판정을 다시 하고(#3898) 등록부의 이름들을 값으로 얼린다. 이 모델이 읽는 <code>sample-prices</code>는 <code>require_verified</code> 한 번(3.1 ms, 그중 sha256 3.0 ms): 등록의 digest와 파일이 같다. FrozenRun에 그 digest가 들어간다(<code>source_digests</code>).",
              "<code>preflight_run</code>(#470, 462.4 ms) → <code>preflight_run</code>(#3898, 190.5 ms) → <code>_freeze_datamodel</code>(#7185) → <code>_freeze_agenda</code>(#7228) → <code>_freeze_sources</code>(#7415, 3.9 ms) → <code>Workspace.require_verified</code>(#7417) → <code>require_verified</code>(#7425) → <code>physical_digest</code>(#7426) → <code>freeze_run_record</code>(#7475, 24.0 ms).",
              fn="require_verified()", code=at("src/vqapr/data/validation.py", "def require_verified", 14),
              mem={"frozen.source_digests": "{sample-prices-source: 18bb7017…}"}),
            F("06_run_features", 7603, "store가 run의 horizon을 든다 (기록 235)",
              "<code>_run_member</code>가 멤버 하나의 자원(스캔 세션 · store · writer · 창)을 만든다. 0.13.0의 store는 두 가지를 더 받는다: <code>horizon=(start, end)</code> — 얼린 run의 기간 — 와 run이 선언한 <code>requirements</code> 전부. 뒤의 모든 panel 스캔은 이 둘로 잘린다. "
              "단일 run이라 <code>cubes=None</code>: 스캔 경로 그대로(⑦에서 달라진다).",
              "<code>_run_member</code>(#7600, 2,150.8 ms, member_kind='datamodel') → <code>_horizon</code>(#7603) → <code>DuckDbObservationStore.__init__</code>(#7604) → <code>datamodel_loop</code>(#7622).",
              fn="_horizon() → DuckDbObservationStore(horizon=…)", code=at("src/vqapr/flow/orchestration.py", "horizon=_horizon(frozen)", 10, before=4),
              mem={"horizon": "(2022-01-04 00:00, 2022-01-25 23:00) +09:00", "requirements": "[sample-prices.close, RowsLookback(rows=6)]"}),
            F("06_run_features", 7622, "같은 RunLoop, 시장 시계 없이",
              "<code>datamodel_loop</code>가 <code>RunLoop(part=DataModelPart, market=None)</code>을 조립한다. 전략 run과 같은 클래스 — 다른 것은 Part와 시장 시계뿐이다(기록 231). 조립하면서 저자의 <code>inputs()</code>를 한 번 불러(#7624) 무엇을 읽을지 안다.",
              "<code>datamodel_loop</code>(#7622, 5.0 ms) → <code>ComputeHandler.__init__</code>(#7623) → <code>SampleFeatures.inputs</code>(#7624, author) → <code>RunLoop.run</code>(#7738, 1,642.7 ms) → <code>RunOutput.open</code>(#7741) → <code>RunLoop.handle</code> ×16.",
              fn="datamodel_loop()", code=at("src/vqapr/flow/run/loop.py", "def datamodel_loop", 12)),
            F("06_run_features", 7959, "첫 창 — 스캔 범위는 등록 span이 아니라 horizon + lookback",
              "2022-01-04 16:00, 첫 <code>context.read('prices', 'close')</code>. store는 panel을 만들기 전에 <b>어디까지 읽을지</b>를 정한다: run의 start(01-04)에서 <code>RowsLookback(rows=6)</code>이 닿는 가장 이른 시각을 원천의 시각 격자에서 센다(<code>_grid_bound</code>, 격자 읽기 63.0 ms — 이 세션에 처음). 격자에 01-04 앞 행은 01-03 15:30 하나뿐이라 하한은 그것이고, 상한은 end(01-25 23:00). "
              "0.12.0은 여기서 등록 span 전체(2022-01-03 ~ 2024-12-30)를 답했다.",
              "<code>panel_window</code>(#7944, 1,394.1 ms) → <code>_digest</code>(#7956, 2.8 ms) → <code>_scan_bounds</code>(#7959, 63.1 ms) → <code>_grid_bound</code>(#7960, rows=6) → <code>ScanSession.instant_grid</code>(#7962, 63.0 ms) → <code>panel_identity</code>(#8704) → <code>observation_table</code>(#8707, 500.4 ms).",
              fn="_scan_bounds() — lookback 하한", code=at("src/vqapr/data/store.py", "for lookback in lookbacks:", 10, before=2),
              mem={"bounds": "2022-01-03 15:30 ~ 2022-01-25 23:00 +09:00 (probe_panel.py로 잰 값)"}),
            F("06_run_features", 8744, "panel은 숫자 필드마다 float64 블록 한 벌 — 17 × 10",
              "스캔이 돌려준 Arrow 표(available_at · instrument · close)를 <code>placement</code>가 (시각, 종목) 정수 쌍으로 배치하고 <code>dense_block</code>이 (17 × 10) float64 행렬 하나로 접는다 — 없는 칸은 NaN. 0.12.0이 옆에 두던 Arrow 사본과 validity bitmap은 없다(기록 235). "
              "<code>placement</code>의 799.7 ms는 vqapr 안의 호출이 없는 시간이다 — 이 세션에서 numpy 블록을 처음 만드는 프로세스의 cold cost. ④·⑥의 같은 자리는 1.1 ms다.",
              "<code>Panel.from_table</code>(#8744, 800.4 ms) → <code>placement</code>(#8745, 799.7 ms) → <code>_is_numeric</code>(#8746) → <code>dense_block</code>(#8747, 0.08 ms) → <code>Panel.window</code>(#8748) → <code>PanelWindow.matrix</code>(#8756) → <code>Panel.block</code>(#8757).",
              fn="Panel.from_table() — 블록", code=at("src/vqapr/data/panel.py", "blocks[name] = dense_block(", 10, before=6),
              mem={"panel.blocks['close'].shape": "(17, 10) — 0.12.0에선 (735, 10)", "panel.bounds": "01-03 15:30 ~ 01-25 23:00"}),
            F("06_run_features", 7923, "첫 세션 — 창을 행렬로 읽고, 아직 여섯 행이 아니라 빈 목록",
              "<code>window.matrix()</code>는 블록의 행 slice — view — 다: 01-04 16:00에 알 수 있는 행은 2개(01-03 · 01-04)라 <code>closes.shape == (2, 10)</code>. <code>LOOKBACK=6</code>에 못 미쳐 <code>[]</code>를 돌려준다. 프레임워크는 빈 목록을 그대로 받는다(<code>rows=[]</code>). "
              "이 compute 1,395.2 ms의 거의 전부가 위의 첫 스캔과 첫 블록이다; 다음 세션의 compute는 2.0 ms(#8812).",
              "<code>RunLoop.handle</code>(#7880, 1,397.5 ms) → <code>DataModelPart.dispatch</code>(#7881) → <code>SampleFeatures.compute</code>(#7923, 1,395.2 ms) → <code>panel_window</code>(#7944) → … → <code>PanelWindow.matrix</code>(#8756, 0.08 ms) → <code>derived_available_at</code>(#8762) → <code>RunOutput.append</code>(#8764, rows=[]).",
              fn="SampleFeatures.compute() — 저자 코드", code=at(DECL + "features.py", "closes = window.matrix()", 12, before=1), author=True,
              mem={"closes.shape": "(2, 10) — 세션 2 × 종목 10", "returned": "[]"}),
            F("06_run_features", 9121, "다섯 번째 세션 — 종목 9개의 모멘텀을 한 식으로",
              "2022-01-10 16:00. 창에 여섯 행이 찼다. <code>closes[-1] / closes[0] - 1.0</code>가 열마다(=종목마다) 한 번에 계산되고, 여섯 값이 다 있는 열만 행으로 나간다: K000001 −0.90% · K000002 −3.34% · K000003 +8.55% · K000008 +15.14% … 9행(K000010은 열이 비어 빠진다). 이번 compute는 2.8 ms. "
              "<code>available_at</code>은 저자가 아니라 프레임워크가 찍는다(16:00, 이 세션의 평가 시각): 이 값은 <b>이 시각에야</b> 알 수 있는 값이다.",
              "<code>RunLoop.handle</code>(#9078, 16.3 ms) → <code>compute</code>(#9121, 2.8 ms) → <code>PanelWindow.matrix</code>(#9168) → <code>derived_available_at</code>(#9418) → <code>RunOutput.append</code>(#9420, 2.9 ms, rows=[{available_at: 2022-01-10 16:00+09:00, instrument: 'K000001', momentum_5d: …}, …]).",
              fn="SampleFeatures.compute() — 행 9", code=at(DECL + "features.py", "momentum = closes[-1]", 8, before=2), author=True,
              mem={"rows this session": "9", "rows so far": "9 → 세션 16에서 108"}),
            F("06_run_features", 13275, "출력이 dataset이 된다 — 같은 문을 지나서",
              "16세션이 끝나면 <code>RunOutput.register</code>가 모은 행을 <code>all.parquet</code>으로 굳히고(<code>_seal</code>, 277.7 ms) 그 파일을 <b>①의 <code>verify_source</code>에 그대로</b> 넣는다: 스키마 · key(available_at, instrument) · span(01-10 16:00 ~ 01-25 16:00) · 값 · digest <code>54f8fd04…</code>. 통과하면 등록부에 <code>sample-features</code>가 <code>produced_by: sample-features-run</code>, <code>produced_by_record: sample-features@20c2acad</code>와 함께 적힌다. "
              "프레임워크가 쓴 표라고 문을 건너뛰지 않는다.",
              "<code>RunOutput.register</code>(#13275, 450.1 ms) → <code>_seal</code>(#13304, 277.7 ms) → <code>verify_source</code>(#13306, 118.7 ms) → <code>check_schema</code>(#13315) → <code>check_key</code>(#13342) → <code>check_span</code>(#13363) → <code>check_values</code>(#13374) → <code>physical_digest</code>(#13408) → <code>register_dataset</code>(#13430) → <code>commit</code>(#13437, 46.3 ms) → <code>Workspace._write</code>(#13451) → <code>success</code>(#13667).",
              fn="RunOutput.register()", code=("def", 14),
              disk={".vqapr/materialized/sample-features/all.parquet": "108행 (available_at · instrument · momentum_5d)", ".vqapr/runs/sample-features-run/": "run.json · datamodels/sample-features@20c2acad/datamodel.json", ".vqapr/workspace.yaml": "datasets + sample-features (source_digest 54f8fd04…)"}),
        ],
        "remember": [
            "panel은 run의 horizon + lookback만큼만 스캔된다. 1년 run은 10년 원천에서 1년만 든다.",
            "숫자 필드는 float64 블록 한 벌이고 matrix()는 그 view다. 출력 parquet도 등록될 때 같은 문을 지난다.",
        ],
    },
    # ---------------------------------------------------------------- ④ factor strategy
    {
        "id": "factor", "key": "④", "title": "factor 전략",
        "sub": "register factor.yaml · 225 ms · 1,058 호출 — run sample-factor-run · 3,370 ms · 31,759 호출 · 10세션 · 이벤트 20",
        "story": (
            "<b>지금 하는 일:</b> <code>factor.py</code>의 <code>SampleFactor</code>는 ③이 만든 <code>sample-features.momentum_5d</code>를 <b>벤더 표처럼</b> 한 줄로 선언해 읽고(최신 행 하나), 상위 3종목 롱 · 하위 3종목 숏, 각 1/6씩(달러 중립, <code>Rebalance.signed</code>)을 돌려준다. "
            "숏이 있으니 거래소는 SIGNED 상장이 필요하다 — <code>exchange_signed.py</code>가 같은 열 종목을 <code>ListingAccess.SIGNED</code>로 든다. run은 2022-01-12 ~ 01-25, 계좌 mode SIGNED. 끝나면 비중이 <code>sample-factor-weights</code>로 저장된다(⑥이 읽는다). "
            "panel: <code>sample-features</code> 12행 중 horizon 안의 <b>11 × 10</b>(01-11 16:00 ~ 01-25 16:00)."
        ),
        "frames": [
            F("08_run_factor", 7446, "preflight — 읽을 dataset과 집행표를 identity로 묶는다",
              "이 전략이 읽는 <code>sample-features</code>는 다른 run이 쓴 표지만 preflight엔 다른 dataset과 똑같다: <code>require_verified</code>(8.0 ms). 집행표는 등록의 <code>execution_prices=['close']</code>에 <code>trade_price: close</code>가 있는지 <b>튜플 조회</b>로 본다. 얼린 run은 세 digest(가격표 · 집행표 · feature 표)를 든다.",
              "<code>preflight_run</code>(#722, 1,018.5 ms) → <code>require_verified</code>(#3691, 6.8 ms) … <code>preflight_run</code>(#4013, 252.0 ms) → <code>require_verified</code>(#6995, 0.001 ms: 같은 workspace 객체라 memo) → <code>_freeze_sources</code>(#7445, 9.1 ms) → <code>_validate_requirement</code>(#7446) → <code>require_verified</code>(#7455, 8.0 ms).",
              fn="_validate_requirement()", code=at("src/vqapr/flow/declaration/preflight.py", "def _validate_requirement", 14)),
            F("08_run_factor", 8587, "아침 8시 — feature 표의 스캔 범위: 한 행 앞부터 end까지",
              "2022-01-12 08:00, 첫 <code>call.read('features', 'momentum_5d')</code>. lookback이 <code>RowsLookback(rows=1)</code>이니 store는 start(01-12) 앞의 격자 한 칸 — 01-11 16:00 — 을 하한으로, end(01-25 23:59:59)를 상한으로 잡고 그 사이만 스캔한다(16.7 ms). panel은 (11 × 10) 블록 하나(1.1 ms). "
              "이 표의 세션이 12개뿐이라 0.12.0과 크기 차이는 한 행이지만, 자리는 같은 자리다.",
              "<code>panel_window</code>(#8572, 37.6 ms) → <code>_scan_bounds</code>(#8587, 13.0 ms) → <code>_grid_bound</code>(#8588, rows=1) → <code>observation_table</code>(#8612, 16.7 ms) → <code>Panel.from_table</code>(#8649, 1.1 ms) → <code>PanelWindow.matrix</code>(#8661, 0.08 ms).",
              fn="_scan_bounds()", code=("def", 12),
              mem={"bounds": "2022-01-11 16:00 ~ 2022-01-25 23:59:59 +09:00", "panel.blocks['momentum_5d'].shape": "(11, 10)"}),
            F("08_run_factor", 8545, "feature 한 행을 읽고 여섯 이름을 고른다",
              "창은 01-11 16:00의 행(전날 저녁에 알 수 있던 값) 하나 × 종목 10. 정렬해서 하위 3(K000004 · K000005 · K000006)에 −1/6, 상위 3(K000003 · K000008 · K000009)에 +1/6. "
              "<code>Rebalance.signed(weights, gross=1)</code>: 부호가 방향이고 gross 1이면 롱 0.5 · 숏 0.5. 이 decide는 42.9 ms(feature 표 첫 스캔 포함), 다음 날은 6.7 ms(#10798).",
              "<code>RunLoop.handle</code>(#8425, 78.4 ms) → <code>StrategyPart.dispatch</code>(#8426) → <code>SampleFactor.decide</code>(#8545, 42.9 ms) → <code>panel_window</code>(#8572) → <code>matrix</code>(#8661) → <code>Rebalance.signed</code>(#8675, 3.9 ms) → <code>RunStateRepository.publish</code>(#9309, 8.3 ms).",
              fn="SampleFactor.decide() — 저자 코드", code=at(DECL + "factor.py", "ranked = sorted(", 10, before=3), author=True,
              mem={"weights": "K000003 +0.1667 · K000008 +0.1667 · K000009 +0.1667 · K000004 −0.1667 · K000005 −0.1667 · K000006 −0.1667", "pending": "intent 1 (계좌 v0 기준)"}),
            F("08_run_factor", 9356, "오후 3시 반 — 숏 셋이 실제로 팔린다",
              "시장 시계 01-12 15:30. pending 의도서가 due가 되고 <code>ExecutionHandler.fill</code>이 주문을 계획한다(<code>plan_orders</code>, 13.8 ms: 비중 → 수량, 정수 주). SIGNED 상장이라 음수 수량이 통과한다. 체결: K000003 +23 · K000008 +8 · K000009 +94, K000004 <b>−55</b> · K000005 <b>−19</b> · K000006 <b>−12</b> (close 가격, 학술 프로파일이라 수수료 0). 계좌 v1: 현금 99,463,501.24, NAV 100,000,000.",
              "<code>MarketClock.at</code>(#9349, 122.5 ms) → <code>fill</code>(#9356, 97.3 ms) → <code>select_snapshot</code>(#9367, 46.9 ms) → <code>plan_orders</code>(#9443, 13.8 ms) → <code>AcademicExchange.execute</code>(#9823, 7.2 ms) → <code>Account.append</code>(#10068) → <code>_publish_account_commit</code>(#10307, 14.4 ms).",
              fn="ExecutionHandler.fill()", code=("def", 12),
              mem={"account v1": "롱 3 · 숏 3 · cash 99,463,501.24 · NAV 100,000,000.00"}),
            F("08_run_factor", 10340, "평가 → 판정 → 마감 — 규칙이 없어도 자리는 있다",
              "같은 시각에 이어서: 보유를 close로 평가하고(<code>mark</code>, 21.2 ms), compliance 규칙이 없으니 <code>observe</code>는 0.003 ms, <code>close</code>가 이 시각의 상태를 publish한다. 시장 시계 한 점은 늘 이 다섯 단계(발생 → 체결 → 평가 → 판정 → 마감)다 — 이 run엔 열 점.",
              "<code>ValuationHandler.mark</code>(#10340) → <code>mark_fill</code>(#10341) → <code>publish_infallible</code>(#10603) → <code>ComplianceHandler.observe</code>(#10648, 0.003 ms) → <code>ExecutionHandler.close</code>(#10649, 1.0 ms) → <code>publish_infallible</code>(#10664).",
              fn="ValuationHandler.mark()", code=("def", 10)),
            F("08_run_factor", 31258, "run이 끝나면 비중이 dataset이 된다 — 역시 같은 문",
              "10세션(계좌 v10, 주문 73 · 체결 54 · no_trade 19)이 끝나면 record를 굳히고(<code>_seal</code>, 표 3: account · fill · weight) <code>_publish_allocation</code>이 <code>vqapr.weight</code> 60행을 <code>sample-factor-weights</code>로 낸다: 각 행의 <code>available_at</code>은 그 결정의 시각(08:00). 이 파일도 <code>verify_source</code>를 지나 등록된다(digest <code>76a9b69b…</code>).",
              "<code>RunRecordWriter._seal</code>(#31066, 292.4 ms) → <code>_write_parquet</code> ×3(#31069 · #31083 · #31097) → <code>_publish_allocation</code>(#31120, 305.2 ms) → <code>RunOutput.register</code>(#31258, 218.5 ms) → <code>verify_source</code>(#31284, 127.6 ms) → <code>physical_digest</code>(#31386) → <code>register_dataset</code>(#31408) → <code>commit</code>(#31415) → <code>_write</code>(#31429) → <code>success</code>(#31753).",
              fn="RunOutput.register()", code=("def", 8),
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
        "sub": "register stoploss.yaml · 180 ms · 1,112 호출 — run sample-stoploss-run · 8,810 ms · 77,553 호출 · 37세션 · 이벤트 74",
        "story": (
            "<b>지금 하는 일:</b> <code>stoploss.py</code>의 <code>SampleStopLoss</code>는 첫 세션에 종가가 있는 모든 종목을 동일가중으로 사고 각 종목의 <b>진입 종가를 <code>self.memory</code>에 적는다</b>. 그 뒤 세션마다 최신 종가를 기억한 진입가와 견줘 3% 넘게 빠진 종목은 버리고 <code>stopped</code>에 날짜를 적는다. "
            "memory는 엄격한 JSON이고 매 decide 전에 복원되고 뒤에 publish된다 — 같은 run을 다시 돌리면 같은 손절이 같은 날 난다. 이 합성 패널은 잘 빠져서 손절이 이어지고, 02-22엔 K000008 하나, 02-23에 전량 매도, 그 뒤는 현금. "
            "panel: 등록 span 735행이 아니라 <b>38 × 10</b>(01-03 ~ 02-28)."
        ),
        "frames": [
            F("10_run_stoploss", 13345, "decide 전 — memory {}가 전략에 복원된다",
              "2022-01-04 08:00, 첫 콜백. 프레임워크가 지금 root의 model memory(첫 세션이라 <code>{}</code>)와 payload(빈 바이트)를 전략 인스턴스에 넣는다. 전략은 하나의 인스턴스로 run 전체를 살지만, <b>믿을 것은 이 복원된 memory뿐</b>이다 — 다른 self 속성은 record가 재현하지 못한다.",
              "<code>StrategyPart.dispatch</code>(#13319, 212.1 ms) → <code>_visible_callback_state</code>(#13326) → <code>_restore_callback_state</code>(#13345: <code>strategy.memory = {}</code> · <code>load_payload(b'')</code>) → 창 → 계좌 view → decide.",
              fn="_restore_callback_state()", code=at("src/vqapr/flow/run/callback.py", "def _restore_callback_state", 4),
              mem={"strategy.memory": "{}"}),
            F("10_run_stoploss", 13474, "첫 창 — 38행짜리 panel 하나가 run 전체를 든다",
              "start(01-04)에서 <code>RowsLookback(rows=1)</code>이 닿는 격자 한 칸 앞은 01-03 15:30, end는 02-28 23:59:59. 그 사이 38세션 × 10종목 float64 블록 하나(83.5 ms; 이 프로세스의 첫 블록)를 만들고, 37세션의 모든 decide가 그 블록의 slice를 본다. 0.12.0은 이 run에서도 735행을 들었다.",
              "<code>SampleStopLoss.decide</code>(#13438, 167.7 ms) → <code>panel_window</code>(#13459, 161.5 ms) → <code>_scan_bounds</code>(#13474, 55.8 ms) → <code>observation_table</code>(#14222, 17.5 ms) → <code>Panel.from_table</code>(#14259, 83.5 ms) → <code>PanelWindow.matrix</code>(#14271). 둘째 날: <code>panel_window</code>(#17087, 1.3 ms) → <code>_scan_bounds</code>(#17100, 0.18 ms, 같은 identity → 같은 panel).",
              fn="_scan_bounds()", code=("def", 8),
              mem={"bounds": "2022-01-03 15:30 ~ 2022-02-28 23:59:59 +09:00", "panel.blocks['close'].shape": "(38, 10)"}),
            F("10_run_stoploss", 13438, "첫 decide — 9종목에 진입하고 진입가 9개를 memory에 적는다",
              "최신 종가(01-03의 것)가 있는 종목은 9개(K000010은 아직 없다). <code>entered</code> 플래그가 없으니 <code>entry</code>에 9개의 종가를 적고 플래그를 세운다. 아무도 3%를 깨지 않았으니 9종목 동일가중 <code>Rebalance.of(long=…, invested='0.9')</code>. "
              "플래그를 따로 둔 이유: 나중에 <code>entry</code>가 비었을 때 \"처음\"으로 오해해 다시 사지 않기 위해서다.",
              "<code>SampleStopLoss.decide</code>(#13438, 167.7 ms) → <code>_DeclaredReads.read</code> → <code>panel_window</code>(#13459) → <code>matrix</code>(#14271) → <code>Rebalance.of</code>(#14276, 4.7 ms).",
              fn="SampleStopLoss.decide() — 저자 코드", code=at(DECL + "stoploss.py", "entry: dict[str, float]", 12), author=True,
              mem={"self.memory": "{entry: {K000001: 145993.43, …, K000009: 170809.66}, stopped: {}, entered: true}"}),
            F("10_run_stoploss", 14667, "decide 후 — memory가 정규화되고 의도서와 함께 publish된다",
              "돌아온 memory를 <code>normalize_memory</code>가 엄격한 JSON으로 확인하고(Decimal · datetime · set이 있으면 여기서 거절), payload와 함께 model state ref를 만든다. 의도서(9종목 비중)에 도장을 찍고(<code>_stamp_intent</code>) 받아들인 뒤(<code>_accept_intent</code>) 계좌 · memory · pending을 <b>한 번</b>에 publish한다(root v1). "
              "15:30에 9종목이 체결된다: K000001 68 · K000002 45 · K000003 14 · K000004 31 · K000005 11 · K000006 7 · K000007 24 · K000008 6 · K000009 57.",
              "<code>_stamp_intent</code>(#14393, 4.8 ms) → <code>_accept_intent</code>(#14571) → <code>_record_defaults</code>(#14588) → <code>_candidate_callback_state</code>(#14667, 7.7 ms: <code>normalize_memory</code> #14668 · <code>save_payload</code> #14697 · <code>prepare_model_state</code> #14698) → <code>_callback_evidence</code>(#14857) → <code>_prepare_callback_publication</code>(#14968) → <code>RunStateRepository.publish</code>(#15085, 9.0 ms) · <code>MarketClock.at</code>(#15125, 131.9 ms) → <code>fill</code>(#15132, 80.9 ms) → <code>plan_orders</code>(#15228, 23.9 ms) → <code>execute</code>(#15812) → <code>Account.append</code>(#16171).",
              fn="_candidate_callback_state()", code=at("src/vqapr/flow/run/callback.py", "def _candidate_callback_state", 10),
              mem={"root": "v1 (account v0 · memory entry 9 · pending 1)"}),
            F("10_run_stoploss", 17066, "둘째 날 — 복원된 memory로 첫 손절",
              "01-05 08:00. 복원된 memory(#16971)에 진입가 9개가 있다. 최신 종가(01-04)를 견주면 K000005가 911,750.33 → 884,024.23, −3.04%로 넘겼다 → <code>stopped['K000005'] = '2022-01-05'</code>, <code>entry</code>에서 지운다. 남은 8종목 동일가중; 15:30에 K000005 −11주. "
              "이어지는 세션들(weight 표의 세션당 보유 수): 9 → 8(01-05) → 7(01-06 K000004) → 5(01-11 K000002 · K000006) → 4(01-19 K000007) → 3(01-24 K000001) → 2(01-25 K000009) → 1(01-26 K000003 → 02-22까지 K000008 하나).",
              "<code>StrategyPart.dispatch</code>(#16919, 56.0 ms) → <code>_restore_callback_state</code>(#16971) → <code>SampleStopLoss.decide</code>(#17066, 7.1 ms) → <code>Rebalance.of</code>(#17118) → <code>_stamp_intent</code>(#17225) → <code>_accept_intent</code>(#17397).",
              fn="SampleStopLoss.decide() — 손절", code=at(DECL + "stoploss.py", "for name, price in list(entry.items())", 6), author=True,
              mem={"self.memory": "{entry: 8, stopped: {K000005: '2022-01-05'}, entered: true}"}),
            F("10_run_stoploss", 72584, "마지막 이름이 깨지면 — 전량 매도는 Hold가 아니라 빈 Rebalance",
              "02-23 08:00. K000008이 02-22 종가로 −3%를 넘겼다. <code>entry</code>가 비었고 계좌엔 K000008 52주가 있다. <code>Hold</code>는 \"아무것도 하지 말라\"라 포지션이 그대로 남는다; 그래서 <code>Rebalance(target_weights={}, cash_weight=1)</code>을 돌려준다. 15:30에 <b>K000008 −52</b>가 1,441,901.11에 체결되고 계좌(v34)는 현금 84,184,068.92뿐이다.",
              "<code>decide</code>(#72584, 2.9 ms) → <code>Rebalance.__init__</code>(#72640) → <code>_accept_intent</code>(#72772) → <code>_candidate_callback_state</code>(#72796) → <code>publish</code>(#73214) · <code>MarketClock.at</code>(#73242, 209.5 ms) → <code>fill</code>(#73249, 18.9 ms) → <code>plan_orders</code>(#73288) → <code>execute</code>(#73371) → <code>Account.append</code>(#73426).",
              fn="SampleStopLoss.decide() — 마지막", code=at(DECL + "stoploss.py", "if any(quantity != 0", 5, before=3), author=True,
              mem={"self.memory": "{entry: {}, stopped: 9개, entered: true}", "account v34": "positions {} · cash 84,184,068.92"}),
            F("10_run_stoploss", 73956, "그 뒤 — Hold, pending 없음, 시장 시각은 평가만",
              "02-24 08:00부터 <code>entry</code>도 포지션도 없다 → <code>Hold</code>(\"every name has broken its stop; the book stays in cash\"). pending이 없으니 15:30의 <code>fill</code>은 <code>due=None</code>으로 0.003 ms에 지나가고 평가만 한다. run은 74 이벤트, 계좌 v34, 주문 111 · 체결 59 · no_trade 52로 끝나고 비중 dataset <code>sample-stoploss-weights</code>가 문을 지나 등록된다(#76945).",
              "<code>decide</code>(#73956, 2.9 ms) → Hold · <code>MarketClock.at</code>(#74465, 86.7 ms) → <code>fill</code>(#74472, 0.003 ms, due=None) … <code>_seal</code>(#76569, 238.8 ms) → <code>_publish_allocation</code>(#76697) → <code>RunOutput.register</code>(#76919) → <code>verify_source</code>(#76945, 136.2 ms) → <code>register_dataset</code>(#77069) → <code>success</code>(#77547).",
              fn="SampleStopLoss.decide() — Hold", code=at(DECL + "stoploss.py", "return va.Hold(", 1, before=0), author=True,
              disk={".vqapr/runs/sample-stoploss-run/strategies/sample-stoploss@bb45a6ab/": "strategy.json · tables 3 (weight 표 33세션분, 02-23부터 없음)", ".vqapr/materialized/sample-stoploss-weights/all.parquet": "등록됨 (digest e09f29f7…)"},
              tip="strategy.json에는 memory dict가 없다. 트레이스가 보이는 것은 매 콜백의 복원(_restore_callback_state) → 정규화(_candidate_callback_state) → publish이고, record에는 그 상태의 ref가 남는다."),
        ],
        "remember": [
            "memory는 decide 전에 복원되고 뒤에 정규화되어 publish된다. 첫 콜백엔 {}. JSON이 아닌 것은 여기서 거절된다.",
            "\"처음인가\"는 별도 플래그로 기억한다. 포지션을 다 비우려면 Hold가 아니라 빈 Rebalance를 돌려준다.",
        ],
    },
    # ---------------------------------------------------------------- ⑥ enhanced index
    {
        "id": "ei", "key": "⑥", "title": "enhanced index",
        "sub": "register enhanced.yaml · 226 ms · 1,315 호출 — run sample-enhanced-run · 3,394 ms · 35,341 호출 · 9세션 — list datasets 79 ms · show run 37 ms",
        "story": (
            "<b>지금 하는 일:</b> <code>enhanced.py</code>의 <code>SampleEnhancedIndex</code>는 ④가 저장한 <code>sample-factor-weights.weight</code>를 <b>alpha로 읽고</b>, 종가가 있는 종목의 동일가중(1/9)에 그 alpha의 절반을 더한 뒤 0 아래를 자른다 — 롱온리 enhanced index. "
            "run은 09:00에 결정한다(④의 08:00 비중이 알 수 있게 된 뒤). 두 dataset이 각각 자기 horizon으로 잘린다: 가격 (10 × 10), alpha (10 × 10). 마지막으로 <code>list datasets</code>와 <code>show run</code>으로 이 프로젝트에 무엇이 남았는지 읽는다: dataset 6개, 그중 4개가 run이 만든 것."
        ),
        "frames": [
            F("12_run_enhanced", 7674, "preflight — 저장된 alpha가 dataset으로 묶인다",
              "요구 둘: <code>sample-factor-weights</code>(source <code>materialized-sample-factor-weights</code>)와 <code>sample-prices</code>. 둘 다 <code>_validate_requirement</code> → <code>require_verified</code>(9.5 · 3.2 ms). run이 만든 표와 벤더 표가 여기서 같은 취급을 받는다는 것이 이 시나리오의 요점이다.",
              "<code>preflight_run</code>(#1040, 1,177.3 ms) → … <code>_freeze_sources</code>(#7673, 14.5 ms) → <code>_validate_requirement</code>(#7674) → <code>Workspace.require_verified</code>(#7675) → <code>require_verified</code>(#7683, 9.5 ms) · <code>_validate_requirement</code>(#7691) → <code>require_verified</code>(#7700, 3.2 ms).",
              fn="_validate_requirement()", code=("def", 14),
              mem={"frozen.source_digests": "{materialized-sample-factor-weights: 76a9b69b…, sample-prices-source: 18bb7017…}"}),
            F("12_run_enhanced", 8840, "9시 — 두 창을 각자의 horizon으로 읽고 벤치마크에 alpha를 얹는다",
              "2022-01-13 09:00. 가격 창: 하한 01-12 15:30(start 앞 한 칸), (10 × 10) 블록 → 행 1에서 종목 9개(K000010 없음) → 벤치마크 1/9 = 0.111. alpha 창: 하한 01-12 08:00, (10 × 10) 블록 → 행 1(01-13 08:00의 factor 비중 ±1/6)에서 K000003 · 8 · 9는 +0.0833, K000004 · 5 · 6은 −0.0833 → tilt: 0.194 · 0.028. <code>Rebalance.of(long=…, invested='1')</code>이 정규화한다(합 1). "
              "이 decide는 110.5 ms(두 표의 첫 격자 읽기 48.3 · 13.9 ms, 스캔 14.5 · 14.5 ms), 다음 날은 9.5 ms(#12648).",
              "<code>StrategyPart.dispatch</code>(#8709, 154.3 ms) → <code>SampleEnhancedIndex.decide</code>(#8840, 110.5 ms) → <code>read</code>(#8841: prices, 68.8 ms) → <code>panel_window</code>(#8861) → <code>_scan_bounds</code>(#8876, 48.3 ms) → <code>observation_table</code>(#9624, 14.5 ms) → <code>from_table</code>(#9661, 1.1 ms) → <code>matrix</code>(#9673) → <code>read</code>(#9677: alpha, 36.5 ms) → <code>panel_window</code>(#9698) → <code>_scan_bounds</code>(#9713, 13.9 ms) → <code>observation_table</code>(#9736) → <code>from_table</code>(#9773, 0.8 ms) → <code>matrix</code>(#9785) → <code>Rebalance.of</code>(#9789, 4.8 ms).",
              fn="SampleEnhancedIndex.decide() — 저자 코드", code=at(DECL + "enhanced.py", "tilted = {", 6, before=0), author=True,
              mem={"weights": "K000002 · K000003 · K000008 0.1944 · K000004 · K000005 · K000009 0.0278 · K000001 · K000006 · K000007 0.1111", "panels": "prices (10 × 10) 01-12 15:30 ~ · alpha (10 × 10) 01-12 08:00 ~"}),
            F("12_run_enhanced", 10728, "3시 반 — 롱온리 체결, 그리고 아홉 세션",
              "첫 체결은 70.9 ms(주문 9: K000001 76 · K000002 87 · K000003 27 · K000004 9 · K000005 3 · K000006 8 · K000007 27 · K000008 10 · K000009 15). 9세션 동안 이벤트 18, 주문 81 · 체결 41 · no_trade 40(비중이 거의 안 변하는 날은 주문이 0주로 계획된다), 계좌 v9. 끝나면 <code>sample-enhanced-weights</code>가 문을 지나 등록된다.",
              "<code>MarketClock.at</code>(#10721, 99.6 ms) → <code>fill</code>(#10728, 70.9 ms) → <code>select_snapshot</code>(#10742, 17.0 ms) → <code>plan_orders</code>(#10824, 21.2 ms) … 다음 날 <code>decide</code>(#12648, 9.5 ms) … <code>_seal</code>(#34547) → <code>_publish_allocation</code>(#34598) → <code>RunOutput.register</code>(#34778) → <code>verify_source</code>(#34804, 117.2 ms) → <code>success</code>(#35335).",
              fn="ExecutionHandler.fill()", code=("def", 8)),
            F("13_list_datasets", 12, "list datasets — 여섯, 그중 넷은 run이 만들었다",
              "등록부를 열어(63.5 ms) dataset 목록을 낸다: <code>sample-prices</code> · <code>sample-execution</code>(벤더) · <code>sample-features</code>(produced_by <code>sample-features-run</code>, record <code>sample-features@20c2acad</code>) · <code>sample-factor-weights</code>(<code>sample-factor@9bba20c4</code>) · <code>sample-stoploss-weights</code>(<code>sample-stoploss@bb45a6ab</code>) · <code>sample-enhanced-weights</code>(<code>sample-enhanced@f174be27</code>). "
              "어느 run의 어느 코드 버전이 이 표를 썼는지가 이름 옆에 있다.",
              "<code>list_.run</code>(#11, 65.7 ms) → <code>Workspace.open</code>(#12, 63.5 ms) → <code>success</code>(#1075, stage workspace.list, count 6).",
              fn="Workspace.open()", code=("def", 8)),
            F("14_show_run_enhanced", 18, "show run — record만 읽는다, 32호출 37 ms",
              "<code>show run sample-enhanced-run</code>은 record(<code>run.json</code>)만 읽는다: 읽은 dataset 둘과 각각의 <code>source_digest</code>(76a9b69b… · 18bb7017…), 거래소 fingerprint, 집행 선언(close · 15:30 · Asia/Seoul), 초기 계좌, 기간 01-13 ~ 01-25, 기록 <code>sample-enhanced@f174be27</code>. 이 run이 어떤 바이트를 읽었는지가 record에 있으므로 나중에 파일이 바뀌어도 그때 무엇이었는지는 남는다.",
              "<code>main</code>(#0, 36.8 ms) → <code>show.run</code>(#11, 24.6 ms) → <code>run_ids</code>(#12, 14.8 ms) → <code>read_run_record</code>(#18, 4.7 ms) → <code>record_view</code>(#21) → <code>strategy_refs</code>(#22) → <code>datamodel_refs</code>(#25) → <code>success</code>(#26, stage run.show).",
              fn="read_run_record()", code=("def", 8),
              disk={".vqapr/": "workspace.yaml · instruments.json · materialized/ 4 · runs/ 4"}),
        ],
        "remember": [
            "run이 저장한 비중은 dataset이다: 다음 run이 DatasetInput 한 줄로 읽고, preflight는 digest로 묶고, panel은 자기 horizon으로 잘린다.",
            "list · show는 등록부와 record만 읽는다. record는 읽은 파일의 digest를 든다.",
        ],
    },
    # ---------------------------------------------------------------- ⑦ --jobs batch
    {
        "id": "batch", "key": "⑦", "title": "--jobs 배치 — cube 한 번",
        "sub": "run sample-factor-run sample-stoploss-run --jobs 2 --force · 3,250 ms · 3,659 호출 (driver) — worker 하나를 따로 추적: 9,960 ms · 27,442 호출",
        "story": (
            "<b>지금 하는 일:</b> ④와 ⑤를 <b>한 배치</b>로 다시 돌린다(<code>--jobs 2</code>; 기록이 이미 있으니 <code>--force</code>). 0.13.0의 driver는 worker를 띄우기 <b>전에</b> 배치가 읽는 panel-grain dataset마다 cube를 굽는다: <code>sample-features.momentum_5d</code>(12 × 9)와 <code>sample-prices.close</code>(735 × 10), 각각 전 종목 × 등록 span. "
            "worker는 자기 horizon만큼을 그 파일의 <b>slice</b>로 받는다(<code>np.load(mmap_mode='r')</code>) — 스캔이 없다. 배치가 돌아오면 디렉터리는 지워진다(기록 236, 이슈 098). "
            "driver의 트레이스는 프로세스 경계에서 끝나므로(<code>in_workers</code>가 spawn한다) worker 쪽은 <code>trace_worker.py</code>가 같은 worker 함수(<code>run_registered_strategy</code>)를 같은 프로파일러 아래서 따로 돌려 얻었다."
        ),
        "frames": [
            F("15_run_batch", 12, "여러 run이면 driver는 배치를 먼저 판정한다",
              "<code>run a b --jobs 2</code>. target이 둘 이상이고 jobs가 1보다 크니 <code>_run_each_in_workers</code>. 등록부를 열고(#15, 61.8 ms) <code>require_independent_batch</code>(#1064, 22.3 ms)가 두 run이 서로가 쓰는 것을 읽지 않는지 본다 — factor는 <code>sample-features</code>를, stop-loss는 <code>sample-prices</code>를 읽고, 둘 다 서로의 <code>writes</code>가 아니다. pool은 순서를 약속하지 않으므로 읽는 쪽이 있으면 배치 전체가 거절된다.",
              "<code>run</code>(#11) → <code>_run_each_in_workers</code>(#12, 3,236.6 ms) → <code>refuse_a_path</code>(#13 · #14) → <code>Workspace.open</code>(#15) → <code>require_independent_batch</code>(#1064) → <code>_reads</code>(#1070 · #1159) → <code>run_definition</code>(#1237 · #1239) → <code>batch_cubes</code>(#1241).",
              fn="_run_each_in_workers()", code=at("src/vqapr/cli/run.py", "with batch_cubes(workspace, targets) as cubes:", 12, before=6),
              mem={"targets": "[sample-factor-run, sample-stoploss-run]", "reads": "factor → sample-features[momentum_5d] · stop-loss → sample-prices[close]"}),
            F("15_run_batch", 1241, "batch_cubes — 묵은 것을 쓸고, 잠그고, 굽는다",
              "<code>.vqapr/cubes/</code> 아래에 <code>&lt;pid&gt;-&lt;random&gt;/</code>를 만들고 lock 파일에 pid를 적는다. 먼저 <code>_sweep_stale_cubes</code>(1.4 ms)가 lock이 10분 넘게 갱신되지 않은 이전 배치의 디렉터리를 지운다 — 강제 종료된 driver가 남긴 것. 30초마다 lock을 만지는 heartbeat 스레드가 이 배치를 살아 있는 것으로 표시한다. 그리고 <code>_bake_for_batch</code>.",
              "<code>batch_cubes</code>(#1241, 621.1 ms) → <code>_sweep_stale_cubes</code>(#1242, 1.4 ms) → <code>_bake_for_batch</code>(#1243, 610.5 ms) → <code>_reads</code>(#1246 · #1336) → <code>ScanSession.__init__</code>(#1414).",
              fn="batch_cubes()", code=("def", 14),
              disk={".vqapr/cubes/<pid>-<hex>/": "cube.lock (pid)"}),
            F("15_run_batch", 1528, "bake — sample-prices.close를 전 종목 × 등록 span으로 한 번",
              "dataset마다 한 번씩: <code>distinct_values</code>로 원천이 든 종목 전부(10)를 세고, <code>observation_table</code>이 등록 span 전체를 <b>종목 제한 없이</b> 스캔하고(6,900행), <code>placement</code>·<code>dense_block</code>이 (735 × 10) float64 하나로 접어 <code>close.npy</code>(58,928 B)로 저장한다. 옆에 <code>present.npy</code>(행이 있던 칸), <code>instants.npy</code>(735), <code>instruments.json</code>(10), <code>cube.json</code>(원천 digest <code>18bb7017…</code>). "
              "앞의 <code>sample-features</code>는 12 × 9 — K000010은 그 표에 한 행도 없다. 굽지 못하는 것(등록 안 된 표, 문자열 필드, rows grain)은 조용히 빠지고 그 worker는 스캔한다.",
              "<code>source_digest</code>(#1423) → <code>bake</code>(#1426, 451.3 ms: sample-features) → <code>distinct_values</code>(#1427) → <code>observation_table</code>(#1453, 350.6 ms) → <code>placement</code>(#1480) → <code>dense_block</code>(#1481) → <code>open_cube</code>(#1494) · <code>source_digest</code>(#1525) → <code>bake</code>(#1528, 127.8 ms: sample-prices) → <code>distinct_values</code>(#1529, 21.7 ms) → <code>observation_table</code>(#1557, 15.3 ms) → <code>placement</code>(#1584, 2.5 ms) → <code>dense_block</code>(#1585, rows shape (6900,)) → <code>open_cube</code>(#2321, 36.1 ms) → <code>ScanSession.__exit__</code>(#3069).",
              fn="bake()", code=at("src/vqapr/data/cube.py", "instants, keep, rows, cols = placement(table, names, keyed)", 12, before=0),
              disk={".vqapr/cubes/<batch>/sample-prices/": "close.npy (735, 10) float64 58,928 B · present.npy (735, 10) bool · instants.npy (735,) int64 · instruments.json 10 · cube.json", ".vqapr/cubes/<batch>/sample-features/": "momentum_5d.npy (12, 9) · present.npy · instants.npy (12,) · instruments.json 9 · cube.json"}),
            F("15_run_batch", 3071, "in_workers — 여기서 driver의 트레이스는 프로세스 경계를 만난다",
              "두 run이 두 spawn 프로세스에 하나씩 간다: <code>run_registered_strategy(project, run_id, store, replace=True, positions=True, cubes=&lt;dir&gt;)</code> — 문자열과 bool만 넘긴다. 2,429.5 ms 동안 driver는 기다린다. 이 프로파일러는 이 프로세스의 것이라 worker 안의 호출은 여기 없다 — 다음 프레임은 worker를 따로 추적한 트레이스다.",
              "<code>in_workers</code>(#3071, 2,429.5 ms) — 안쪽 호출 없음(다른 프로세스).",
              fn="in_workers()", code=("def", 10)),
            F("16_worker_factor", 4636, "worker — 스캔 대신 cube를 map 한다",
              "worker 프로세스의 첫 decide(01-12 08:00). <code>panel_window</code>는 평소처럼 <code>_scan_bounds</code>로 horizon을 정하고(01-11 16:00 ~ 01-25 23:59:59), 그 다음이 다르다: store에 <code>cubes</code>가 있으니 <code>open_cube</code>가 <code>sample-features/cube.json</code>을 읽고 원천 digest가 worker 자신이 방금 대조한 digest와 같은지 본 뒤(#4610, 9.0 ms), <code>panel_from_cube</code>가 <code>present.npy</code>·<code>momentum_5d.npy</code>를 <code>mmap_mode='r'</code>로 열어 horizon 안의 행만 slice 한다. "
              "run이 선언한 종목(10)이 cube의 종목(9)과 다르므로 순수 view가 아니라 gather 한 번(11 × 10, K000010 열은 NaN) — 선언한 크기만큼이다. 이 트레이스 어디에도 <code>observation_table</code>과 <code>Panel.from_table</code>이 없다.",
              "<code>SampleFactor.decide</code>(#4544, 73.1 ms) → <code>panel_window</code>(#4571, 59.7 ms) → <code>_scan_bounds</code>(#4586, 20.0 ms) → <code>_cube</code>(#4609) → <code>open_cube</code>(#4610, 9.0 ms) → <code>panel_from_cube</code>(#4636, 21.1 ms) → <code>Cube.present</code>(#4638, 10.9 ms) → <code>Cube.field</code>(#4640, 9.4 ms) → <code>PanelWindow.matrix</code>(#4649) → <code>Panel.block</code>(#4650). 다음 날: <code>panel_window</code>(#6813, 1.6 ms) → <code>_cube</code>(#6831, 0.003 ms: 이미 열렸다).",
              fn="panel_from_cube()", code=at("src/vqapr/data/cube.py", "if whole and identical:", 8, before=2),
              mem={"cube": "sample-features: instants 12 · names 9 · digest 54f8fd04… = worker의 digest", "panel": "(11 × 10) gather — K000010 열 NaN"}),
            F("15_run_batch", 3072, "배치가 돌아오면 디렉터리는 없다 — 봉투는 run마다 하나",
              "<code>in_workers</code>가 두 결과를 돌려주자 <code>batch_cubes</code>의 <code>finally</code>가 heartbeat를 멈추고 <code>rmtree</code>로 cube 디렉터리를 지운다(45.0 ms; 프로파일러는 제너레이터의 재개를 두 번째 호출로 기록한다). 성공이든 거절이든 예외든 같다 — 아무것도 쌓이지 않는다. "
              "<code>_worker_entry</code>가 run마다 record를 읽어 봉투를 만든다: factor 계좌 v10 · 주문 73 · 체결 54, stop-loss 계좌 v34 · 주문 111 · 체결 59 — ④·⑤와 같은 수. 봉투의 <code>jobs: 2</code>가 실제로 돈 프로세스 수다. 명령 뒤의 파일 목록에 <code>.vqapr/cubes/</code> 아래 파일은 없다.",
              "<code>in_workers</code>(#3071) → <code>batch_cubes</code>(#3072, 45.0 ms: finally → rmtree) → <code>_worker_entry</code>(#3073, 25.7 ms: sample-factor-run) → <code>_strategy_envelope</code>(#3074) → <code>read_table</code>(#3075 …) → <code>_worker_entry</code>(#3304, 30.1 ms: sample-stoploss-run) → <code>_runs_envelope</code>(#3649) → <code>success</code>(#3653).",
              fn="batch_cubes() — finally", code=at("src/vqapr/flow/orchestration.py", "_bake_for_batch(workspace, run_ids, directory)", 7, before=1),
              disk={".vqapr/cubes/": "비어 있음 (배치 디렉터리 삭제됨)", ".vqapr/runs/": "sample-factor-run · sample-stoploss-run 다시 씀 (--force)"}),
        ],
        "remember": [
            "--jobs 배치는 dataset마다 cube를 한 번 굽고 worker는 map 한다: 671-run sweep의 스캔 671번이 bake 한 번이 된다.",
            "cube는 배치의 것이다. 시작할 때 굽고 끝날 때 지우며, 묵은 것은 다음 배치가 쓴다. 단일 run은 스캔 경로 그대로.",
        ],
    },
]

TABLE = {
    "title": "트레이스가 확인한 것 — 0.13.0이 바꾼 자리",
    "rows": [
        ["<b>panel은 run의 horizon이다</b> (기록 235)",
         "<code>_scan_bounds</code>: datamodel 06 #7959 (01-03 15:30 ~ 01-25 23:00 → 17 × 10) · factor 08 #8587 (01-11 16:00 ~ → 11 × 10) · stop-loss 10 #13474 (01-03 15:30 ~ 02-28 → 38 × 10) · enhanced 12 #8876 · #9713 (10 × 10 둘). 0.12.0의 같은 자리는 넷 다 등록 span 735 × 10",
         "1년 run은 10년 원천에서 1년 + lookback만 든다. rows lookback은 원천의 시각 격자에서 세고, calendar lookback은 날짜로 뺀다"],
        ["<b>숫자 필드는 블록 한 벌, matrix()는 view</b> (기록 235)",
         "<code>Panel.from_table</code> → <code>placement</code> → <code>dense_block</code>: 06 #8744 · #8745 · #8747, 08 #8649 (1.1 ms), 12 #9661 · #9773. <code>PanelWindow.matrix</code> → <code>Panel.block</code>: 06 #8756 · #8757 (0.08 ms)",
         "Arrow 사본과 validity bitmap이 없다. 창을 여는 비용은 slice 하나다"],
        ["<b>--jobs 배치는 한 번 굽고 worker는 map 한다</b> (기록 236)",
         "15: <code>batch_cubes</code> #1241 → <code>bake</code> #1426 (sample-features 12 × 9) · #1528 (sample-prices 735 × 10, 127.8 ms) → <code>in_workers</code> #3071 → <code>batch_cubes</code> #3072 (rmtree). 16(worker): <code>open_cube</code> #4610 → <code>panel_from_cube</code> #4636 → <code>Cube.present</code> #4638 · <code>Cube.field</code> #4640; <code>observation_table</code> 0번",
         "스캔은 배치당 dataset마다 한 번. cube의 digest가 worker의 digest와 같을 때만 쓴다. 디렉터리는 배치와 함께 사라진다"],
        ["<b>물리 읽기의 문은 하나다</b> (기록 234)",
         "<code>verify_source</code>: 등록 01 #136 · #328 · 재등록 04 #451 · #643 · datamodel 출력 06 #13306 · 배분 출력 08 #31284 · 10 #76945 · 12 #34804. 그 밖의 읽기는 전부 <code>require_verified</code>: check 03 #45879 · preflight 06 #7425 · 08 #7455 · 12 #7683 · #7700",
         "스키마 · key · span · 값 · 집행 가격 · digest를 한 곳에서 한 번 잰다. 프레임워크가 쓴 표도, 배치의 cube도 같은 digest에 묶인다"],
        ["<b>집행 순서 판정은 run 안의 occurrence를 묻는다</b> (기록 237)",
         "03 #360 <code>_judge_execution_ordering</code> → #42201 <code>inclusive_slice</code> (180.9 ms) → #45870 <code>bound_execution_table</code>. 0.12.0은 날짜 상위집합을 그대로 순회했다",
         "체결과 결정 사이의 end가 500 대신 통과한다(이슈 099). 이 판의 트레이스는 커밋 전의 작업 트리에서 떴다"],
        ["<b>check는 표를 읽지 않는다 — 그러나 agenda는 두 번 유도한다</b>",
         "03: 바뀐 집행표의 거절이 <code>require_verified</code> #45879 8.5 ms. 남은 4.3 s 중 <code>derived_agenda</code> #362 2,019.5 ms + #48202 1,838.8 ms — 734세션 agenda를 judgments와 preflight가 <b>각각</b> 유도한다",
         "0.12.0 페이지가 찾은 것이 그대로 있다(보고서 report-2026-09-10-check-derives-a-three-year-agenda-twice). 다음 이슈 후보"],
        ["<b>루프는 하나다</b> (기록 231)",
         "<code>RunLoop.run</code>: datamodel 06 #7738 (market None, handle ×16) · factor 08 #8236 (×20) · stop-loss 10 #12751 (×74) · enhanced 12 #8533 (×18). 조립은 <code>datamodel_loop</code> #7622 · <code>strategy_loop</code> #8154 · #12507 · #8457; 앞에 <code>_horizon</code> #7603 · #7835 · #12188 · #8138",
         "무엇이 다른지는 Part와 시장 시계의 유무뿐이다. store는 넷 다 같은 horizon 인자를 받는다"],
        ["<b>memory는 복원 → 정규화 → publish</b>",
         "10: <code>_restore_callback_state</code> #13345 → decide #13438 → <code>_candidate_callback_state</code> #14667(<code>normalize_memory</code> #14668) → <code>publish</code> #15085; 매 콜백 같은 순서(#16971 → #17066 → …)",
         "전략이 self에 둔 다른 것은 record가 재현하지 못한다. 첫 콜백은 {}"],
        ["cold 읽기가 절대치를 지배한다",
         "등록의 명단 #46 14,246 ms(CIFS 위의 첫 parquet) · datamodel 첫 compute #7923 1,395 ms(스캔 500 + numpy 첫 블록 800) · 두 번째부터 한 자릿수 ms · worker(16)의 첫 decide 73 ms",
         "판끼리 절대치를 비교하지 말 것. 구조의 값은 상대 비교에 있다"],
    ],
}
