# ruff: noqa: E501, RUF001 -- prose data: long lines and typographic characters are the content
# The 0.14.2 scenario stepper: the owner's six scenarios and the `--jobs` batch, traced again on the
# 0.14.2 tree so the one door (`verify_run`, records 240-242) and the once-read facts (`RunFacts`,
# records 238-239) show where they sit. Every frame stands on a call the profiler recorded
# (traces: `README.md` beside this file; tools: `exp_230`, plus `exp_238/trace_worker.py`).
#
# Rendered by `exp_230/render.py`, which executes this file with `REPO` bound to the tree the traces
# were taken on. A frame names its trace and call index; the renderer fills in the definition line,
# the qualified name and the milliseconds from the trace, and reads the code window from the tree.
# A number that appears anywhere here appears in a trace, in a record the traced commands wrote, or
# in the output of `exp_238/probe_panel.py` / `probe_cubes.py` run on the same project.

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
    "title": "vqapr 0.14.2 시나리오 디버거",
    "storage_key": "vqapr-stepper-0142",
    "eyebrow": "vqapr 0.14.2 · develop 22b433bf (records 238–245) · 2026-09-10 · 실제 실행을 sys.setprofile로 추적한 결과",
    "h1": "vqapr 0.14.2 시나리오 디버거 — 사용자가 하는 일 여섯 가지 + 배치 하나, 프레임워크 안에서 한 프레임씩",
    "lede": (
        "<b>일곱 시나리오를 차례로 따라갑니다.</b> <code>vqapr new sample</code>이 만든 프로젝트(10종목, 2022-01-03 ~ 2024-12-30, 735세션)에서 "
        "① 데이터를 <b>등록</b>하고, ② 등록이 <b>거절</b>되는 두 경우(파일에 없는 컬럼 · 등록 뒤에 바뀐 파일)를 보고, ③ <b>DataModel</b>을 돌려 firm characteristic(5일 모멘텀)을 dataset으로 쓰고, "
        "④ 그것을 읽는 <b>factor 전략</b>(상위 3 롱 · 하위 3 숏)을 돌리고, ⑤ <b>memory</b>로 진입가를 기억하는 <b>stop-loss 전략</b>을 돌리고, ⑥ ④가 저장한 alpha 비중을 읽어 <b>enhanced index</b>를 만들고, "
        "⑦ ④와 ⑤를 <code>--jobs 2</code>로 <b>한 배치</b>에 돌립니다. 0.13.0 페이지와 같은 일곱 시나리오이고 계산된 숫자는 하나도 다르지 않습니다(record digest 83/83). 달라진 것은 <b>선언에서 run까지의 길</b>입니다: "
        "<code>check</code> · <code>run</code> · <code>--jobs</code> worker가 전부 <b>문 하나</b>(<code>verify_run</code>)를 지나고(기록 240–241), 그 문이 사실(agenda · 집행표 · horizon · import한 부품)을 <b>명령당 한 번</b> 읽고(<code>RunFacts</code>, 기록 238–240), "
        "run은 그 문이 load한 것을 <b>그대로 받아</b> 다시 import하지 않습니다(<code>RunResources</code>, 기록 242). 0.13.0의 <code>check</code>가 3년짜리 agenda를 두 번 유도하던 자리(4,271 ms · 90,168 호출)가 한 번(2,261 ms · 48,326 호출)이 된 것이 ②에 보이고, worker가 처음으로 판정을 받는 것이 ⑦에 보입니다. "
        "프레임마다 위에는 <b>지금 무슨 일이 일어나는지</b>를 보통 말로 적었고, 아래 접힌 곳에 트레이스가 기록한 호출 순서를 두었습니다. "
        "모든 <code>#idx</code>(그 명령 안에서 몇 번째 호출인지)와 <code>ms</code>는 <code>sys.setprofile</code>이 실제로 기록한 값이고, 스니펫은 그 시점의 소스 줄입니다 — "
        "상상한 것은 없습니다(<code>experiments/exp_246_the_scenario_trace_0_14_2/</code>)."
    ),
    "facts": [
        {"k": "데이터", "v": "10 × 735", "s": "종목 × 세션(등록 span). run 구간은 2022년 1~2월: datamodel 16세션 · factor 10 · stop-loss 37 · enhanced 9"},
        {"k": "문 하나", "v": "verify_run", "s": "check 03 #336 · run 06 #470 · 08 #722 · 10 #881 · 12 #1040 · worker 16 #16 — 여섯 명령이 같은 함수 하나를 지난다. 안에서 judgments(모아서 답한다)와 preflight(이름을 값으로 얼린다)가 <b>같은 RunFacts</b>를 읽는다"},
        {"k": "사실은 한 번", "v": "agenda ×1", "s": "3년 run의 check: derived_agenda 1,922 ms 한 번(0.13.0은 2,020 + 1,839 ms 두 번). factor run: judgments가 유도한 agenda를 preflight가 0.07 ms에 받는다(08 #4026)"},
        {"k": "명령 16개", "v": "호출 32 … 68,066", "s": "register 973 · register(거절) 427 · check(거절) 48,326 · register(재측정) 1,294 · run datamodel 10,336 · factor 27,853 · stop-loss 68,066 · enhanced 31,594 · list 1,081 · show 32 · <code>--jobs 2</code> 배치(driver) 3,492 · worker 26,832"},
        {"k": "panel = horizon", "v": "17 · 11 · 38 · 10 행", "s": "run마다 실제로 든 (시각 × 종목) 블록: datamodel 17×10 · factor 11×10 · stop-loss 38×10 · enhanced 10×10 + 10×10 (probe_panel.py, 0.13.0과 같다)"},
        {"k": "worker도 판정", "v": "16 #16 → #18", "s": "--jobs worker가 verify_run → judgments를 지난다. 0.13.0의 worker는 판정 없이 얼렸다(check가 거절한 run을 배치가 돌렸다, 이슈 015). cube는 그대로: sample-prices.close 735 × 10 · 58,928 B, 배치가 끝나면 없다"},
        {"k": "factor run", "v": "롱 3 · 숏 3", "s": "10세션 · 주문 73 · 체결 54 · 첫날 K000003 +23 · K000008 +8 · K000009 +94 · K000004 −55 · K000005 −19 · K000006 −12 · 비중 dataset 60행 — 0.13.0과 같은 수"},
        {"k": "stop-loss run", "v": "9 → 0", "s": "37세션 · 첫날 9종목 진입, 3% 손절이 이어져 02-22엔 K000008 하나, 02-23에 −52주 전량 매도 → 현금 84,184,068.92 (계좌 v34)"},
    ],
    "fix": (
        "<strong>시간 읽는 법.</strong> ms는 프로파일러가 켜진 채 잰 값이라 절대치는 실제보다 큽니다. 같은 트레이스 안에서 <b>서로 비교</b>만 하십시오. "
        "이 판의 프로젝트는 로컬 디스크 위에 있어 0.13.0 판(CIFS 네트워크 홈, 등록의 명단 읽기 14,246 ms)보다 절대치가 훨씬 작습니다 — 등록 전체가 1,028 ms, 그중 이 프로세스의 첫 parquet 스캔(<code>check_span</code>) 443 ms. "
        "그래서 판끼리 ms를 견주면 안 되고, <b>호출 수</b>와 <b>같은 자리의 유무</b>로 견줘야 합니다: check의 <code>derived_agenda</code>가 두 번에서 한 번이 된 것은 ms가 아니라 호출 90,168 → 48,326이 말합니다."
    ),
    "glossary_title": "이 페이지에 나오는 낱말 — 먼저 읽어 두면 편합니다",
    "glossary": [
        ("선언 (declaration)", "당신이 쓰는 YAML. \"이 parquet은 가격이다, 이 파일은 내 전략이다, 이 run은 이렇게 돌려라\"."),
        ("등록부 (workspace)", "<code>.vqapr/workspace.yaml</code>. <code>register</code>가 쓰고, 모든 명령이 맨 처음 펼쳐 읽는다. 코드에선 <code>Workspace</code>."),
        ("문 (validation door)", "<code>data/validation.py</code>. 물리 파일은 등록될 때 <b>여기서 한 번</b> 잰다(스키마 · key · span · 값 · 집행 가격 · digest). 이후의 모든 읽기는 파일 <i>내용</i>이 아니라 <i>digest</i>를 대조한다(<code>require_verified</code>). 기록 234."),
        ("문 하나 (verify_run)", "<code>flow/declaration/verify.py</code>. 등록된 run 선언에서 FrozenRun까지 가는 <b>유일한</b> 길. 판정(judgments)과 얼리기(preflight)를 한 번의 읽기로 하고 <code>RunVerdict</code>(failures · blocked · frozen · refusal · resources)를 돌려준다. <code>check</code>는 그것을 그려 주고 <code>run</code>·worker는 <code>require_ready()</code>로 받는다. 기록 240–241."),
        ("RunFacts", "verify_run 안에서 사실을 <b>한 번만</b> 읽는 그릇: agenda · 집행표 · horizon · import한 전략/거래소/규칙. 처음 물은 쪽이 읽고 나머지는 그 값을 받는다. 읽기가 실패하면 <b>같은 예외</b>가 물은 모두에게 간다. 기록 240."),
        ("RunResources", "verify_run이 load한 인스턴스와 자른 horizon을 run에 건네는 값. FrozenRun은 record 값이라 살아 있는 객체를 못 들기 때문에 따로 간다. run은 다시 import하지 않고, 다른 run의 것이면 거절한다. 기록 242."),
        ("digest · 측정된 반쪽", "파일 바이트의 sha256. 등록의 선언된 반쪽(컬럼 · key · grain)은 사용자의 것, 측정된 반쪽(span · digest · 집행 가격)은 문의 것. 파일이 바뀌면 같은 선언으로 다시 등록해 측정만 갈아 끼운다."),
        ("검사·판정 (check · judgment)", "\"이 run을 돌려도 되나\"에 대한 예/아니오 하나하나. <code>check</code>는 모아서 답하고, <code>run</code>은 첫 거절에서 멈춘다. 답하지 못한 판정은 <code>judgment.blocked</code>로 원인 예외를 통째로 든다."),
        ("얼리기 (freeze → FrozenRun)", "등록부에 적힌 <i>이름</i>들을 <i>실제 값</i>(코드 fingerprint, parquet 경로와 digest, 결정 시각들, 초기 계좌)으로 풀어 묶은 불변 스냅샷. 이 뒤로 등록부가 바뀌어도 run은 이것만 본다."),
        ("horizon (run의 지평)", "<code>[start, end]</code>. store가 이것을 들고, panel은 \"start에서 가장 이른 lookback 하한 ~ end\"만 스캔한다(<code>_scan_bounds</code>). 기록 235."),
        ("창 (window) · matrix() · 블록", "한 alias의 한 필드를 <i>시각 × 종목</i>으로 본 것. panel은 숫자 필드마다 float64 행렬 <b>한 벌</b>(블록)을 들고, <code>window.matrix()</code>는 그 행렬의 <b>view</b>(복사 없음, 마지막 행이 최신, 없는 값은 NaN)다. 기록 232 · 235."),
        ("cube", "<code>--jobs</code> 배치가 dataset마다 굽는 디렉터리: 숫자 필드마다 <code>.npy</code> 하나(전 종목 × 등록 span) + <code>instants.npy</code> + <code>instruments.json</code> + <code>present.npy</code> + <code>cube.json</code>(원천 digest). worker는 <code>np.load(mmap_mode='r')</code>로 map 하고, 배치가 끝나면 디렉터리는 지워진다. 기록 236."),
        ("전략 시계 · 시장 시계", "agenda가 만드는 결정 시각(매일 08:00 또는 09:00)과 집행표에 행이 있는 시각(매일 15:30). 결정은 앞에서, 체결·평가·판정은 뒤에서만. 트레이스의 시장 시각은 UTC로 찍힌다(06:30 = 15:30 KST)."),
        ("DataModel · materialized dataset", "세션마다 종목별 행을 돌려주는 모델. run이 끝나면 그 행들이 <code>.vqapr/materialized/&lt;writes&gt;/all.parquet</code>이 되고 <b>같은 문을 지나</b> dataset으로 등록된다. 다음 run은 벤더 표와 똑같이 읽는다."),
        ("writes · 배분 dataset", "전략 run도 자기 비중(<code>vqapr.weight</code>)을 <code>writes</code>가 이름한 dataset으로 낸다. 다른 run이 그것을 alpha로 읽을 수 있다(⑥)."),
        ("memory", "전략의 <code>self.memory</code>. 엄격한 JSON. 매 <code>decide</code> 전에 복원되고 뒤에 정규화되어 publish된다. 첫 콜백엔 <code>{}</code>."),
        ("의도서 (intent) · pending", "전략이 돌려준 목표 비중에 프레임워크가 도장을 찍은 것. 체결 시각이 올 때까지 pending으로 하나만 기다린다. <code>Hold</code>면 pending 없음."),
        ("봉투 (envelope)", "모든 명령이 stdout에 내는 JSON 한 덩어리. 성공이든 거절이든 모양이 같다: <code>ok · stage · failures[code · status · requirement · observed · fix]</code>."),
    ],
}

MAP = [
    ("①", "데이터 등록", "선언 → 문 → 등록부"),
    ("②", "등록 오류", "없는 컬럼 · 바뀐 파일 · 문 하나"),
    ("③", "DataModel", "verify_run → horizon panel → dataset"),
    ("④", "factor 전략", "RunFacts · RunResources · 롱 3 숏 3"),
    ("⑤", "stop-loss", "memory가 진입가를 든다"),
    ("⑥", "enhanced index", "저장된 alpha를 읽는다"),
    ("⑦", "--jobs 배치", "worker도 판정 · cube 한 번"),
]

SCENES = [
    # ---------------------------------------------------------------- ① register
    {
        "id": "reg", "key": "①", "title": "데이터 등록",
        "sub": "vqapr register sample.yaml · 1,028 ms · 973 호출 (0.13.0과 같은 973 호출 — 등록은 바뀌지 않았다)",
        "story": (
            "<b>지금 하는 일:</b> 당신이 <code>sample.yaml</code>을 건넨다. 거기엔 종목 명단, 가격 parquet(<code>sample-prices</code>), 집행표 parquet(<code>sample-execution</code>), 전략 코드, 거래소 코드, run 하나가 적혀 있다. "
            "vqapr은 이 문서를 그대로 믿지 않는다 — parquet을 <b>한 문에서 실제로 열어</b> 선언과 맞는지 재고 digest를 남기고, 전략과 거래소 코드를 <b>실제로 import</b>해 계약대로인지 본 뒤, "
            "그제야 등록부(<code>.vqapr/workspace.yaml</code>) 한 파일을 쓴다. 이 페이지의 다른 여섯 시나리오는 전부 이 등록부 위에서 일어난다. 0.13.0과 같은 973 호출, 같은 순서다 — 0.14.x는 등록을 건드리지 않았다."
        ),
        "frames": [
            F("01_register", 0, "명령줄이 register 핸들러를 고른다",
              "<code>vqapr --project-root sample register sample.yaml</code>. argparse가 verb를 고르고 프로젝트 루트를 정한 뒤 핸들러를 부른다. 1,028 ms의 거의 전부(1,009.9 ms)는 핸들러 안에서 보낸다. 무엇이 잘못되든 결과는 같은 모양의 JSON 봉투다.",
              "<code>build_parser</code>(#1, 14.1 ms) → <code>_resolve_project_root</code>(#10) → <code>register.run</code>(#11, 1,009.9 ms) → <code>read_yaml_mapping</code>(#12, 21.6 ms) → <code>apply</code>(#13, 988.1 ms).",
              fn="main() → register.run()", code=at("src/vqapr/cli/main.py", "def main(", 14),
              mem={"argv": "['--project-root', '.../sample', 'register', '.../sample/sample.yaml']"}, disk={".vqapr/": "없음"}),
            F("01_register", 14, "트랜잭션을 열고, 섹션을 정해진 순서로 처리한다",
              "모르는 섹션 이름이 있으면 여기서 이름을 대며 거절한다(#25). 그 다음 <b>트랜잭션</b>을 연다 — 등록부의 스냅샷 위에 하나씩 올려 두었다가 맨 끝에 한 번에 쓰는 장치. 디스크는 아직 그대로다. "
              "처리 순서는 instruments → datasets → components → runs: 뒤의 것이 앞의 것을 이름으로 가리키기 때문이다(run은 전략 id와 dataset id를 든다).",
              "<code>Workspace.transaction</code>(#15, 0.6 ms) → <code>_require_declared_ids</code>(#25) → <code>_instruments</code>(#43, 354.5 ms) → datasets(#136 · #328) → components(#468 · #614) → runs(#877) → <code>commit</code>(#902).",
              fn="_apply() — 섹션 순서", code=at("src/vqapr/project/registration.py", 'for dataset_id, body in section("datasets")', 7),
              mem={"document": "dict (instruments 1, datasets 2, components 2, runs 1)", "transaction.staged": "[]"}),
            F("01_register", 46, "종목 명단도 같은 문을 지난다 — verify_roster",
              "명단 parquet(<code>instruments_stock.parquet</code>)은 문의 <code>verify_roster</code>가 연다. 없는 파일이나 컬럼이 빠진 표는 raise가 아니라 <b>Diagnosis</b>(<code>roster.table_missing</code> · <code>roster.table_invalid</code>)로 돌아와 다른 거절 옆에 놓인다. "
              "이 프로세스에서 pyarrow로 parquet을 처음 여는 호출이라 351.0 ms — 10행짜리 표의 값이 아니라 첫 읽기의 값이다. 10종목이 <code>InstrumentRoster</code>가 되고 트랜잭션에 올라간다.",
              "<code>verify_roster</code>(#46, 351.0 ms) → <code>Diagnosis.ok</code>(#49) → <code>build_roster</code>(#50, 1.5 ms: <code>instrument</code> ×10) → <code>Transaction.register_instruments</code>(#83).",
              fn="verify_roster()", code=at("src/vqapr/data/validation.py", "def verify_roster", 12),
              mem={"transaction.staged": "[instruments: stock 10, digest 875b5fe1…]"}),
            F("01_register", 136, "가격 parquet을 열어 여섯 가지를 잰다 — verify_source",
              "선언은 \"<code>available_at</code>이 시각이고 <code>close</code>가 DOUBLE이고 (시각, 종목)이 유일하다\"고 말한다. 문은 믿지 않고 파일을 열어 순서대로 묻는다: "
              "<b>스키마</b>(선언한 컬럼이 다 있고 타입이 맞나, 14.8 ms) → <b>key</b>(null · 중복, 16.0 ms) → <b>span</b>(첫 시각과 끝 시각, 443.4 ms — 이 프로세스의 첫 duckdb 스캔) → <b>값</b>(DOUBLE에 NaN · Inf가 없나, 15.2 ms) → <b>집행 가격</b>(이 표엔 execution 역할이 없어 0.002 ms) → <b>digest</b>(바이트의 sha256, 0.5 ms). "
              "돌아오는 등록은 span과 <code>source_digest</code>를 든다. 여기가 이 파일이 <b>내용으로</b> 검사되는 유일한 자리다 — 뒤의 모든 명령은 digest만 대조한다.",
              "<code>verify_source</code>(#136, 504.6 ms) → <code>describe</code>(#137, 13.7 ms) → <code>check_schema</code>(#149) → <code>check_key</code>(#192) → <code>check_span</code>(#213) → <code>check_values</code>(#224) → <code>check_execution_prices</code>(#276) → <code>physical_digest</code>(#278) → <code>with_verification</code>(#280) → <code>Transaction.register_dataset</code>(#282) → <code>spoken</code>(#288).",
              fn="verify_source() — 여섯 단계", code=at("src/vqapr/data/validation.py", "def verify_source", 14),
              mem={"measured.span": "2022-01-03 15:30 ~ 2024-12-30 15:30 +09:00", "measured.source_digest": "18bb7017…"}),
            F("01_register", 436, "집행표는 한 가지를 더 잰다 — 어느 가격이 거래 가능한 행마다 양수인가",
              "<code>sample-execution</code>은 <code>execution: {is_tradable}</code> 역할을 선언했다. 같은 다섯 단계 뒤에 문은 <b>후보 가격 전부</b>에 대해 \"tradable인 행마다 유한하고 양수인가\"를 한 번에 묻고(13.3 ms) 답을 <code>execution_prices</code>로 등록에 남긴다 — 여기선 <code>['close']</code>. "
              "run이 나중에 <code>trade_price: close</code>를 고르면 preflight는 이 튜플을 조회할 뿐 표를 다시 스캔하지 않는다. 두 번째 표라 스캔이 데워져 있다: 80.5 ms.",
              "<code>verify_source</code>(#328, 80.5 ms) → <code>check_schema</code>(#338, 13.0 ms) → <code>check_key</code>(#370, 14.2 ms) → <code>check_span</code>(#391, 12.2 ms) → <code>check_values</code>(#402, 14.1 ms) → <b><code>check_execution_prices</code>(#436, 13.3 ms)</b> → <code>physical_digest</code>(#453, 0.4 ms) → <code>register_dataset</code>(#459).",
              fn="check_execution_prices()", code=at("src/vqapr/data/validation.py", "def check_execution_prices", 14),
              mem={"measured.execution_prices": "('close',)", "measured.source_digest": "49e4b4ab…"}),
            F("01_register", 552, "전략과 거래소 코드는 실제로 import해서 계약을 본다",
              "<code>reversal_5d.py</code>를 fingerprint(바이트의 해시, #472)하고 import해 <code>StrategyModel</code>의 메서드 시그니처가 맞는지 본다(<code>conformance</code>, 5.5 ms). 거래소(<code>exchange.py</code>)도 같은 길(#614~#812). "
              "옛 시그니처로 쓴 규칙이 여기서 거절되는 것을 0.11.0 페이지가 보였다; 오늘은 둘 다 통과해 트랜잭션에 오른다.",
              "<code>_component</code>(#468, 10.1 ms) → <code>prepare_component</code>(#471) → <code>fingerprint_component</code>(#472, 0.4 ms) → <code>conformance</code>(#552) → <code>_check_methods</code>(#599) → <code>register_component</code>(#608) · 거래소 <code>_component</code>(#614, 11.2 ms) → <code>conformance</code>(#722, 5.8 ms) → <code>register_component</code>(#812).",
              fn="conformance()", code=("def", 10),
              mem={"transaction.staged": "[instruments, sample-prices, sample-execution, sample-reversal-5d, sample-exchange]"}),
            F("01_register", 902, "run을 올리고, 한 번에 쓴다",
              "run <code>sample-run</code>이 전략 id · dataset id · 거래소 id로 앞의 것들을 가리키고(#877), 사람 말로 푼 문장(<code>spoken</code>, #889)이 봉투에 들어간다: \"<i>dataset 'sample-prices': a row is knowable at its 'available_at' value and never earlier</i>\", \"<i>run 'sample-run' fills against dataset 'sample-execution': the first execution instant after the decision, at 15:30:00 Asia/Seoul, at its 'close' price</i>\". "
              "<code>commit</code>이 lock을 잡고 등록부를 한 번 읽고 올려 둔 것을 순서대로 합친 뒤 <b>한 번</b> 쓴다(8.9 ms). 디스크에 처음으로 <code>.vqapr/workspace.yaml</code>이 생기고, 두 dataset 항목엔 <code>source_digest</code>가, 집행표엔 <code>execution_prices: [close]</code>가 적힌다.",
              "<code>register_run</code>(#877) → <code>_merge_run</code>(#881) → <code>RunDefinition.spoken</code>(#889) → <code>Transaction.commit</code>(#902, 12.2 ms) → <code>_merge_dataset</code> ×2(#909 …) → <code>_merge_component</code> ×2(#913 …) → <code>Workspace._write</code>(#924, 8.9 ms) → <code>_write_roster</code>(#963) → <code>success</code>(#967).",
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
        "id": "err", "key": "②", "title": "등록 오류 — 그리고 문 하나",
        "sub": "register bad.yaml · 67 ms · 427 호출 (거절) — check sample-run · 2,261 ms · 48,326 호출 (거절; 0.13.0은 4,271 ms · 90,168) — register sample.yaml 다시 · 686 ms · 1,294 호출",
        "story": (
            "<b>지금 하는 일:</b> 두 가지 실수를 저지른다. 먼저 <code>bad.yaml</code>로 파일에 <b>없는 컬럼</b>(<code>adj_close</code>)을 선언한 dataset을 등록한다 — 문이 파일을 열어 보고 이름을 대며 거절하고, 등록부는 한 바이트도 바뀌지 않는다. "
            "다음엔 등록이 끝난 뒤 <code>execution.parquet</code>을 <b>다른 바이트로 덮어쓴다</b>(마지막 날을 뺀 유효한 파일). <code>check sample-run</code>은 표를 다시 스캔하지 않고 digest 하나를 대조해 <code>dataset.source_changed</code>로 막고, 고치는 법을 말한다: 같은 선언으로 다시 등록하라. 그렇게 하면 측정된 반쪽만 갈린다. "
            "<b>0.14.x에서 바뀐 자리가 이 check에 있다.</b> 0.13.0의 check는 판정(judgments)과 얼리기(preflight)가 각자 선언을 읽어 3년짜리 agenda(734세션)를 <b>두 번</b> 유도했다(2,020 + 1,839 ms). 이제 둘은 <code>verify_run</code> 문 하나 안에서 <code>RunFacts</code>를 나눠 읽고, agenda는 한 번(1,922 ms)이다 — 호출 90,168 → 48,326."
        ),
        "frames": [
            F("02_register_bad", 396, "문이 파일을 열어 선언과 대조한다 — 첫 단계에서 멈춘다",
              "<code>sample-adjusted</code>는 <code>observations.parquet</code>에 <code>adj_close</code> 컬럼이 있다고 말한다. <code>verify_source</code>가 파일의 스키마를 읽고(<code>describe</code>, 14.6 ms) <code>check_schema</code>가 선언과 맞춘다: 없다. 이 뒤의 단계(key · span · 값 · digest)는 돌지 않는다 — 스키마가 틀린 파일에 key를 묻는 것은 뜻이 없다.",
              "<code>_dataset</code>(#354) → <code>verify_source</code>(#383, 18.3 ms) → <code>describe</code>(#384, 14.6 ms) → <code>check_schema</code>(#396, 3.5 ms) → <code>Diagnosis.ok</code>(#411) = False → <code>raise_if_failed</code>(#412).",
              fn="check_schema()", code=at("src/vqapr/data/validation.py", "def check_schema", 12),
              mem={"observed": "available_at, close, high, instrument, low, open, volume"}),
            F("02_register_bad", 417, "거절은 이름 · 관찰 · 고치는 법을 든 봉투다 — 그리고 등록부는 그대로다",
              "봉투 한 장: <code>dataset.field_missing</code> (400) · requirement \"<i>fields[adj_close] declares column 'adj_close', which must exist</i>\" · observed \"<i>available_at, close, high, instrument, low, open, volume</i>\" · fix \"<i>add column 'adj_close' to the prepared source, or point fields[adj_close] at a column it already has</i>\" · source <code>datasets.sample-adjusted.fields[adj_close]</code> · cause <code>data/validation.py:153 (check_schema)</code>. "
              "<code>mutation: false</code> — 트랜잭션은 열렸지만 commit되지 않았다. exit 1.",
              "<code>raise_if_failed</code>(#412) → <code>VqaprError</code>(#413) → <code>envelope.failure</code>(#417, stage register) → <code>emit</code>(#426) → exit 1.",
              fn="envelope.failure()", code=("def", 10),
              disk={".vqapr/workspace.yaml": "바뀌지 않음 (mutation: false)"}),
            F("03_check_changed", 336, "check는 문 하나를 지난다 — verify_run (기록 240)",
              "<code>execution.parquet</code>이 다른 바이트가 된 채로 <code>check sample-run</code>. <code>check</code>는 등록부를 열고(#14, 22.6 ms) run 선언을 꺼내(#334) <b><code>verify_run</code></b>에 넘긴다. 이 함수가 0.14.0이 세운 문이다: 안에서 <code>RunFacts</code> 그릇 하나를 만들고(#337), 판정들을 <b>모아서</b> 묻고(<code>judgments</code>, #338), 이어서 얼리기를 시도한다(<code>preflight_run</code>, #48204) — 둘 다 <b>같은 그릇</b>에서 사실을 읽는다. "
              "돌아오는 <code>RunVerdict</code>는 거절(failures) · 답하지 못한 판정(blocked) · 얼린 run 또는 얼리기가 낸 예외(refusal)를 든다. check는 그것을 그려 주고, run은 <code>require_frozen()</code>으로 첫 거절에서 멈춘다. 0.13.0의 check는 #336 <code>judgments</code>와 #48202 <code>preflight_run</code>이 따로 읽었다.",
              "<code>check</code>(#12, 2,244.7 ms) → <code>Workspace.open</code>(#14, 22.6 ms) → <code>run_definition</code>(#334) → <code>verify_run</code>(#336, 2,221.2 ms) → <code>RunFacts.__init__</code>(#337) → <code>judgments</code>(#338, 2,214.9 ms) → … → <code>preflight_run</code>(#48204, 6.1 ms) → <code>Failure.as_dict</code>(#48311) → <code>emit</code>(#48325).",
              fn="verify_run() — 문 하나", code=at("src/vqapr/flow/declaration/verify.py", "facts = RunFacts(workspace, definition)", 10, before=1),
              mem={"verdict": "failures 1 (dataset.source_changed) · blocked 1 (judgment.blocked: execution_ordering) · frozen None · refusal VqaprError"}),
            F("03_check_changed", 338, "판정 하나하나가 답한다 — 사실은 RunFacts가 한 번 읽는다",
              "판정 일곱: 종목 집합(#737) · 명단(#739) · 기간(#746) · <b>집행 순서</b>(#361) · 멤버의 dataset(#45915, 106.5 ms) · 비중(#48201) · 출력(#48203). "
              "집행 순서 판정이 <code>facts.agenda()</code>를 묻자 그릇이 처음이라 <code>derived_agenda</code>를 돈다 — 3년짜리 run이라 734세션, 1,922.5 ms(그중 집행표의 시각 열 읽기 <code>evaluation_times</code> 164.7 ms, duckdb <code>distinct_values</code> 130.8 ms). 기록 237대로 <code>[start, end]</code>로 자른 뒤(<code>inclusive_slice</code>, #42204, 169.8 ms) 집행표를 묻는다(<code>facts.execution_table()</code>, #45873). "
              "그 다음 preflight가 같은 agenda를 물으면 그릇이 <b>돌려주기만</b> 한다 — 0.13.0에서 1,838.8 ms 걸리던 두 번째 유도가 이 트레이스엔 없다.",
              "<code>judgments</code>(#338) → <code>_judge_universe</code>(#737) · <code>_judge_roster</code>(#739) · <code>_judge_period</code>(#746) · <code>_judge_execution_ordering</code>(#361, 2,097.0 ms) → <code>RunFacts.agenda</code>(#362) → <code>_once</code>(#363) → <code>derived_agenda</code>(#365, 1,922.5 ms) → <code>evaluation_times</code>(#366, 164.7 ms) → <code>distinct_values</code>(#374, 130.8 ms) … <code>inclusive_slice</code>(#42204, 169.8 ms) → <code>RunFacts.execution_table</code>(#45873, 4.4 ms).",
              fn="RunFacts._once() — 한 번 읽고 나눠 준다", code=at("src/vqapr/flow/declaration/preflight.py", "def _once(", 10),
              tip="이 트레이스에서 큰 것은 표 스캔이 아니라 agenda 유도(1.9 s)다. 그것이 한 번이 된 것이 기록 240이고, 0.12.0·0.13.0 페이지가 보고서로 남겼던 \"두 번 유도\"는 닫혔다."),
            F("03_check_changed", 361, "집행 순서 판정은 run이 걷는 것과 같은 조각을 묻는다 (기록 237)",
              "이 판정은 preflight가 얼리는 것과 같은 <code>inclusive_slice(start, end)</code>를 순회한다. 0.12.0까지는 <code>derived_agenda</code>가 돌려준 <b>날짜 상위집합</b>을 그대로 돌아, end가 마지막 체결과 마지막 결정 사이(예: 16:00)에 놓인 옳은 선언에서 end 뒤의 occurrence가 <code>ValueError</code>로 죽고 500 <code>judgment.blocked</code>가 됐다(testbed 보고 099). 이 sample-run의 end는 23:59:59라 잘리는 것은 없지만, 자리 자체가 트레이스에 보인다.",
              "<code>_judge_execution_ordering</code>(#361) → <code>RunFacts.agenda</code>(#362) → … → <code>OperationAgenda.inclusive_slice</code>(#42204, 169.8 ms) → <code>RunFacts.execution_table</code>(#45873, 4.4 ms) → <code>Workspace.require_verified</code>(#45877).",
              fn="_judge_execution_ordering() — inclusive_slice", code=at("src/vqapr/flow/declaration/judgments.py", "inclusive_slice(", 12, before=3)),
            F("03_check_changed", 45888, "표를 다시 스캔하지 않는다 — digest 하나를 대조한다, 그리고 한 번만 해시한다",
              "집행표를 묶으려면 등록부에 <code>require_verified('sample-execution')</code>을 물어야 한다. 등록이 든 digest <code>49e4b4abef4f…</code>와 지금 파일의 sha256 <code>bf30cb34b1ca…</code>(0.5 ms)가 다르다 → <code>dataset.source_changed</code> (412): "
              "\"<i>the bytes a run reads must be the bytes registration measured; every fact the registration carries (span, key, prices) was measured on them</i>\", fix \"<i>register dataset 'sample-execution' again so its facts are measured on the file as it is now -- the command is `vqapr register &lt;its declaration file&gt;`</i>\"(기록 243이 명령을 적었다). "
              "그릇은 실패도 기억한다: <code>_once</code>가 예외를 저장해 두고, 뒤에 같은 사실을 묻는 preflight(#48204, 6.1 ms)에게 <b>같은 예외</b>를 다시 던진다. 0.13.0은 preflight가 한 번 더 해시했다(#90143).",
              "<code>RunFacts.execution_table</code>(#45873) → <code>Workspace.require_verified</code>(#45877, 4.2 ms) → <code>source_digest</code>(#45885) → <code>physical_digest</code>(#45886, 0.5 ms) → <code>require_verified</code>(#45888, 3.2 ms) → 거절 · 판정을 blocked로 감싼다 → <code>_judge_member_datasets</code>(#45915) … <code>preflight_run</code>(#48204, 6.1 ms: 저장된 예외).",
              fn="require_verified()", code=at("src/vqapr/data/validation.py", "def require_verified", 14),
              mem={"registered": "49e4b4abef4f…", "file now": "bf30cb34b1ca…"},
              caution="봉투: checked [workspace, run, judgments, preflight] · passed [workspace, run] · failures [dataset.source_changed] · blocked [judgment.blocked: \"execution_ordering could not answer\", cause에 예외 전체]. 판정 하나가 답하지 못하면 원인 거절은 failures에, 판정은 blocked에 둔다."),
            F("04_register_again", 643, "같은 선언으로 다시 등록한다 — 측정만 다시 한다",
              "<code>register sample.yaml</code>을 다시. 선언은 한 글자도 바뀌지 않았고 파일만 다르다. 문이 두 표를 다시 잰다(가격표 142.9 ms · 집행표 82.4 ms): span, digest(<code>bf30cb34…</code>), 집행 가격. 트랜잭션에 올라갈 때 <code>_merge_dataset</code>이 기존 등록과 비교한다.",
              "<code>_apply</code>(#14, 647.1 ms) → <code>verify_source</code>(#451, 142.9 ms) → <code>_merge_dataset</code>(#601) · <code>verify_source</code>(#643, 82.4 ms) → <code>_merge_dataset</code>(#778).",
              fn="verify_source() 다시", code=("def", 8)),
            F("04_register_again", 778, "선언된 반쪽이 같으면 측정된 반쪽을 갈아 끼운다",
              "<code>_merge_dataset</code>은 기존 등록의 span · aggregated · digest · 집행 가격을 새 측정으로 바꾼 사본이 새 등록과 <b>같은지</b> 본다. 같다 → 선언은 그대로이고 측정만 바뀐 것이니 받아들인다. 컬럼 이름 하나라도 달랐다면 <code>dataset.registered</code>(409)로 거절했을 것이다. "
              "commit이 등록부를 다시 쓴다(#1245, 8.6 ms). 이 페이지의 run들은 원본 바이트로 되돌린 뒤 한 번 더 등록한 상태(digest <code>49e4b4ab…</code>)에서 돌았다.",
              "<code>_merge_dataset</code>(#778) → … <code>Transaction.commit</code>(#1217, 12.2 ms) → <code>_merge_dataset</code> ×2(#1230 …: 재생) → <code>Workspace._write</code>(#1245) → <code>success</code>(#1288).",
              fn="_merge_dataset() — remeasured", code=at("src/vqapr/project/merge.py", "remeasured = replace(", 12, before=6),
              disk={".vqapr/workspace.yaml": "sample-execution.source_digest: 49e4b4ab… → bf30cb34… (그 뒤 원본으로 되돌려 한 번 더 등록)"}),
        ],
        "remember": [
            "등록이 거절되면 봉투가 code · requirement · observed · fix · source를 들고, 등록부는 바뀌지 않는다.",
            "check · run · worker는 verify_run 하나를 지난다. 판정과 얼리기는 RunFacts에서 사실을 나눠 읽고, 실패한 읽기도 한 번이다.",
        ],
    },
    # ---------------------------------------------------------------- ③ datamodel
    {
        "id": "dm", "key": "③", "title": "DataModel → firm characteristic",
        "sub": "register features.yaml · 71 ms · 647 호출 — run sample-features-run · 1,041 ms · 10,336 호출 · 16세션 · 108행 (0.13.0은 13,673 호출)",
        "story": (
            "<b>지금 하는 일:</b> <code>features.py</code>의 <code>SampleFeatures</code>는 세션마다 종목별 <b>5일 모멘텀</b>(여섯 종가 중 마지막 ÷ 첫 번째 − 1)을 돌려주는 DataModel이다. run은 전략 시계만 돈다(매일 16:00, 시장 시계 없음). "
            "첫 네 세션은 창이 덜 차서 빈 목록, 2022-01-10부터 종가 여섯 개가 다 있는 종목당 한 행(K000010은 이 구간에 여섯 종가가 없어 행이 없다). run이 끝나면 108행(12세션 × 9종목)이 <code>.vqapr/materialized/sample-features/all.parquet</code>이 되고 <b>①과 같은 문</b>을 지나 dataset <code>sample-features</code>로 등록된다. "
            "run의 앞부분이 0.13.0과 다르다: <code>preflight_run</code>이 두 번(462 + 190 ms) 돌던 자리에 <code>verify_run</code> 한 번(251.6 ms)이 있고, 그 안의 얼리기는 11.9 ms다. 루프 안은 그대로다 — panel 17 × 10, 첫 compute만 무겁고 나머지는 2 ms."
        ),
        "frames": [
            F("06_run_features", 470, "run도 같은 문을 지난다 — verify_run, 그리고 얼리기는 판정이 읽은 것을 받는다",
              "<code>run sample-features-run</code>. 등록부를 열고 선언을 꺼낸 뒤 <code>verify_run</code>(251.6 ms): 판정들이 239.0 ms(그중 agenda 유도 — 이 run은 16세션이라 짧다), 얼리기가 11.9 ms. 0.13.0에서는 <code>preflight_run</code>이 판정을 위해 한 번(462.4 ms), 얼리기 위해 또 한 번(190.5 ms) 선언을 읽었다. "
              "<code>_freeze_datamodel</code>(#3914)이 모델을 import해 <code>inputs()</code>를 묻고 — 이 import도 <code>RunFacts.component</code>를 지나므로 판정이 이미 import한 인스턴스다 — 읽을 dataset을 <code>_freeze_sources</code>로 묶는다.",
              "<code>_run_one</code>(#12) → <code>Workspace.open</code>(#14) → <code>run_definition</code> → <code>verify_run</code>(#470, 251.6 ms) → <code>judgments</code>(#472, 239.0 ms) → <code>preflight_run</code>(#3902, 11.9 ms) → <code>_freeze_datamodel</code>(#3914, 8.3 ms) → <code>_freeze_sources</code>(#4107, 1.6 ms).",
              fn="verify_run()", code=at("src/vqapr/flow/declaration/verify.py", "facts = RunFacts(workspace, definition)", 10, before=1)),
            F("06_run_features", 4120, "얼리기 — 읽을 dataset의 identity를 대조한다",
              "이 모델이 읽는 <code>sample-prices</code>는 <code>require_verified</code> 한 번(1.2 ms, 그중 sha256): 등록의 digest와 파일이 같다. FrozenRun에 그 digest가 들어간다(<code>source_digests</code>). 파일 내용은 여기서도 읽지 않는다 — ①에서 잰 것을 대조할 뿐이다.",
              "<code>_freeze_sources</code>(#4107) → <code>_validate_requirement</code> → <code>Workspace.require_verified</code>(#4109, 1.2 ms) → <code>require_verified</code>(#4120, 0.05 ms).",
              fn="require_verified()", code=at("src/vqapr/data/validation.py", "def require_verified", 14),
              mem={"frozen.source_digests": "{sample-prices-source: 18bb7017…}"}),
            F("06_run_features", 4160, "RunResources — 문이 load한 것을 run이 받는다 (기록 242)",
              "얼린 run(<code>FrozenRun</code>)은 record 값이라 살아 있는 모델 인스턴스를 들 수 없다. 0.14.0까지 run은 그래서 시작하면서 모델을 <b>다시 import</b>했다. 이제 <code>RunResources.of</code>가 <code>RunFacts</code>가 이미 든 인스턴스(datamodel)와 horizon을 한 값에 담고(0.4 ms — 아무것도 load하지 않는다), <code>require_ready()</code>가 (frozen, resources) 쌍을 돌려주면 <code>orchestration.run</code>이 그것을 그대로 쓴다. 다른 run의 것이면 거절한다(<code>run_identity</code>).",
              "<code>RunResources.of</code>(#4160, 0.4 ms) → <code>RunVerdict.require_ready</code>(#4168) → <code>run</code>(#4170, 745.5 ms, resources=…) → <code>_own_output_or_refuse</code> → <code>_run_datamodels</code>(#4178) → <code>_run_datamodel</code>(#4225) → <code>_run_member</code>(#4263, 735.1 ms, member_kind='datamodel').",
              fn="RunResources.of()", code=at("src/vqapr/flow/declaration/verify.py", "def of(cls, facts: RunFacts, frozen: FrozenRun)", 12),
              mem={"resources": "datamodel=SampleFeatures 인스턴스(판정이 import한 것) · strategy None · exchange None · horizon None(datamodel run)"}),
            F("06_run_features", 4266, "store가 run의 horizon을 든다 (기록 235)",
              "<code>_run_member</code>가 멤버 하나의 자원(스캔 세션 · store · writer · 창)을 만든다. store는 <code>horizon=(start, end)</code> — 얼린 run의 기간 — 와 run이 선언한 <code>requirements</code> 전부를 받고, 뒤의 모든 panel 스캔은 이 둘로 잘린다. 단일 run이라 <code>cubes=None</code>: 스캔 경로 그대로(⑦에서 달라진다).",
              "<code>_run_member</code>(#4263) → <code>_horizon</code>(#4266) → <code>DuckDbObservationStore.__init__</code> → <code>body</code>(#4278, 729.3 ms) → <code>RunOutput.__init__</code>(#4281) → <code>datamodel_loop</code>(#4285).",
              fn="_horizon() → DuckDbObservationStore(horizon=…)", code=at("src/vqapr/flow/orchestration.py", "horizon=_horizon(frozen)", 10, before=4),
              mem={"horizon": "(2022-01-04 00:00, 2022-01-25 23:00) +09:00", "requirements": "[sample-prices.close, RowsLookback(rows=6)]"}),
            F("06_run_features", 4285, "같은 RunLoop, 시장 시계 없이",
              "<code>datamodel_loop</code>가 <code>RunLoop(part=DataModelPart, market=None)</code>을 조립한다. 전략 run과 같은 클래스 — 다른 것은 Part와 시장 시계뿐이다(기록 231). <code>RunLoop.run</code>이 <code>start</code>(cutoff 01-04 00:00)로 열고 <code>events</code>가 16개의 결정 시각을 낸 뒤 <code>handle</code> ×16.",
              "<code>datamodel_loop</code>(#4285, 4.9 ms) → <code>RunLoop.__init__</code>(#4399) → <code>RunLoop.run</code>(#4401, 621.7 ms) → <code>start</code>(#4402) → <code>RunOutput.open</code>(#4405 근처) → <code>events</code>(#4405) → <code>RunLoop.handle</code> ×16 (#4543 …) → <code>finish</code>(#9904).",
              fn="datamodel_loop()", code=at("src/vqapr/flow/run/loop.py", "def datamodel_loop", 12)),
            F("06_run_features", 4622, "첫 창 — 스캔 범위는 등록 span이 아니라 horizon + lookback",
              "2022-01-04 16:00, 첫 <code>context.read('prices', 'close')</code>. store는 panel을 만들기 전에 <b>어디까지 읽을지</b>를 정한다: run의 start(01-04)에서 <code>RowsLookback(rows=6)</code>이 닿는 가장 이른 시각을 원천의 시각 격자에서 센다(53.6 ms — 이 프로세스에 처음). 격자에 01-04 앞 행은 01-03 15:30 하나뿐이라 하한은 그것이고, 상한은 end(01-25 23:00). 그 사이만 <code>observation_table</code>이 스캔한다(336.6 ms, 첫 duckdb 스캔).",
              "<code>compute</code>(#4586) → <code>_DeclaredReads.read</code>(#4587) → <code>ModelWindow.panel</code>(#4606) → <code>panel_window</code>(#4607, 407.8 ms) → <code>_scan_bounds</code>(#4622, 53.6 ms) → <code>observation_table</code>(#5370, 336.6 ms) → <code>Panel.from_table</code>(#5407).",
              fn="_scan_bounds() — lookback 하한", code=at("src/vqapr/data/store.py", "for lookback in lookbacks:", 10, before=2),
              mem={"bounds": "2022-01-03 15:30 ~ 2022-01-25 23:00 +09:00 (probe_panel.py로 잰 값)"}),
            F("06_run_features", 5407, "panel은 숫자 필드마다 float64 블록 한 벌 — 17 × 10",
              "스캔이 돌려준 Arrow 표(available_at · instrument · close)를 <code>placement</code>가 (시각, 종목) 정수 쌍으로 배치하고(7.2 ms) <code>dense_block</code>이 (17 × 10) float64 행렬 하나로 접는다 — 없는 칸은 NaN. <code>window.matrix()</code>는 그 행렬의 행 slice(view)다. 0.13.0 판의 같은 자리는 800 ms였다(CIFS 위 numpy 첫 블록); 구조는 같다.",
              "<code>Panel.from_table</code>(#5407, 15.5 ms) → <code>placement</code>(#5408, 7.2 ms) → <code>dense_block</code>(#5410, rows=array([0, 0, …, 1, 1, …])) → <code>PanelWindow.matrix</code>(#5419, 0.09 ms).",
              fn="Panel.from_table() — 블록", code=at("src/vqapr/data/panel.py", "blocks[name] = dense_block(", 10, before=6),
              mem={"panel.blocks['close'].shape": "(17, 10)", "panel.bounds": "01-03 15:30 ~ 01-25 23:00"}),
            F("06_run_features", 4586, "첫 세션 — 창을 행렬로 읽고, 아직 여섯 행이 아니라 빈 목록",
              "<code>window.matrix()</code>는 블록의 행 slice — view — 다: 01-04 16:00에 알 수 있는 행은 2개(01-03 · 01-04)라 <code>closes.shape == (2, 10)</code>. <code>LOOKBACK=6</code>에 못 미쳐 <code>[]</code>를 돌려준다. 프레임워크는 빈 목록을 그대로 받는다(<code>rows=[]</code>). "
              "이 compute 409.0 ms의 거의 전부가 위의 첫 스캔이다; 다음 세션의 compute는 2.3 ms(#5475).",
              "<code>RunLoop.handle</code>(#4543, 411.2 ms) → <code>DataModelPart.dispatch</code> → <code>_window_factory.at</code>(#4550, 01-04 16:00) → <code>SampleFeatures.compute</code>(#4586, 409.0 ms) → … → <code>PanelWindow.matrix</code>(#5419) → <code>RunOutput.append</code>(#5427, rows=[]).",
              fn="SampleFeatures.compute() — 저자 코드", code=at(DECL + "features.py", "closes = window.matrix()", 12, before=1), author=True,
              mem={"closes.shape": "(2, 10) — 세션 2 × 종목 10", "returned": "[]"}),
            F("06_run_features", 5784, "다섯 번째 세션 — 종목 9개의 모멘텀을 한 식으로",
              "2022-01-10 16:00. 창에 여섯 행이 찼다. <code>closes[-1] / closes[0] - 1.0</code>가 열마다(=종목마다) 한 번에 계산되고, 여섯 값이 다 있는 열만 행으로 나간다: 9행(K000010은 열이 비어 빠진다). 이번 compute는 2.3 ms. "
              "<code>available_at</code>은 저자가 아니라 프레임워크가 찍는다(16:00, 이 세션의 평가 시각): 이 값은 <b>이 시각에야</b> 알 수 있는 값이다.",
              "<code>RunLoop.handle</code>(#5741, 14.5 ms) → <code>_window_factory.at</code>(#5748, 01-10 16:00) → <code>compute</code>(#5784, 2.3 ms) → <code>RunOutput.append</code>(#6083, 0.3 ms, rows=[{available_at: 2022-01-10 16:00+09:00, instrument: 'K000001', momentum_5d: …}, …]).",
              fn="SampleFeatures.compute() — 행 9", code=at(DECL + "features.py", "momentum = closes[-1]", 8, before=2), author=True,
              mem={"rows this session": "9", "rows so far": "9 → 세션 16에서 108"}),
            F("06_run_features", 9938, "출력이 dataset이 된다 — 같은 문을 지나서",
              "16세션이 끝나면 <code>RunOutput.register</code>가 모은 행을 <code>all.parquet</code>으로 굳히고(<code>_seal</code>, 3.9 ms) 그 파일을 <b>①의 <code>verify_source</code>에 그대로</b> 넣는다(68.9 ms): 스키마 · key(available_at, instrument) · span(01-10 16:00 ~ 01-25 16:00) · 값 · digest <code>54f8fd04…</code>. 통과하면 등록부에 <code>sample-features</code>가 <code>produced_by: sample-features-run</code>, <code>produced_by_record: sample-features@20c2acad</code>와 함께 적힌다. "
              "프레임워크가 쓴 표라고 문을 건너뛰지 않는다. 그 다음 record(<code>datamodel.json</code>)를 얼리고 봉투는 rows 108 · sessions 16을 말한다.",
              "<code>RunLoop.finish</code>(#9904) → <code>RunOutput.register</code>(#9938, 89.0 ms) → <code>_seal</code>(#9967, 3.9 ms) → <code>verify_source</code>(#9969, 68.9 ms) → <code>Transaction.commit</code>(#10100, 12.9 ms) → <code>freeze_datamodel_record</code>(#10167, 11.9 ms) → <code>RunRecordWriter._seal</code>(#10309) → <code>read_datamodel_record</code>(#10323) → <code>success</code>(#10330).",
              fn="RunOutput.register()", code=("def", 14),
              disk={".vqapr/materialized/sample-features/all.parquet": "108행 (available_at · instrument · momentum_5d)", ".vqapr/runs/sample-features-run/": "run.json · datamodels/sample-features@20c2acad/datamodel.json", ".vqapr/workspace.yaml": "datasets + sample-features (source_digest 54f8fd04…)"}),
        ],
        "remember": [
            "run의 앞부분은 verify_run 한 번이다: 판정이 import한 모델을 얼리기가 받고, RunResources로 run에 간다.",
            "panel은 run의 horizon + lookback만큼만 스캔된다. 출력 parquet도 등록될 때 같은 문을 지난다.",
        ],
    },
    # ---------------------------------------------------------------- ④ factor strategy
    {
        "id": "factor", "key": "④", "title": "factor 전략",
        "sub": "register factor.yaml · 99 ms · 1,058 호출 — run sample-factor-run · 2,252 ms · 27,853 호출 · 10세션 · 이벤트 20 (0.13.0은 31,759 호출)",
        "story": (
            "<b>지금 하는 일:</b> <code>factor.py</code>의 <code>SampleFactor</code>는 ③이 만든 <code>sample-features.momentum_5d</code>를 <b>벤더 표처럼</b> 한 줄로 선언해 읽고(최신 행 하나), 상위 3종목 롱 · 하위 3종목 숏, 각 1/6씩(달러 중립, <code>Rebalance.signed</code>)을 돌려준다. "
            "숏이 있으니 거래소는 SIGNED 상장이 필요하다 — <code>exchange_signed.py</code>가 같은 열 종목을 <code>ListingAccess.SIGNED</code>로 든다. run은 2022-01-12 ~ 01-25, 계좌 mode SIGNED. 끝나면 비중이 <code>sample-factor-weights</code>로 저장된다(⑥이 읽는다). "
            "전략 run에서 <code>RunFacts</code>가 아끼는 것이 가장 잘 보인다: 0.13.0의 이 run은 집행표의 시각 열을 다섯 번 읽고 전략을 네 번 import했다(exp_238). 이제 판정이 유도한 agenda를 얼리기가 0.07 ms에 받고(#4026), 문이 import한 전략 · 거래소 · horizon을 run이 그대로 받는다(#4471)."
        ),
        "frames": [
            F("08_run_factor", 722, "verify_run — 판정이 읽고, 얼리기는 받는다",
              "판정 일곱 중 무거운 것은 집행 순서(#748, 264.0 ms: agenda 유도 251.8 ms — 이 run은 10세션이지만 3년 집행표의 시각 열을 한 번은 읽는다). 이어서 <code>preflight_run</code>(#4022)이 <b>25.1 ms</b>에 끝난다: <code>RunFacts.agenda</code>(#4026)가 0.07 ms — 그릇이 이미 들고 있다. 얼리기 안에서 전략을 얼리며(<code>_freeze_strategy</code>, 17.8 ms) 초기 memory를 새 인스턴스에 증명하고(<code>_validate_initial_model_state</code>) 요구를 묻고(<code>Component.requirements</code>) agenda와 체결 목표를 얼린다.",
              "<code>verify_run</code>(#722, 305.1 ms) → <code>judgments</code>(#724, 279.0 ms) → <code>_judge_execution_ordering</code>(#748, 264.0 ms) → <code>derived_agenda</code>(#752, 251.8 ms) · <code>_judge_member_datasets</code>(#3804, 7.4 ms) · <code>_judge_weights</code>(#3931) · <code>_judge_outputs</code>(#4021) → <code>preflight_run</code>(#4022, 25.1 ms) → <code>RunFacts.agenda</code>(#4026, 0.07 ms) → <code>_freeze_strategy</code>(#4070, 17.8 ms) → <code>_validate_initial_model_state</code>(#4077) → <code>Component.requirements</code>(#4131) → <code>_freeze_agenda</code>(#4167) → <code>_validate_execution_targets</code>(#4255).",
              fn="verify_run()", code=("def", 16),
              mem={"facts settled": "agenda · execution_table · horizon · component:sample-factor · exchange"}),
            F("08_run_factor", 4410, "얼리기 — 읽을 dataset과 집행표를 identity로 묶는다",
              "이 전략이 읽는 <code>sample-features</code>는 다른 run이 쓴 표지만 얼리기엔 다른 dataset과 똑같다: <code>require_verified</code>(1.6 ms). 집행표는 등록의 <code>execution_prices=['close']</code>에 <code>trade_price: close</code>가 있는지 <b>튜플 조회</b>로 본다. 얼린 run은 digest들(집행표 · feature 표)을 들고 <code>FrozenRun.__post_init__</code>이 불변식을 검사한다.",
              "<code>_freeze_sources</code>(#4409, 2.3 ms) → <code>_validate_requirement</code>(#4410) → <code>Workspace.require_verified</code>(#4411, 1.6 ms) → <code>Workspace.dataset</code> → <code>source_digest</code> ×2 → <code>FrozenRun.__post_init__</code>(#4443, 1.3 ms).",
              fn="_validate_requirement()", code=at("src/vqapr/flow/declaration/preflight.py", "def _validate_requirement", 14)),
            F("08_run_factor", 4471, "RunResources — 전략 · 거래소 · horizon을 다시 만들지 않는다 (기록 242)",
              "<code>RunResources.of</code>가 그릇에서 전략 인스턴스 · 거래소 · 규칙(없음) · horizon을 꺼내 한 값에 담는다 — 세 번의 <code>RunFacts._once</code>가 각각 0.06 ms, 즉 load가 아니라 조회다. 0.14.0까지 run은 여기서 전략을 다시 import하고 첫 의도서에서 집행표를 다시 스캔해 horizon을 잘랐다. <code>require_ready</code>가 (frozen, resources)를 주고 <code>orchestration.run</code>이 받는다.",
              "<code>RunResources.of</code>(#4471, 0.8 ms) → <code>FrozenRun.identity</code>(#4472) → <code>RunFacts.component</code>(#4478, 0.06 ms) · <code>exchange</code>(#4480) · <code>horizon</code>(#4483) → <code>RunVerdict.require_ready</code>(#4485) → <code>run</code>(#4487, 1,865.1 ms).",
              fn="RunResources.of()", code=at("src/vqapr/flow/declaration/verify.py", "def of(cls, facts: RunFacts, frozen: FrozenRun)", 12),
              mem={"resources": "strategy=SampleFactor · exchange=AcademicExchange(SIGNED) · rules=() · horizon=01-12 15:30 ~ 01-25 15:30"}),
            F("08_run_factor", 4496, "run 시작 — 명단은 얼리지 않고 그때그때 읽는다",
              "run이 시작하며 <code>registered_roster</code>가 명단을 <b>새로</b> 읽는다(407.2 ms, 그중 <code>verify_roster</code>의 parquet 읽기 404.5 ms — 이 프로세스의 첫 pyarrow 읽기라 무겁다; ⑦의 worker에선 같은 자리가 19.9 ms). 얼리지 않는 것은 설계다(이슈 009): 명단은 매일 자라고, 새 이름을 만지지 않는 run까지 아침마다 거절할 이유가 없다. 대신 record가 그날의 digest를 적는다. 이 뒤 <code>_run_strategy</code> → <code>_run_member</code>가 계좌(v0, cash 100,000,000, SIGNED) · 규칙 자리 · 루프를 조립한다.",
              "<code>run</code>(#4487) → <code>_own_output_or_refuse</code>(#4489) → <code>registered_roster</code>(#4496, 407.2 ms) → <code>verify_roster</code>(#4502, 404.5 ms) → <code>build_roster</code>(#4506) → <code>_run_strategy</code>(#4616, 1,446.7 ms) → <code>_run_member</code>(#4678, 1,442.9 ms) → <code>Account.__init__</code>(#4999) → <code>ComplianceHandler.__init__</code>(#5077) → <code>RunLoop.__init__</code>(#5079) → <code>Account.bind</code>(#5081) → <code>RunLoop.run</code>(#5082, 1,268.3 ms).",
              fn="registered_roster()", code=at("src/vqapr/flow/roster.py", "def registered_roster", 12),
              tip="단일 프로세스 run 셋(08 · 10 · 12)에서 이 자리는 각각 407 · 354 · 358 ms로, 루프 밖에서 가장 큰 항목이다. 값이 아니라 첫 pyarrow 읽기의 비용이고, 설계상 매 run 읽는다."),
            F("08_run_factor", 5410, "아침 8시 — feature 표의 스캔 범위: 한 행 앞부터 end까지",
              "2022-01-12 08:00, 첫 <code>call.read('features', 'momentum_5d')</code>. lookback이 <code>RowsLookback(rows=1)</code>이니 store는 start(01-12) 앞의 격자 한 칸 — 01-11 16:00 — 을 하한으로, end(01-25 23:59:59)를 상한으로 잡고(16.6 ms) 그 사이만 스캔한다(5.6 ms). panel은 (11 × 10) 블록 하나(1.4 ms).",
              "<code>decide</code>(#5368) → <code>panel_window</code> → <code>_scan_bounds</code>(#5410, 16.6 ms) → <code>observation_table</code>(#5435, 5.6 ms) → <code>Panel.from_table</code>(#5472, 1.4 ms) → <code>PanelWindow.matrix</code>.",
              fn="_scan_bounds()", code=("def", 12),
              mem={"bounds": "2022-01-11 16:00 ~ 2022-01-25 23:59:59 +09:00", "panel.blocks['momentum_5d'].shape": "(11, 10)"}),
            F("08_run_factor", 5368, "feature 한 행을 읽고 여섯 이름을 고른다",
              "창은 01-11 16:00의 행(전날 저녁에 알 수 있던 값) 하나 × 종목 10. 정렬해서 하위 3(K000004 · K000005 · K000006)에 −1/6, 상위 3(K000003 · K000008 · K000009)에 +1/6. "
              "<code>Rebalance.signed(weights, gross=1)</code>: 부호가 방향이고 gross 1이면 롱 0.5 · 숏 0.5. 이 decide는 33.3 ms(feature 표 첫 스캔 포함), 다음 날은 7.2 ms(#7549). 돌아온 의도서에 도장을 찍고(<code>_stamp_intent</code>) 받아들여(<code>_accept_intent</code>) 계좌 · memory · pending을 한 번에 publish한다.",
              "<code>RunLoop.handle</code>(#5248, 67.1 ms, agenda 01-12 08:00) → <code>StrategyPart.dispatch</code>(#5249) → <code>CallbackHandler.dispatch</code>(#5251) → <code>SampleFactor.decide</code>(#5368, 33.3 ms) → <code>_stamp_intent</code>(#5598, 5.9 ms) → <code>_accept_intent</code>(#5764) → <code>RunStateRepository.publish</code>(#6059, 3.6 ms).",
              fn="SampleFactor.decide() — 저자 코드", code=at(DECL + "factor.py", "ranked = sorted(", 10, before=3), author=True,
              mem={"weights": "K000003 +0.1667 · K000008 +0.1667 · K000009 +0.1667 · K000004 −0.1667 · K000005 −0.1667 · K000006 −0.1667", "pending": "intent 1 (계좌 v0 기준)"}),
            F("08_run_factor", 6106, "오후 3시 반 — 숏 셋이 실제로 팔린다",
              "시장 시계 01-12 15:30(트레이스엔 UTC 06:30). pending 의도서가 due가 되고 <code>ExecutionHandler.fill</code>이 주문을 계획한다(<code>plan_orders</code>, 16.1 ms: 비중 → 수량, 정수 주). SIGNED 상장이라 음수 수량이 통과한다. 체결: K000003 +23 · K000008 +8 · K000009 +94, K000004 <b>−55</b> · K000005 <b>−19</b> · K000006 <b>−12</b> (close 가격, 학술 프로파일이라 수수료 0). 계좌 v1: 현금 99,463,501.24, NAV 100,000,000.",
              "<code>RunLoop.handle</code>(#6098, 73.2 ms, MarketEvent) → <code>MarketClock.at</code>(#6099) → <code>fill</code>(#6106, 50.9 ms) → <code>plan_orders</code>(#6194, 16.1 ms) → <code>AcademicExchange.execute</code>(#6574, 8.8 ms) → <code>Account.append</code>(#6819, 1.2 ms) → <code>commit_append</code>(#7052).",
              fn="ExecutionHandler.fill()", code=("def", 12),
              mem={"account v1": "롱 3 · 숏 3 · cash 99,463,501.24 · NAV 100,000,000.00"}),
            F("08_run_factor", 7091, "평가 → 판정 → 마감 — 규칙이 없어도 자리는 있다",
              "같은 시각에 이어서: 보유를 close로 평가하고(<code>mark</code>, 17.2 ms → <code>Account.mark</code> 1.7 ms), compliance 규칙이 없으니 <code>observe</code>는 0.003 ms. 시장 시계 한 점은 늘 이 순서(발생 → 체결 → 평가 → 판정 → 마감)다 — 이 run엔 열 점, 전부 <code>MarketClock.at</code> 하나가 돈다.",
              "<code>ValuationHandler.mark</code>(#7091, 17.2 ms) → <code>mark_fill</code> → <code>Account.mark</code>(#7201) → <code>commit_mark</code> → <code>ComplianceHandler.observe</code>(#7399, 0.003 ms) → 다음 agenda(#7427).",
              fn="ValuationHandler.mark()", code=("def", 10)),
            F("08_run_factor", 27352, "run이 끝나면 비중이 dataset이 된다 — 역시 같은 문",
              "10세션(계좌 v10, 주문 73 · 체결 54 · no_trade 19)이 끝나면 record를 굳히고(<code>_seal</code>, 표 3: account · fill · weight) <code>_publish_allocation</code>이 <code>vqapr.weight</code> 60행을 <code>sample-factor-weights</code>로 낸다: 각 행의 <code>available_at</code>은 그 결정의 시각(08:00). 이 파일도 <code>verify_source</code>(82.0 ms)를 지나 등록된다.",
              "<code>RunLoop.finish</code>(#26994) → <code>RunRecordWriter._seal</code>(#27160, 19.4 ms) → <code>_write_parquet</code> ×3 → <code>_publish_allocation</code>(#27214, 116.5 ms) → <code>RunOutput.register</code>(#27352, 104.9 ms) → <code>verify_source</code>(#27378, 82.0 ms) → <code>Transaction.commit</code>(#27509, 17.1 ms).",
              fn="RunOutput.register()", code=("def", 8),
              disk={".vqapr/runs/sample-factor-run/strategies/sample-factor@9bba20c4/": "strategy.json · tables/vqapr.{account,fill,weight}/all.parquet", ".vqapr/materialized/sample-factor-weights/all.parquet": "60행 (available_at 01-12 08:00 ~ 01-25 08:00 · instrument · weight ±0.1667)"}),
        ],
        "remember": [
            "verify_run 안에서 판정이 읽은 사실을 얼리기가 받고, 문이 import한 부품을 run이 받는다. 같은 것을 두 번 만들지 않는다.",
            "Rebalance.signed는 부호가 방향이다. 숏은 SIGNED 상장과 SIGNED 계좌가 있어야 체결된다.",
        ],
    },
    # ---------------------------------------------------------------- ⑤ stop-loss with memory
    {
        "id": "stop", "key": "⑤", "title": "stop-loss — memory",
        "sub": "register stoploss.yaml · 97 ms · 1,112 호출 — run sample-stoploss-run · 7,117 ms · 68,066 호출 · 37세션 · 이벤트 74 (0.13.0은 77,553 호출)",
        "story": (
            "<b>지금 하는 일:</b> <code>stoploss.py</code>의 <code>SampleStopLoss</code>는 첫 세션에 종가가 있는 모든 종목을 동일가중으로 사고 각 종목의 <b>진입 종가를 <code>self.memory</code>에 적는다</b>. 그 뒤 세션마다 최신 종가를 기억한 진입가와 견줘 3% 넘게 빠진 종목은 버리고 <code>stopped</code>에 날짜를 적는다. "
            "memory는 엄격한 JSON이고 매 decide 전에 복원되고 뒤에 publish된다 — 같은 run을 다시 돌리면 같은 손절이 같은 날 난다. 이 합성 패널은 잘 빠져서 손절이 이어지고, 02-22엔 K000008 하나, 02-23에 전량 매도, 그 뒤는 현금. "
            "기록 239가 이 콜백의 memory 정규화를 다섯 번에서 한 번으로 줄였다: <code>_candidate_callback_state</code>가 <code>PreparedModelState</code> 하나를 돌려주고 <code>prepare_callback(prepared=)</code>이 그것을 그대로 받는다. panel은 <b>38 × 10</b>(01-03 ~ 02-28)."
        ),
        "frames": [
            F("10_run_stoploss", 8482, "decide 전 — memory {}가 전략에 복원된다",
              "2022-01-04 08:00, 첫 콜백. 프레임워크가 지금 root의 model memory(첫 세션이라 <code>{}</code>)와 payload(빈 바이트)를 전략 인스턴스에 넣는다. 전략은 하나의 인스턴스로 run 전체를 살지만, <b>믿을 것은 이 복원된 memory뿐</b>이다 — 다른 self 속성은 record가 재현하지 못한다. 앞서 <code>verify_run</code>(#881, 365.2 ms)이 이 인스턴스에 초기 memory를 증명했고, run은 그 인스턴스를 받았다.",
              "<code>RunLoop.run</code>(#7938, 6,112.9 ms) → <code>checkpoint</code>(#8450) → <code>_visible_callback_state</code>(#8463) → <code>load_model_state</code>(#8465) → <code>normalize_memory</code>(#8467) → <code>_restore_callback_state</code>(#8482: <code>strategy.memory = {}</code> · <code>load_payload(b'')</code>) → 창 → 계좌 view → decide.",
              fn="_restore_callback_state()", code=at("src/vqapr/flow/run/callback.py", "def _restore_callback_state", 4),
              mem={"strategy.memory": "{}"}),
            F("10_run_stoploss", 8611, "첫 창 — 38행짜리 panel 하나가 run 전체를 든다",
              "start(01-04)에서 <code>RowsLookback(rows=1)</code>이 닿는 격자 한 칸 앞은 01-03 15:30, end는 02-28 23:59:59. 그 사이 38세션 × 10종목 float64 블록 하나를 만들고, 37세션의 모든 decide가 그 블록의 slice를 본다. 둘째 날의 <code>_scan_bounds</code>는 0.17 ms(#12113) — 같은 identity, 같은 panel.",
              "<code>SampleStopLoss.decide</code>(#8575, 69.7 ms) → <code>_DeclaredReads.read</code>(#8576) → <code>ModelWindow.panel</code>(#8595) → <code>panel_window</code>(#8596, 63.0 ms) → <code>_scan_bounds</code>(#8611, 54.8 ms) → <code>observation_table</code> → <code>Panel.from_table</code> → <code>matrix</code>.",
              fn="_scan_bounds()", code=("def", 8),
              mem={"bounds": "2022-01-03 15:30 ~ 2022-02-28 23:59:59 +09:00", "panel.blocks['close'].shape": "(38, 10)"}),
            F("10_run_stoploss", 8575, "첫 decide — 9종목에 진입하고 진입가 9개를 memory에 적는다",
              "최신 종가(01-03의 것)가 있는 종목은 9개(K000010은 아직 없다). <code>entered</code> 플래그가 없으니 <code>entry</code>에 9개의 종가를 적고 플래그를 세운다. 아무도 3%를 깨지 않았으니 9종목 동일가중 <code>Rebalance.of(long=…, invested='0.9')</code>. "
              "플래그를 따로 둔 이유: 나중에 <code>entry</code>가 비었을 때 \"처음\"으로 오해해 다시 사지 않기 위해서다.",
              "<code>SampleStopLoss.inputs</code>(#8560) → <code>SampleStopLoss.decide</code>(#8575, 69.7 ms) → <code>read</code>(#8576, 64.1 ms) → <code>matrix</code> → <code>Rebalance.of</code>.",
              fn="SampleStopLoss.decide() — 저자 코드", code=at(DECL + "stoploss.py", "entry: dict[str, float]", 12), author=True,
              mem={"self.memory": "{entry: {K000001: …, …, K000009: …} 9개, stopped: {}, entered: true}"}),
            F("10_run_stoploss", 9804, "decide 후 — memory가 한 번 정규화되고 의도서와 함께 publish된다 (기록 239)",
              "돌아온 memory를 <code>_candidate_callback_state</code>가 <b>한 번</b> 엄격한 JSON으로 확인하고(<code>prepare_model_state</code>, 3.8 ms: Decimal · datetime · set이 있으면 여기서 거절) <code>PreparedModelState</code>로 만든다. 의도서(9종목 비중)에 도장을 찍고(<code>_stamp_intent</code>) 받아들인 뒤(<code>_accept_intent</code>) <code>prepare_callback(prepared=)</code>이 그 상태를 다시 정규화하지 않고 받아 계좌 · memory · pending을 <b>한 번</b>에 publish한다(root v1). 0.13.0 트레이스는 같은 콜백에서 memory를 다섯 번 정규화하고 envelope을 두 번 해시했다. "
              "15:30에 9종목이 체결된다(<code>fill</code> #10144, 64.9 ms).",
              "<code>_stamp_intent</code>(#9530, 5.1 ms) → <code>_accept_intent</code>(#9708) → <code>_candidate_callback_state</code>(#9804, 6.9 ms) → <code>prepare_model_state</code>(#9806, 3.8 ms) → <code>RunStateRepository.prepare_callback</code>(#10077, 1.0 ms) → <code>publish</code>(#10097, 2.9 ms) → <code>_deliver</code>(#10098) · <code>ExecutionHandler.fill</code>(#10144, 64.9 ms).",
              fn="_candidate_callback_state()", code=at("src/vqapr/flow/run/callback.py", "def _candidate_callback_state", 10),
              mem={"root": "v1 (account v0 · memory entry 9 · pending 1)"}),
            F("10_run_stoploss", 12079, "둘째 날 — 복원된 memory로 첫 손절",
              "01-05 08:00. 복원된 memory(#11984)에 진입가 9개가 있다. 최신 종가(01-04)를 견주면 K000005가 −3%를 넘겼다 → <code>stopped['K000005'] = '2022-01-05'</code>, <code>entry</code>에서 지운다. 남은 8종목 동일가중; 15:30에 K000005를 판다(<code>fill</code> #12838). "
              "이어지는 세션들(weight 표의 세션당 보유 수, 0.13.0 페이지와 같다): 9 → 8(01-05) → 7(01-06) → 5(01-11) → 4(01-19) → 3(01-24) → 2(01-25) → 1(01-26 ~ 02-22, K000008 하나).",
              "<code>_restore_callback_state</code>(#11984) → <code>SampleStopLoss.decide</code>(#12079, 7.0 ms) → <code>_stamp_intent</code>(#12238) → <code>_accept_intent</code>(#12410) → <code>_candidate_callback_state</code>(#12498) → <code>prepare_callback</code>(#12771) · <code>fill</code>(#12838, 58.2 ms).",
              fn="SampleStopLoss.decide() — 손절", code=at(DECL + "stoploss.py", "for name, price in list(entry.items())", 6), author=True,
              mem={"self.memory": "{entry: 8, stopped: {K000005: '2022-01-05'}, entered: true}"}),
            F("10_run_stoploss", 63597, "마지막 이름이 깨지면 — 전량 매도는 Hold가 아니라 빈 Rebalance",
              "02-23 08:00. K000008이 02-22 종가로 −3%를 넘겼다. <code>entry</code>가 비었고 계좌엔 K000008 52주가 있다. <code>Hold</code>는 \"아무것도 하지 말라\"라 포지션이 그대로 남는다; 그래서 <code>Rebalance(target_weights={}, cash_weight=1)</code>을 돌려준다. 15:30에 <b>K000008 −52</b>가 1,441,901.11에 체결되고(fill 표 sequence 347) 계좌(v34)는 현금 84,184,068.92뿐이다.",
              "<code>decide</code>(#63597, 3.1 ms) → <code>_accept_intent</code>(#63785) → <code>MarketClock.at</code> → <code>fill</code>(#64137, 18.3 ms) → <code>AcademicExchange.execute</code>(#64259, 1.6 ms) → <code>Account.append</code>.",
              fn="SampleStopLoss.decide() — 마지막", code=at(DECL + "stoploss.py", "if any(quantity != 0", 5, before=3), author=True,
              mem={"self.memory": "{entry: {}, stopped: 9개, entered: true}", "account v34": "positions {} · cash 84,184,068.92"}),
            F("10_run_stoploss", 64844, "그 뒤 — Hold, pending 없음, 시장 시각은 평가만",
              "02-24 08:00부터 <code>entry</code>도 포지션도 없다 → <code>Hold</code>(\"every name has broken its stop; the book stays in cash\"). pending이 없으니 15:30의 <code>fill</code>은 <code>due=None</code>으로 0.003 ms에 지나가고 <code>mark_held</code>만 한다(10.7 ms). run은 74 이벤트, 계좌 v34로 끝나고 비중 dataset <code>sample-stoploss-weights</code>가 문을 지나 등록된다.",
              "<code>decide</code>(#64844, 2.8 ms) → Hold · <code>AccrualHandler.accrue</code>(#65232) → <code>fill</code>(#65235, 0.003 ms, due=None) → <code>ValuationHandler.mark</code>(#65236, 10.7 ms) → <code>mark_held</code>(#65237) … <code>_publish_allocation</code> → <code>RunOutput.register</code> → <code>verify_source</code>.",
              fn="SampleStopLoss.decide() — Hold", code=at(DECL + "stoploss.py", "return va.Hold(", 1, before=0), author=True,
              disk={".vqapr/runs/sample-stoploss-run/strategies/sample-stoploss@bb45a6ab/": "strategy.json · tables 3 (weight 표 33세션분, 02-23부터 없음)", ".vqapr/materialized/sample-stoploss-weights/all.parquet": "등록됨"},
              tip="strategy.json에는 memory dict가 없다. 트레이스가 보이는 것은 매 콜백의 복원(_restore_callback_state) → 한 번의 정규화(_candidate_callback_state) → publish이고, record에는 그 상태의 ref가 남는다."),
        ],
        "remember": [
            "memory는 decide 전에 복원되고 뒤에 한 번 정규화되어 publish된다. 첫 콜백엔 {}. JSON이 아닌 것은 여기서 거절된다.",
            "\"처음인가\"는 별도 플래그로 기억한다. 포지션을 다 비우려면 Hold가 아니라 빈 Rebalance를 돌려준다.",
        ],
    },
    # ---------------------------------------------------------------- ⑥ enhanced index
    {
        "id": "ei", "key": "⑥", "title": "enhanced index",
        "sub": "register enhanced.yaml · 106 ms · 1,315 호출 — run sample-enhanced-run · 2,196 ms · 31,594 호출 · 9세션 — list datasets 79 ms · show run 22 ms",
        "story": (
            "<b>지금 하는 일:</b> <code>enhanced.py</code>의 <code>SampleEnhancedIndex</code>는 ④가 저장한 <code>sample-factor-weights.weight</code>를 <b>alpha로 읽고</b>, 종가가 있는 종목의 동일가중(1/9)에 그 alpha의 절반을 더한 뒤 0 아래를 자른다 — 롱온리 enhanced index. "
            "run은 09:00에 결정한다(④의 08:00 비중이 알 수 있게 된 뒤). 두 dataset이 각각 자기 horizon으로 잘린다: 가격 (10 × 10), alpha (10 × 10). 마지막으로 <code>list datasets</code>와 <code>show run</code>으로 이 프로젝트에 무엇이 남았는지 읽는다: dataset 6개, 그중 4개가 run이 만든 것."
        ),
        "frames": [
            F("12_run_enhanced", 4742, "얼리기 — 저장된 alpha가 dataset으로 묶인다",
              "요구 둘: <code>sample-factor-weights</code>(source <code>materialized-sample-factor-weights</code>)와 <code>sample-prices</code>. 둘 다 <code>_validate_requirement</code> → <code>require_verified</code>(1.8 · 1.1 ms). run이 만든 표와 벤더 표가 여기서 같은 취급을 받는다는 것이 이 시나리오의 요점이다. 앞의 <code>verify_run</code>은 #1040(272.3 ms).",
              "<code>verify_run</code>(#1040, 272.3 ms) → … <code>_freeze_sources</code>(#4741, 3.8 ms) → <code>_validate_requirement</code>(#4742) → <code>Workspace.require_verified</code>(#4743, 1.8 ms) · <code>_validate_requirement</code>(#4761) → <code>Workspace.require_verified</code>(#4762, 1.1 ms).",
              fn="_validate_requirement()", code=("def", 14),
              mem={"frozen.source_digests": "{materialized-sample-factor-weights: …, sample-prices-source: 18bb7017…}"}),
            F("12_run_enhanced", 5749, "9시 — 두 창을 각자의 horizon으로 읽고 벤치마크에 alpha를 얹는다",
              "2022-01-13 09:00. 가격 창: 하한 01-12 15:30(start 앞 한 칸), (10 × 10) 블록 → 행 1에서 종목 9개(K000010 없음) → 벤치마크 1/9 = 0.111. alpha 창: 하한 01-12 08:00, (10 × 10) 블록 → 행 1(01-13 08:00의 factor 비중 ±1/6)에서 K000003 · 8 · 9는 +0.0833, K000004 · 5 · 6은 −0.0833 → tilt. <code>Rebalance.of(long=…, invested='1')</code>이 정규화한다(합 1). "
              "이 decide는 80.7 ms(두 표의 첫 스캔), 다음 날은 9.7 ms(#9485).",
              "<code>_window_factory.at</code>(#5656, 01-13 09:00) → <code>SampleEnhancedIndex.decide</code>(#5749, 80.7 ms) → prices: <code>observation_table</code>(#6533, 4.3 ms) → <code>from_table</code>(#6570, 1.2 ms) → alpha: <code>observation_table</code>(#6645, 3.7 ms) → <code>from_table</code>(#6682, 0.8 ms) → <code>Rebalance.of</code>.",
              fn="SampleEnhancedIndex.decide() — 저자 코드", code=at(DECL + "enhanced.py", "tilted = {", 6, before=0), author=True,
              mem={"panels": "prices (10 × 10) 01-12 15:30 ~ · alpha (10 × 10) 01-12 08:00 ~ (probe_panel.py)"}),
            F("12_run_enhanced", 7564, "3시 반 — 롱온리 체결, 그리고 아홉 세션",
              "첫 체결은 63.1 ms. 9세션 동안 이벤트 18, 계좌 v9. 끝나면 <code>_publish_allocation</code>(102.4 ms)이 비중을 내고 <code>sample-enhanced-weights</code>가 문을 지나 등록된다(<code>RunOutput.register</code>, 91.9 ms).",
              "<code>MarketClock.at</code> → <code>fill</code>(#7564, 63.1 ms) … 다음 날 <code>decide</code>(#9485, 9.7 ms) … <code>_publish_allocation</code>(#30851, 102.4 ms) → <code>RunOutput.register</code>(#31031, 91.9 ms) → <code>verify_source</code>.",
              fn="ExecutionHandler.fill()", code=("def", 8)),
            F("13_list_datasets", 12, "list datasets — 여섯, 그중 넷은 run이 만들었다",
              "등록부를 열어(59.8 ms) dataset 목록을 낸다: <code>sample-prices</code> · <code>sample-execution</code>(벤더) · <code>sample-features</code>(produced_by <code>sample-features-run</code>, record <code>sample-features@20c2acad</code>) · <code>sample-factor-weights</code>(<code>sample-factor@9bba20c4</code>) · <code>sample-stoploss-weights</code>(<code>sample-stoploss@bb45a6ab</code>) · <code>sample-enhanced-weights</code>(<code>sample-enhanced@f174be27</code>). "
              "어느 run의 어느 코드 버전이 이 표를 썼는지가 이름 옆에 있다.",
              "<code>list_.run</code>(#11, 60.7 ms) → <code>Workspace.open</code>(#12, 59.8 ms) → <code>Workspace._read</code>(#15) → <code>datasets</code>(#1061) → <code>_summarize</code> ×6(#1069 …) → <code>success</code>(#1075, stage workspace.list, count 6).",
              fn="Workspace.open()", code=("def", 8)),
            F("14_show_run_enhanced", 18, "show run — record만 읽는다, 32호출 22 ms",
              "<code>show run sample-enhanced-run</code>은 record(<code>run.json</code>)만 읽는다: 읽은 dataset 둘과 각각의 <code>source_digest</code>, 거래소 fingerprint, 집행 선언(close · 15:30 · Asia/Seoul), 초기 계좌, 기간 01-13 ~ 01-25, 기록 <code>sample-enhanced@f174be27</code>. 이 run이 어떤 바이트를 읽었는지가 record에 있으므로 나중에 파일이 바뀌어도 그때 무엇이었는지는 남는다.",
              "<code>main</code>(#0, 21.8 ms) → <code>show.run</code>(#11, 2.4 ms) → <code>run_ids</code>(#12, 0.9 ms) → <code>read_run_record</code>(#18, 0.5 ms) → <code>record_view</code>(#21) → <code>strategy_refs</code>(#22) → <code>datamodel_refs</code>(#25) → <code>success</code>(#26, stage run.show).",
              fn="read_run_record()", code=("def", 8),
              disk={".vqapr/": "workspace.yaml · instruments.json · materialized/ 4 · runs/ 4"}),
        ],
        "remember": [
            "run이 저장한 비중은 dataset이다: 다음 run이 DatasetInput 한 줄로 읽고, 얼리기는 digest로 묶고, panel은 자기 horizon으로 잘린다.",
            "list · show는 등록부와 record만 읽는다. record는 읽은 파일의 digest를 든다.",
        ],
    },
    # ---------------------------------------------------------------- ⑦ --jobs batch
    {
        "id": "batch", "key": "⑦", "title": "--jobs 배치 — worker도 판정, cube 한 번",
        "sub": "run sample-factor-run sample-stoploss-run --jobs 2 --force · 1,693 ms · 3,492 호출 (driver) — worker 하나를 따로 추적: 1,679 ms · 26,832 호출",
        "story": (
            "<b>지금 하는 일:</b> ④와 ⑤를 <b>한 배치</b>로 다시 돌린다(<code>--jobs 2</code>; 기록이 이미 있으니 <code>--force</code>). driver는 worker를 띄우기 <b>전에</b> 각 run이 무엇을 읽는지 한 번 묻고(<code>batch_reads</code>, 기록 238) 그것으로 독립성을 판정하고 cube를 굽는다: <code>sample-features.momentum_5d</code>(12 × 9)와 <code>sample-prices.close</code>(735 × 10), 각각 전 종목 × 등록 span. "
            "worker는 자기 horizon만큼을 그 파일의 <b>slice</b>로 받는다(<code>np.load(mmap_mode='r')</code>) — 스캔이 없다. 배치가 돌아오면 디렉터리는 지워진다(기록 236). "
            "<b>0.14.0이 바꾼 것:</b> worker가 <code>verify_run</code>을 지난다. 0.13.0의 worker는 판정 없이 얼려서, <code>check</code>가 거절한 run을 <code>run a b --jobs 2</code>가 돌렸다(이슈 015). 이제 worker의 트레이스 #16이 <code>verify_run</code>, #18이 <code>judgments</code>다. "
            "driver의 트레이스는 프로세스 경계에서 끝나므로(<code>in_workers</code>가 spawn한다) worker 쪽은 <code>exp_238/trace_worker.py</code>가 같은 worker 함수(<code>run_registered_strategy</code>)를 같은 프로파일러 아래서 따로 돌려 얻었다."
        ),
        "frames": [
            F("15_run_batch", 12, "여러 run이면 driver는 무엇을 읽는지 한 번 묻고 배치를 판정한다",
              "<code>run a b --jobs 2</code>. target이 둘 이상이고 jobs가 1보다 크니 <code>_run_each_in_workers</code>. 등록부를 열고(#15, 56.6 ms) <code>batch_reads</code>(#1064, 8.9 ms)가 run마다 부품을 load해 <code>_reads</code>를 한 번씩 묻는다 — factor는 <code>sample-features[momentum_5d]</code>, stop-loss는 <code>sample-prices[close]</code>. 0.13.0은 독립성 판정과 bake가 각자 부품을 다시 load했다(<code>_reads</code> ×4). <code>require_independent_batch</code>(#1235, 0.2 ms)는 그 답만 본다: 둘 다 서로의 <code>writes</code>를 읽지 않는다.",
              "<code>run</code>(#11) → <code>_run_each_in_workers</code>(#12, 1,676.1 ms) → <code>refuse_a_path</code> ×2 → <code>Workspace.open</code>(#15, 56.6 ms) → <code>batch_reads</code>(#1064, 8.9 ms) → <code>_reads</code>(#1067, 4.6 ms · #1157, 4.1 ms) → <code>require_independent_batch</code>(#1235, 0.2 ms) → <code>run_definition</code> ×2 → <code>batch_cubes</code>(#1244).",
              fn="_run_each_in_workers()", code=at("src/vqapr/cli/run.py", "with batch_cubes(workspace, targets, reads) as cubes:", 12, before=6),
              mem={"targets": "[sample-factor-run, sample-stoploss-run]", "reads": "factor → sample-features[momentum_5d] · stop-loss → sample-prices[close] (한 번 물어 두 문에 건넨다)"}),
            F("15_run_batch", 1244, "batch_cubes — 묵은 것을 쓸고, 잠그고, 굽는다",
              "<code>.vqapr/cubes/</code> 아래에 <code>&lt;pid&gt;-&lt;random&gt;/</code>를 만들고 lock 파일에 pid를 적는다. 먼저 이전 배치가 남긴 묵은 디렉터리를 쓸고(lock이 10분 넘게 갱신되지 않은 것), 30초마다 lock을 만지는 heartbeat 스레드가 이 배치를 살아 있는 것으로 표시한다. 그리고 <code>_bake_for_batch</code>가 <code>batch_reads</code>의 답을 받아 dataset id 순서로 굽는다.",
              "<code>batch_cubes</code>(#1244, 478.4 ms) → <code>_bake_for_batch</code>(#1246, 475.4 ms) → <code>source_digest</code>(#1256) → <code>bake</code>(#1259, 375.9 ms: sample-features) → <code>source_digest</code>(#1358) → <code>bake</code>(#1361, 94.5 ms: sample-prices).",
              fn="batch_cubes()", code=("def", 14),
              disk={".vqapr/cubes/<pid>-<hex>/": "cube.lock (pid)"}),
            F("15_run_batch", 1361, "bake — sample-prices.close를 전 종목 × 등록 span으로 한 번",
              "dataset마다 한 번씩: <code>distinct_values</code>로 원천이 든 종목 전부(10)를 세고(15.1 ms), 등록 span 전체를 <b>종목 제한 없이</b> 스캔하고, <code>placement</code>(2.7 ms)·<code>dense_block</code>이 (735 × 10) float64 하나로 접어 <code>close.npy</code>(58,928 B)로 저장한다. 옆에 <code>present.npy</code>(행이 있던 칸), <code>instants.npy</code>(735), <code>instruments.json</code>(10), <code>cube.json</code>(원천 digest <code>18bb7017…</code>). "
              "앞의 <code>sample-features</code>(#1259, 375.9 ms — 이 프로세스의 첫 스캔)는 12 × 9 — K000010은 그 표에 한 행도 없다. 굽지 못하는 것(등록 안 된 표, 문자열 필드, rows grain)은 조용히 빠지고 그 worker는 스캔한다.",
              "<code>bake</code>(#1259, 375.9 ms: sample-features) → <code>distinct_values</code>(#1260, 15.8 ms) → … → <code>placement</code>(#1313, 7.0 ms) · <code>bake</code>(#1361, 94.5 ms: sample-prices) → <code>distinct_values</code>(#1362, 15.1 ms) → <code>placement</code>(#1417, 2.7 ms) → <code>dense_block</code> → <code>open_cube</code>.",
              fn="bake()", code=at("src/vqapr/data/cube.py", "instants, keep, rows, cols = placement(table, names, keyed)", 12, before=0),
              disk={".vqapr/cubes/<batch>/sample-prices/": "close.npy (735, 10) float64 58,928 B · present.npy (735, 10) bool 7,478 B · instants.npy (735,) int64 6,008 B · instruments.json 10 · cube.json", ".vqapr/cubes/<batch>/sample-features/": "momentum_5d.npy (12, 9) 992 B · present.npy · instants.npy (12,) · instruments.json 9 · cube.json (probe_cubes.py)"}),
            F("15_run_batch", 2904, "in_workers — 여기서 driver의 트레이스는 프로세스 경계를 만난다",
              "두 run이 두 spawn 프로세스에 하나씩 간다: <code>run_registered_strategy(project, run_id, store, replace=True, positions=True, cubes=&lt;dir&gt;)</code> — 문자열과 bool만 넘긴다. 1,094.1 ms 동안 driver는 기다린다. 이 프로파일러는 이 프로세스의 것이라 worker 안의 호출은 여기 없다 — 다음 두 프레임은 worker를 따로 추적한 트레이스다.",
              "<code>in_workers</code>(#2904, 1,094.1 ms) — 안쪽 호출 없음(다른 프로세스).",
              fn="in_workers()", code=("def", 10)),
            F("16_worker_factor", 16, "worker — 문 하나를 지나고 판정을 받는다 (기록 240)",
              "worker 프로세스는 등록부를 열고(0.9 ms — 데워진 파일) 자기 run을 <b><code>verify_run</code></b>에 넘긴다: 판정 309.5 ms · 얼리기 21.8 ms · <code>RunResources.of</code> 0.7 ms → <code>require_ready</code>. 판정이 거절하면 <code>check</code>의 code로 거절되고 record는 쓰이지 않는다 — driver의 봉투에 그 run의 항목으로 돌아온다. 0.13.0의 worker는 <code>preflight_run</code>만 불렀다. 그 다음은 단일 run과 같은 <code>_run_strategy</code>다.",
              "<code>run_registered_strategy</code>(#0, 1,675.8 ms) → <code>Workspace.open</code>(#1, 0.9 ms) → <code>run_definition</code>(#14) → <code>verify_run</code>(#16, 332.3 ms) → <code>judgments</code>(#18, 309.5 ms) → <code>preflight_run</code>(#3394, 21.8 ms) → <code>_freeze_strategy</code>(#3446) → <code>_freeze_sources</code>(#3785) → <code>RunResources.of</code>(#3847) → <code>require_ready</code>(#3861) → <code>registered_roster</code>(#3863, 19.9 ms) → <code>_run_strategy</code>(#3908, 1,322.1 ms) → <code>RunLoop.run</code>(#4377, 1,182.3 ms).",
              fn="run_registered_strategy() — worker", code=at("src/vqapr/flow/orchestration.py", "def run_registered_strategy", 12)),
            F("16_worker_factor", 4755, "worker — 스캔 대신 cube를 map 한다",
              "worker 프로세스의 첫 decide(01-12 08:00). <code>panel_window</code>는 평소처럼 <code>_scan_bounds</code>로 horizon을 정하고(12.8 ms), 그 다음이 다르다: store에 <code>cubes</code>가 있으니 <code>open_cube</code>가 <code>sample-features/cube.json</code>을 읽고 원천 digest가 worker 자신이 방금 대조한 digest와 같은지 본 뒤(1.9 ms), <code>panel_from_cube</code>가 <code>present.npy</code>·<code>momentum_5d.npy</code>를 <code>mmap_mode='r'</code>로 열어 horizon 안의 행만 slice 한다(2.2 ms). "
              "run이 선언한 종목(10)이 cube의 종목(9)과 다르므로 순수 view가 아니라 gather 한 번(11 × 10, K000010 열은 NaN). 이 트레이스 어디에도 <code>observation_table</code>과 <code>Panel.from_table</code>이 없다. 첫 decide 24.4 ms, 다음부터 6.7 ms.",
              "<code>SampleFactor.decide</code>(#4663, 24.4 ms) → <code>panel_window</code>(#4690, 18.8 ms) → <code>_scan_bounds</code>(#4705, 12.8 ms) → <code>open_cube</code>(#4729, 1.9 ms) → <code>panel_from_cube</code>(#4755, 2.2 ms) → <code>PanelWindow.matrix</code>. 다음 날: <code>decide</code>(#6833, 6.7 ms).",
              fn="panel_from_cube()", code=at("src/vqapr/data/cube.py", "if whole and identical:", 8, before=2),
              mem={"cube": "sample-features: instants 12 · names 9 · digest 54f8fd04… = worker의 digest", "panel": "(11 × 10) gather — K000010 열 NaN"}),
            F("15_run_batch", 2905, "배치가 돌아오면 디렉터리는 없다 — 봉투는 run마다 하나",
              "<code>in_workers</code>가 두 결과를 돌려주자 <code>batch_cubes</code>의 <code>finally</code>가 heartbeat를 멈추고 <code>rmtree</code>로 cube 디렉터리를 지운다(3.5 ms; 프로파일러는 제너레이터의 재개를 두 번째 호출로 기록한다). 성공이든 거절이든 예외든 같다 — 아무것도 쌓이지 않는다. "
              "<code>_worker_entry</code>가 run마다 record를 읽어 봉투를 만든다: factor 계좌 v10 · 주문 73 · 체결 54, stop-loss 계좌 v34 — ④·⑤와 같은 수. 봉투의 <code>jobs: 2</code>가 실제로 돈 프로세스 수다. 명령 뒤의 파일 목록에 <code>.vqapr/cubes/</code> 아래 파일은 없다.",
              "<code>in_workers</code>(#2904) → <code>batch_cubes</code>(#2905, 3.5 ms: finally → rmtree) → <code>_worker_entry</code>(#2906, 14.6 ms: sample-factor-run) → <code>_strategy_envelope</code>(#2907) → <code>_worker_entry</code>(#3137, 18.6 ms: sample-stoploss-run) → <code>_runs_envelope</code>(#3482) → <code>success</code>(#3486).",
              fn="batch_cubes() — finally", code=at("src/vqapr/flow/orchestration.py", "_bake_for_batch(", 9, before=1),
              disk={".vqapr/cubes/": "비어 있음 (배치 디렉터리 삭제됨)", ".vqapr/runs/": "sample-factor-run · sample-stoploss-run 다시 씀 (--force)"}),
        ],
        "remember": [
            "--jobs worker도 verify_run을 지난다: check가 거절하는 run은 배치도 거절하고 record를 쓰지 않는다.",
            "--jobs 배치는 무엇을 읽는지 한 번 묻고, dataset마다 cube를 한 번 굽고, worker는 map 한다. 배치가 끝나면 cube는 없다.",
        ],
    },
]

TABLE = {
    "title": "트레이스가 확인한 것 — 0.14.x가 바꾼 자리",
    "rows": [
        ["<b>선언에서 run까지 문은 하나다</b> (기록 240–241)",
         "<code>verify_run</code>: check 03 #336 · run 06 #470 · 08 #722 · 10 #881 · 12 #1040 · worker 16 #16. 안에서 <code>judgments</code> → <code>preflight_run</code> 순서, 둘 다 <code>RunFacts</code>(#337 · #723 · #17)를 받는다. 0.13.0은 run이 <code>preflight_run</code>을 두 번(08 #722 1,018 ms · #4013 252 ms), worker는 판정 없이 한 번 불렀다",
         "check가 거절하는 것을 run과 worker도 거절한다. 선언은 명령당 한 번 읽힌다"],
        ["<b>사실은 명령당 한 번 읽힌다</b> (기록 238–240)",
         "check 03: <code>derived_agenda</code> #365 한 번(1,922.5 ms; 0.13.0은 #362 2,019.5 + #48202 1,838.8 ms). run 08: 판정의 <code>derived_agenda</code> #752 251.8 ms 뒤 얼리기의 <code>RunFacts.agenda</code> #4026 0.07 ms. 실패도 한 번: 03 #45886 <code>physical_digest</code> 0.5 ms 뒤 preflight #48204는 저장된 예외(6.1 ms; 0.13.0은 #90143에서 다시 해시)",
         "호출 수가 말한다: check 90,168 → 48,326 · run factor 31,759 → 27,853 · stop-loss 77,553 → 68,066 · enhanced 35,341 → 31,594"],
        ["<b>run은 문이 load한 것을 받는다</b> (기록 242)",
         "<code>RunResources.of</code>: 06 #4160 (0.4 ms) · 08 #4471 (0.8 ms: <code>RunFacts.component</code> #4478 0.06 ms · <code>exchange</code> #4480 · <code>horizon</code> #4483) · 16 #3847 → <code>require_ready</code> #4168 · #4485 · #3861 → <code>run(…, resources=)</code>",
         "전략 · 거래소 · 규칙은 판정이 import한 인스턴스 그대로, horizon은 판정이 자른 것 그대로. run 시작의 재import · 재스캔이 없다"],
        ["<b>worker가 판정을 받는다</b> (기록 240)",
         "16: <code>verify_run</code> #16 → <code>judgments</code> #18 (309.5 ms) → <code>preflight_run</code> #3394 → <code>RunResources.of</code> #3847 → <code>require_ready</code> #3861. driver 15에는 <code>verify_run</code>이 없다 — 판정은 worker의 몫이다",
         "이슈 015가 닫혔다: check가 거절한 run을 배치가 돌리지 않는다"],
        ["<b>배치는 무엇을 읽는지 한 번 묻는다</b> (기록 238)",
         "15: <code>batch_reads</code> #1064 (8.9 ms) → <code>_reads</code> #1067 · #1157 (run마다 한 번) → <code>require_independent_batch</code> #1235 (0.2 ms) → <code>batch_cubes(…, reads)</code> #1244. 0.13.0은 <code>_reads</code> ×4",
         "독립성 판정과 bake가 같은 답을 받는다"],
        ["<b>memory는 한 번 정규화된다</b> (기록 239)",
         "10: <code>_candidate_callback_state</code> #9804 (6.9 ms) → <code>prepare_model_state</code> #9806 한 번 → <code>prepare_callback</code> #10077 (1.0 ms, prepared=) → <code>publish</code> #10097. 매 콜백 같은 순서",
         "0.13.0 #14668 .. #14971이 다섯 번 정규화하고 두 번 해시하던 자리. ref와 record는 byte-identical"],
        ["<b>바뀌지 않은 것 — panel은 horizon, cube는 배치, 문은 하나</b> (기록 234–236)",
         "<code>_scan_bounds</code>: 06 #4622 (17 × 10) · 08 #5410 (11 × 10) · 10 #8611 (38 × 10) · 12 (10 × 10 둘). <code>verify_source</code>: 등록 01 #136 · #328 · 재등록 04 #451 · #643 · 출력 06 #9969 · 08 #27378. 16: <code>open_cube</code> #4729 → <code>panel_from_cube</code> #4755, <code>observation_table</code> 0번",
         "계산된 숫자는 하나도 다르지 않다: 체결 · 계좌 · 비중 dataset이 0.13.0 페이지와 같다(showcase digest 83/83)"],
        ["<b>run 시작의 명단 읽기는 설계다</b>",
         "<code>registered_roster</code> → <code>verify_roster</code>: 08 #4496 407.2 ms · 10 #7196 354.5 ms · 12 #4858 358.4 ms · worker 16 #3863 19.9 ms. 각 프로세스의 첫 pyarrow parquet 읽기",
         "명단은 얼리지 않고 매 run 새로 읽는다(이슈 009). 절대치는 첫 읽기의 비용이지 10행짜리 표의 값이 아니다"],
        ["cold 읽기가 절대치를 지배한다",
         "등록의 <code>check_span</code> #213 443.4 ms(첫 duckdb 스캔) · 명단 #46 351.0 ms(첫 pyarrow 읽기) · datamodel 첫 compute #4586 409.0 ms(스캔 336.6) · 두 번째부터 한 자릿수 ms · worker(16)의 첫 decide 24.4 ms",
         "판끼리 절대치를 비교하지 말 것. 이 판은 로컬 디스크, 0.13.0 판은 CIFS였다"],
    ],
}
