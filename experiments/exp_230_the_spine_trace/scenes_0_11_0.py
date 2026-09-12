# ruff: noqa: E501, RUF001 -- prose data: long lines and typographic characters are the content
# The 0.11.0 spine stepper: ten scenes, every frame standing on a call the profiler recorded.
#
# Rendered by `render.py` (which executes this file with `REPO` bound to the tree the traces
# were taken on). A frame names its trace and call index; `render.py` fills in the definition
# line, the qualified name and the milliseconds from the trace, and reads the code window from
# the tree. Each frame says first, in plain words, what happens to the sample project at that
# moment (`story`), and folds the call sequence the trace shows beneath it (`calls`). A number
# that appears anywhere here appears in a trace. Traces: `README.md` beside this file.


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
    "title": "vqapr 0.11.0 척추 디버거",
    "storage_key": "vqapr-stepper-0110",
    "eyebrow": "vqapr 0.11.0 · develop (records 221–229) · 2026-09-10 · 실제 실행을 sys.setprofile로 추적한 결과",
    "h1": "vqapr 0.11.0 척추 디버거 — sample 프로젝트의 하루를 한 프레임씩",
    "lede": (
        "<b>한 시나리오를 처음부터 끝까지 따라갑니다.</b> <code>vqapr new sample</code>이 만든 프로젝트(10종목, 2022-01-03 ~ 2024-12-30)에서 "
        "선언을 <b>등록</b>하고, run을 돌려도 되는지 <b>검사</b>하고, 15세션짜리 전략 run(<code>sample-run-short</code>, 규칙 <code>no-short</code> 하나)을 "
        "<b>돌리고</b>, 그 안에서 하루가 어떻게 흘러가는지(아침의 결정 → 오후의 체결·평가·판정 → 적힌 행의 행방)를 보고, 결과를 <b>읽고</b>, "
        "같은 루프로 <b>datamodel</b>을 돌리고, 마지막으로 옛 방식으로 쓴 규칙이 <b>거절</b>되는 것을 봅니다. "
        "프레임마다 위에는 <b>지금 무슨 일이 일어나는지</b>를 보통 말로 적었고, 아래 접힌 곳에 트레이스가 기록한 호출 순서를 두었습니다. "
        "모든 <code>#idx</code>(그 명령 안에서 몇 번째 호출인지)와 <code>ms</code>는 <code>sys.setprofile</code>이 실제로 기록한 값이고, 스니펫은 그 시점의 소스 줄입니다 — "
        "상상한 것은 없습니다(<code>experiments/exp_230_the_spine_trace/</code>)."
    ),
    "facts": [
        {"k": "데이터", "v": "10 × 735", "s": "종목 × 세션. run 구간은 그중 15세션(2022-01-04 ~ 01-25): 아침 결정 16번 · 오후 시장 시각 16번 = 이벤트 32"},
        {"k": "결정과 체결", "v": "Hold 5 · 매수 11", "s": "처음 5일은 6일치 종가가 안 차서 Hold, 1월 11일부터 매일 최하위 3종목 매수. 주문 41 · 체결 24 · no_trade 17"},
        {"k": "끝난 뒤 장부", "v": "v11", "s": "cash 10,688,433 · 보유 3(K000002 145 · K000003 46 · K000008 18) · 규칙 no-short: 16번 판정, 16번 held"},
        {"k": "디스크에 남는 것", "v": "4 + 2 + 1", "s": "표 4(account · fill · monitoring · weight) all.parquet · strategy.json · run.json · 배분 dataset 1. 도는 동안은 lock과 progress.json뿐"},
        {"k": "호출 수", "v": "run 45,436", "s": "register 945 · check 8,137 · run(datamodel) 20,128 · list runs 689 · show run 30 · show strategy 27 · list strategies 30 · register(거절) 805"},
        {"k": "datamodel", "v": "108 행", "s": "16세션 → dataset <code>sample-features-values</code> 하나 · 같은 RunLoop, 시장 시계 없음"},
    ],
    "fix": (
        "<strong>시간 읽는 법.</strong> ms는 프로파일러가 켜진 채 잰 값이라 절대치는 실제보다 큽니다. 같은 트레이스 안에서 <b>서로 비교</b>만 하십시오. "
        "이 머신에선 parquet의 <b>첫</b> 읽기가 유난히 큽니다(등록의 span 측정 9.5 s, 검사의 집행표 스캔 11.5 s, 첫 panel 읽기 0.4~0.8 s). "
        "같은 질문을 두 번째 물을 땐 수십 ms입니다."
    ),
    "glossary_title": "이 페이지에 나오는 낱말 — 먼저 읽어 두면 편합니다",
    "glossary": [
        ("선언 (declaration)", "당신이 쓰는 YAML. \"이 parquet은 가격이다, 이 파일은 내 전략이다, 이 run은 이렇게 돌려라\"."),
        ("등록부 (workspace)", "<code>.vqapr/workspace.yaml</code>. <code>register</code>가 쓰고, 모든 명령이 맨 처음 펼쳐 읽는다. 코드에선 <code>Workspace</code>."),
        ("검사·판정 (check · judgment)", "\"이 run을 돌려도 되나\"에 대한 예/아니오 하나하나. <code>check</code>는 모아서 답하고, <code>run</code>은 첫 거절에서 멈춘다."),
        ("얼리기 (freeze → FrozenRun)", "등록부에 적힌 <i>이름</i>들(전략 id, dataset id, 거래소 id)을 <i>실제 값</i>(코드의 fingerprint, parquet 경로와 span, 16개의 결정 시각, 초기 계좌)으로 전부 풀어 하나로 묶은 <b>불변 스냅샷</b>. 이 뒤로 등록부가 바뀌어도 run은 이 스냅샷만 본다."),
        ("전략 시계 · occurrence", "agenda(매일 08:00)가 만드는 결정 시각 하나하나. 전략의 <code>decide</code>가 불리는 때."),
        ("시장 시계 · horizon", "집행표(sample-execution)에 행이 있는 모든 시각(매일 15:30). 체결·평가·규칙 판정은 여기서만 일어난다. horizon = 그 시각의 목록."),
        ("의도서 (intent) · pending", "전략이 돌려준 목표 비중에 프레임워크가 도장(id · 본 계좌 버전 · 읽은 데이터)을 찍은 것. 체결 시각이 올 때까지 <b>pending</b>으로 하나만 기다린다."),
        ("root · publish", "run이 지금까지 받아들인 상태(계좌 · 전략 메모리 · pending)의 버전. <code>publish</code> 한 문으로만 바뀐다."),
        ("chunk · sink · seal", "적힌 행의 묶음 · 그 묶음이 흘러가는 곳(writer의 버퍼) · run 끝에 parquet 파일로 굳히기."),
        ("기록 (record)", "run.json · strategy.json · tables/*.parquet. <code>show</code>·<code>list</code>는 이것만 읽는다."),
        ("봉투 (envelope)", "모든 명령이 stdout에 내는 JSON 한 덩어리. 성공이든 거절이든 모양이 같다."),
    ],
}

MAP = [
    ("①", "등록", "선언 → 등록부"),
    ("②", "검사", "돌려도 되나 → 얼리기"),
    ("③", "run 시작", "부품 로드 · 루프 조립"),
    {"loop": [
        ("④", "아침 8시", "전략이 결정한다"),
        ("⑤", "읽기", "\"최근 6일 종가\""),
        ("⑥", "오후 3시 반", "체결 → 평가 → 판정"),
        ("⑦", "적힌 행", "어디로 가나"),
    ]},
    ("⑧", "결과 읽기", "list · show"),
    ("⑨", "datamodel", "같은 루프, 시계 하나"),
    ("⑩", "거절", "옛 규칙을 등록하면"),
]

SCENES = [
    # ---------------------------------------------------------------- ① register
    {
        "id": "reg", "key": "①", "title": "등록",
        "sub": "vqapr register sample.yaml · 15,052 ms · 945 호출 — 그리고 short.yaml(규칙 no-short + run sample-run-short) 169 ms · 769 호출",
        "story": (
            "<b>지금 하는 일:</b> 당신이 <code>sample.yaml</code>을 건넨다. 거기엔 종목 명단, 가격 parquet, 집행표 parquet, 전략 코드, 거래소 코드, run 하나가 적혀 있다. "
            "vqapr은 이 문서를 그대로 믿지 않는다 — parquet을 <b>실제로 열어</b> 선언과 맞는지 재고, 전략과 거래소 코드를 <b>실제로 import</b>해 계약대로인지 본 뒤, "
            "그제야 등록부(<code>.vqapr/workspace.yaml</code>) 한 파일을 쓴다. 두 번째 문서 <code>short.yaml</code>은 규칙 <code>no-short</code>와 짧은 run을 같은 길로 더한다."
        ),
        "frames": [
            F("01_register", 0, "명령줄이 register 핸들러를 고른다",
              "<code>vqapr --project-root sample register sample.yaml</code>. argparse가 verb를 고르고, 프로젝트 루트를 정한 뒤 register 핸들러를 부른다. 이 15초의 거의 전부(15,041 ms)는 핸들러 안에서 보낸다. 무엇이 잘못되든 결과는 같은 모양의 JSON 봉투로 나온다.",
              "<code>build_parser</code>(#1, 7.9 ms) → <code>parse_args</code> → <code>_resolve_project_root</code>(#10) → <code>args.handler(args, project_root=...)</code>(#11).",
              fn="main() → handler", code=at("src/vqapr/cli/main.py", "def main(", 14),
              mem={"argv": "['--project-root', '.../sample', 'register', '.../sample/sample.yaml']"}, disk={".vqapr/": "없음"}),
            F("01_register", 11, "YAML을 dict 하나로 읽는다",
              "선언 문서가 메모리에 올라온다: instruments 10, datasets 둘(<code>sample-prices</code> 가격 · <code>sample-execution</code> 집행표), components 둘(전략 · 거래소), runs 하나(<code>sample-run</code>). 아직 아무것도 검사하지 않았다.",
              "<code>read_yaml_mapping</code>(#12, 31 ms) → <code>apply</code>(#13). 반환은 <code>Registered</code> — 등록된 id들의 dict에 <code>.spoken</code>(사람 말로 푼 문장)이 붙은 것.",
              fn="register.run() → read_yaml_mapping() → apply()", code=at("src/vqapr/cli/register.py", "declaration = Path(args.declaration)", 6),
              mem={"document": "dict (instruments 1, datasets 2, components 2, runs 1)"}),
            F("01_register", 14, "트랜잭션을 열고, 섹션을 정해진 순서로 처리한다",
              "모르는 섹션 이름이 있으면 여기서 이름을 대며 거절한다. 그 다음 <b>트랜잭션</b>을 연다 — 등록부의 스냅샷 위에 하나씩 올려 두었다가 맨 끝에 한 번에 쓰는 장치. 디스크는 아직 그대로다. "
              "처리 순서는 instruments → datasets → components → runs: 뒤의 것이 앞의 것을 이름으로 가리키기 때문이다(run은 전략 id와 dataset id를 든다). 종목 명단 parquet이 먼저 읽힌다(679 ms).",
              "<code>Workspace.transaction</code>(#15, 0.7 ms) → <code>_require_declared_ids</code>(#25) → <code>_instruments</code>(#43, 679 ms: <code>read_roster_table</code> #46이 instruments parquet을 읽는다) → datasets → components → runs.",
              fn="_apply() — 섹션 순서", code=at("src/vqapr/project/registration.py", 'for dataset_id, body in section("datasets")', 7),
              mem={"transaction.staged": "[instruments: stock 10]"}),
            F("01_register", 133, "가격 parquet을 실제로 열어 네 가지를 잰다 — 이 트레이스에선 13.6 s",
              "선언은 \"<code>available_at</code> 열이 시각이고 <code>close</code>가 DOUBLE이고 (시각, 종목)이 유일하다\"고 말한다. vqapr은 믿지 않고 파일을 열어 순서대로 묻는다: "
              "① 그 열들이 있고 타입이 선언대로인가 ② (시각, 종목)이 정말 유일한가 ③ 파일이 실제로 덮는 기간은 언제부터 언제까지인가(<b>잰다</b>, 선언받지 않는다) ④ 숫자 열에 NaN·inf가 없는가. "
              "이 머신에선 ③의 첫 스캔이 9.5 s였다 — 구조가 아니라 디스크 캐시의 값이다. 집행표는 같은 네 단계가 76 ms에 끝난다.",
              "<code>_dataset</code>(#87, 80 ms)이 <code>DatasetRegistration</code>과 <code>SourceSpec</code>을 만들고 → <code>validate</code>(#133, 13,556 ms): describe → <code>check_schema</code> → <code>check_key</code> → <code>check_span</code>(#210, 9,463 ms) → <code>check_values</code> → <code>with_span</code>. 통과하면 <code>Transaction.register_dataset</code>(#275). 집행표: <code>validate</code>(#321, 76 ms; check_span #384 12.6 ms) → #431.",
              fn="validate() — 4단계", code=at("src/vqapr/data/datasets.py", "def validate(", 12),
              disk={"sample/observations.parquet": "읽음 (schema · key · span · values)", "sample/execution.parquet": "읽음 (같은 네 단계)"},
              mem={"transaction.staged": "[instruments, dataset:sample-prices(span 2022-01-03~2024-12-30 잼), dataset:sample-execution]"},
              tip="여기서 잰 span은 등록부에 저장된다. 그 뒤 \"이 dataset은 언제까지 있나\"는 파일을 열지 않고 답한다."),
            F("01_register", 443, "전략과 거래소 코드를 import해서 계약대로인지 본다",
              "<code>reversal_5d.py</code>와 <code>exchange.py</code>를 실제로 import하고 객체를 만들어 본다. 그 다음 계약 메서드(<code>decide</code>, <code>execute</code> …)가 있는지, <b>인자 개수</b>가 프레임워크가 부를 모양과 맞는지 본다. "
              "파일 바이트의 fingerprint(sha256)도 여기서 찍힌다 — 나중에 \"등록한 그 코드가 돌았나\"를 묻는 근거다. 쓰는 것은 없다.",
              "<code>_component</code>(#440) → <code>prepare_component</code>(#443, 273 ms 전략 · #589, 196 ms 거래소) → <code>fingerprint_component</code> → <code>ComponentRef.of</code> → <code>conformance</code>(#524): <code>_LOADERS[kind]</code>가 import·생성 → <code>_check_methods</code>가 arity 검사.",
              fn="prepare_component() ×2 → conformance()", n=2,
              code=at("src/vqapr/extension/prepare.py", "fingerprint = fingerprint_component(", 17),
              mem={"transaction.staged": "[…, component:sample-reversal-5d(fb2406b9…), component:sample-exchange(e2b2ab0f…)]"}),
            F("04_register_short", 483, "배포된 규칙 no-short도 똑같은 문을 지난다",
              "두 번째 문서 <code>short.yaml</code>은 vqapr가 배포하는 <code>no_short.py</code>의 <code>NoShort</code>를 규칙 <code>no-short</code>로 등록한다. 배포된 것이라고 봐주지 않는다 — 사용자 코드와 같은 fingerprint · import · 계약 검사를 지난다. "
              "그 다음 run <code>sample-run-short</code>가 등록되는데, 이때 run이 가리키는 전략 · 규칙 · 거래소 셋이 등록부에 있는지 확인한다.",
              "<code>prepare_component</code>(#483, kind=compliance, 18.6 ms) → <code>fingerprint_component</code>(#484) → <code>conformance</code>(#568) → <code>load_compliance</code>(#570) → <code>NoShort.__init__(compliance_id='no-short')</code>(#580) → <code>_check_methods</code>(#583) → <code>register_component</code>(#589). run: <code>register_run</code>(#656) → <code>_require_run_references</code>(#661: strategy_model · compliance · exchange).",
              fn="prepare_component(kind=compliance) → conformance()", code=at("src/vqapr/compliance/builtin/no_short.py", "def observe(self, call: ComplianceCall)", 12, before=2),
              mem={"transaction.staged": "[component:no-short, run:sample-run-short]"}),
            F("01_register", 794, "run 정의를 읽고, 사람 말로 다시 말해 준다",
              "runs 섹션은 등록부에 저장될 모양 그대로 한 번 더 읽힌다(선언에서 읽든 등록부에서 읽든 run은 한 길로 온다). 그리고 봉투에 넣을 문장을 만든다: "
              "\"이 run은 집행표에 행이 있는 날마다 08:00에 모델을 부르고, 결정은 그 다음 첫 집행 시각 15:30에 종가로 체결된다\". 당신이 쓴 몇 줄이 어떤 시점 규칙을 뜻하는지를 등록하는 순간에 들려준다.",
              "<code>RunDefinition._from_the_stored_spelling</code>(#794, 24 ms) → <code>_refuse_a_run_fed_by_a_sibling</code>(#845) → <code>Transaction.register_run</code>(#849) → <code>RunDefinition.spoken</code>(#861).",
              fn="RunDefinition._from_the_stored_spelling() → register_run()", code=at("src/vqapr/project/registration.py", 'for run_id, body in section("runs")', 8),
              mem={"transaction.staged": "[…, run:sample-run]"}),
            F("01_register", 874, "마지막에 등록부 한 파일을 쓴다",
              "여기까지 디스크엔 아무것도 없었다. commit이 락을 잡고, 지금 디스크에 있는 등록부를 다시 읽고, 스테이징해 둔 것을 그 위에 재생한 뒤, 파일을 <b>한 번</b> 원자적으로 바꿔 쓴다. 종목 명단은 <code>instruments.json</code>으로. "
              "봉투: 등록된 id들 + 문장 4개.",
              "<code>Transaction.commit</code>(#874, 92 ms): <code>_exclusive</code>(#875 → filelock #877) → <code>_read_or_empty</code>(#878) → <code>_merge_dataset</code> ×2 · <code>_merge_component</code> ×2 · <code>_merge_run</code>(#889) → <code>_write</code>(#896 → <code>write_workspace</code> #898 83 ms → <code>write_atomically</code> #932) → <code>_write_roster</code>(#935) → <code>success('workspace.register')</code>(#939).",
              fn="Transaction.commit()", code=at("src/vqapr/project/store.py", "def commit", 12),
              disk={".vqapr/workspace.yaml": "쓰임 (atomic)", ".vqapr/instruments.json": "쓰임"},
              mem={"transaction.staged": None, "envelope": "ok · registered{datasets 2, components 2, instruments[stock 10], runs 1} · spoken 4"}),
        ],
        "remember": [
            "등록은 <b>믿지 않고 잰다</b>: parquet은 실제로 열어 스키마 · 유일성 · 기간 · NaN을 묻고, 코드는 실제로 import해 계약을 본다. 배포된 규칙도 예외가 아니다.",
            "디스크에는 맨 끝에 한 번 쓴다(트랜잭션). 도중에 거절되면 등록부는 손대지 않은 그대로다.",
            "등록부는 이름의 장부다. run은 전략·규칙·거래소·dataset을 <i>이름으로</i> 가리키고, 그 이름이 실제 값으로 바뀌는 것은 다음 장면(얼리기)이다.",
        ],
    },
    # ---------------------------------------------------------------- ② check
    {
        "id": "check", "key": "②", "title": "검사",
        "sub": "vqapr check sample-run-short · 11,789 ms · 8,137 호출 · passed [workspace, run, judgments, preflight]",
        "story": (
            "<b>지금 하는 일:</b> 돌리기 전에 묻는다 — \"<code>sample-run-short</code>, 돌려도 되나?\" vqapr은 등록부를 펼쳐 run 정의를 꺼내고, 예/아니오 판정 여섯 개를 <b>모두</b> 묻고(하나 틀렸다고 멈추지 않는다), "
            "마지막으로 run을 <b>얼려 본다</b>: 등록부의 이름들을 실제 값으로 다 풀어 하나의 불변 스냅샷(FrozenRun)이 만들어지는지. 디스크엔 아무것도 쓰지 않는다. "
            "이 트레이스의 11.8 s 중 11.5 s는 집행표 parquet을 처음 스캔하는 비용이다."
        ),
        "frames": [
            F("05_check_short", 12, "check는 네 단계를 모아서 답한다",
              "workspace(등록부를 펼칠 수 있나) → run(그 id가 있나) → judgments(판정 여섯) → preflight(얼릴 수 있나). 앞 단계가 실패하면 뒤는 skipped, 판정이 답을 못 내면 blocked — <b>답하지 못한 것은 통과가 아니다</b>. 이 run은 넷 다 passed.",
              "<code>refuse_a_path</code>(#13: YAML 경로를 주면 이름을 대며 거절) → phase 넷. 판정 phase만 raise 대신 모은다.",
              fn="check() — 네 phase", code=at("src/vqapr/cli/check.py", "for phase in phases", 8),
              mem={"phases": "[workspace, run, judgments, preflight]"}),
            F("05_check_short", 14, "등록부를 펼친다 — 모든 명령의 첫 걸음",
              "<code>Workspace.open</code>은 <code>.vqapr/workspace.yaml</code>(장면 ①이 쓴 그 파일)을 읽어 메모리의 등록부 객체로 만든다: source 4 · dataset 4 · component 4 · run 3. 명령은 YAML이 아니라 <b>id</b>를 받으므로, id가 무엇을 뜻하는지는 이 등록부에서 푼다. "
              "코드가 빈 Workspace를 먼저 만들어 <code>_read()</code>를 부르는 것은 경로가 붙은 읽기 메서드를 얻기 위한 우회일 뿐이다 — 하는 일은 \"파일 하나를 읽는다\"가 전부다. 판정과 얼리기는 이 <b>한 스냅샷</b>을 같이 본다.",
              "<code>Workspace.open</code>(#14, 43 ms) → <code>_read</code>(#17) → <code>read_workspace</code>(#19, 42.7 ms): 문서 종류마다 <code>_decoded</code> → <code>DatasetCodec.to_domain</code> 등 → <code>run_definition('sample-run-short')</code>(#598).",
              fn="Workspace.open() → read_workspace()", code=at("src/vqapr/project/store.py", "def open(", 8),
              disk={".vqapr/workspace.yaml": "읽음"},
              mem={"workspace": "datasets 2(+materialized 2) · components 4 · runs 3", "definition": "sample-run-short: strategy sample-reversal-5d · exchange sample-exchange · compliance [no-short] · 08:00 결정 · 15:30 close 체결"}),
            F("05_check_short", 600, "판정 여섯을 묻는다: 종목 · 명단 · 기간 · 체결 순서 · 데이터 충분성 · 비중 · 출력",
              "각 판정은 \"돌려도 되나\"의 한 조각이다. 종목이 선언돼 있나, 명단이 있나, 기간이 말이 되나, <b>결정마다 그 뒤에 체결할 시각이 있나</b>, 전략이 읽을 데이터가 충분히 있나, 비중 제약이 맞나, 출력 dataset 이름이 비어 있나. 거절은 raise하지 않고 <b>모은다</b>.",
              "<code>judgments</code>(#600, 11,470 ms): <code>_judge_universe</code>(#613) · <code>_judge_roster</code>(#615) · <code>_judge_period</code>(#622) · <code>_judge_execution_ordering</code>(#624) · <code>_judge_member_datasets</code>(#4013, 7 ms) · <code>_judge_weights</code>(#4144) · <code>_judge_outputs</code>(#4146). agenda는 <code>_agenda_once</code>(#605)로 한 번만 파생해 나눠 쓴다.",
              fn="judgments() — 모아서", code=at("src/vqapr/flow/declaration/judgments.py", "def judgments(", 8),
              mem={"judged": "[]", "could_not_answer": "[]"}),
            F("05_check_short", 624, "\"모든 결정에 그 뒤 체결 시각이 있나\" — 집행표에게 묻는다",
              "결정은 매일 08:00, 체결은 그날 첫 15:30. 이 질문에 답하려면 두 목록이 필요하다: 결정 시각 16개(agenda)와 집행표에 실제로 행이 있는 시각 전부(horizon). 둘 다 <b>집행표 parquet을 스캔</b>해서 얻는다 — 그래서 첫 실행에 4.3 s + 7.1 s. "
              "16개 결정 모두 그 뒤에 15:30이 있다. 벽시계가 아니라 <b>표에 있는 시각</b>에게 묻는 이유: 하루의 마지막 시각에 결정하면 그날 체결은 없다.",
              "<code>derived_agenda</code>(#626, 4,340 ms: <code>Workspace.evaluation_times</code> #627 4,263 ms가 distinct <code>trade_at</code>를 읽고 <code>OperationAgenda.expand</code> #2871 41 ms가 16 occurrence로 편다) → <code>bound_execution_table</code> → <code>build_horizon</code>(#3871, 7,114 ms → <code>candidate_instants</code> #3873) → occurrence마다 <code>select_target</code>이 None이면 late.",
              fn="_judge_execution_ordering() → derived_agenda() · build_horizon()", code=at("src/vqapr/flow/declaration/judgments.py", "occurrences = agenda().occurrences", 12),
              disk={"sample/execution.parquet": "읽음 ×2 (distinct trade_at · candidate_instants)"},
              mem={"agenda": "16 occurrence (08:00 Asia/Seoul)", "horizon": "instants 16 (15:30 KST)", "late": "[]"},
              caution="같은 두 스캔을 <code>run</code>이 다시 하면 642 ms(장면 ③)다. 11.8 s는 디스크 캐시의 값이다."),
            F("05_check_short", 4149, "얼리기 1/2: run 층 — 거래소 · 집행표 · 명단 · 초기 계좌를 실제 값으로 푼다",
              "<b>얼린다</b>는 것은 이름을 값으로 바꿔 못 박는 것이다. 등록부의 \"exchange: sample-exchange\"는 거래소 코드의 fingerprint와 실제 로드된 객체가 되고, \"execution: sample-execution / fill at 15:30 close\"는 parquet 경로 · 가격 열 · 체결 규칙이 묶인 <code>ExecutionTable</code>이 되고, "
              "종목 10개와 초기 계좌(cash 1억, LONG_ONLY)가 붙는다. 집행표는 여기서 한 번 더 검증된다(schema · key · 양수 가격). 출력 dataset 이름이 이미 등록돼 있으면 거절.",
              "<code>preflight_run</code>(#4149, 266 ms): <code>derived_agenda</code>(#4153, 169 ms — 두 번째라 빠르다) → <code>_registered_exchange</code>(#7379) → <code>require_declared_roster</code>(#7383) → <code>load_exchange</code>(#7389) → <code>bound_execution_table</code>(#7471) → <code>validate_execution_table</code>(#7490, 43.5 ms) → <code>_validate_execution_requirements</code> · <code>_validate_instrument_universe</code> · <code>_validate_initial_account</code> → <code>_refuse_taken_output</code>(#7561).",
              fn="preflight_run() — run 층", code=at("src/vqapr/flow/declaration/preflight.py", "decide = derived_agenda", 14),
              mem={"exchange": "SampleExchange (listings 10, fingerprint e2b2ab0f…)", "execution_table": "sample-execution · fill 15:30 close"}),
            F("05_check_short", 7567, "얼리기 2/2: 전략 층 — 코드 로드 · 초기 메모리 · 결정 시각 16개 · 각 결정의 체결 시각",
              "전략 코드를 로드해 <code>inputs()</code>가 무엇을 읽겠다는지(sample-prices의 close, 최근 6행) 받아 두고, 초기 메모리·payload를 정하고, agenda를 16개 시각으로 펴고, 16개 각각의 체결 시각을 미리 골라 둔다. 규칙 <code>no-short</code>가 읽을 것(없음)도 합쳐진다. "
              "이 모든 값이 <code>FrozenRun</code> 하나에 들어가면 얼리기가 끝난다. 이제 run은 등록부를 다시 보지 않는다.",
              "<code>_freeze_strategy</code>(#7567, 41.5 ms): <code>load_strategy_model</code>(#7572, 3 ms) → <code>_validate_initial_model_state</code>(#7617) → <code>Component.requirements</code>(#7672) → <code>_freeze_agenda</code>(#7719, 6.4 ms) → <code>_validate_execution_targets</code>(#7855, 21.9 ms) → <code>_freeze_sources</code>(#8080) → <code>FrozenRun.__post_init__</code>(#8103).",
              fn="_freeze_strategy() → FrozenRun", code=at("src/vqapr/flow/declaration/preflight.py", "def _freeze_strategy", 8),
              mem={"frozen": "FrozenRun(sample-run-short: 전략 sample-reversal-5d@fb2406b9, 규칙 [no-short], 거래소, 집행표, 결정 16 · 체결 시각 16, 종목 10, cash 1억, 읽는 것 1, 소스 2)"}),
            F("05_check_short", 8131, "답: 넷 다 통과. 쓴 것은 없다",
              "봉투는 <code>ok:true · passed [workspace, run, judgments, preflight]</code>. check는 판정과 얼리기를 메모리에서만 하고 끝난다 — 얼린 스냅샷은 버려지고, <code>run</code>이 같은 것을 다시 만든다.",
              "<code>success('check')</code>(#8131) → <code>emit</code>(#8136).",
              fn="success('check')", code=at("src/vqapr/cli/envelope.py", "def success", 4),
              mem={"envelope": "ok · passed 4 · blocked 0 · skipped 0"}, disk={".vqapr/": "변화 없음"}),
        ],
        "remember": [
            "<b>등록부를 펼친다</b> = workspace.yaml 한 파일을 읽는다. 명령은 id만 받으므로 모든 명령이 여기서 시작한다.",
            "<b>얼린다</b> = 등록부의 이름들을 실제 값(코드 fingerprint · parquet 경로와 span · 결정 시각 16개와 각각의 체결 시각 · 초기 계좌)으로 다 풀어 불변 스냅샷 하나로 묶는다. 이 뒤로 run은 등록부를 다시 보지 않는다.",
            "check는 판정을 <b>모아서</b> 답하고 아무것도 쓰지 않는다. 답하지 못한 판정은 통과가 아니다.",
            "\"결정마다 체결 시각이 있나\"는 집행표에 있는 시각에게 묻는다. 그래서 집행표를 스캔한다.",
        ],
    },
    # ---------------------------------------------------------------- ③ run start
    {
        "id": "runstart", "key": "③", "title": "run 시작",
        "sub": "vqapr run sample-run-short · 5,005 ms · 45,436 호출",
        "story": (
            "<b>지금 하는 일:</b> <code>vqapr run sample-run-short</code>. 장면 ②와 같은 판정과 얼리기를 다시 하고(이번엔 첫 거절에서 멈춘다), <code>run.json</code>을 <b>먼저</b> 써 두고, "
            "전략 · 거래소 · 규칙 코드를 로드해 등록 때의 것과 같은지 확인한 뒤, 루프를 조립한다. 루프는 하나(<code>RunLoop</code>)이고 시계는 둘이다: 전략이 결정하는 시계(매일 08:00)와 시장의 시계(매일 15:30). "
            "둘을 한 줄로 합치면 이벤트 32개가 된다."
        ),
        "frames": [
            F("06_run_short", 12, "같은 판정, 같은 얼리기 — 이번엔 거절이면 멈춘다",
              "등록부를 펼치고, run 정의를 꺼내고, 판정 여섯을 묻고(장면 ②에서 11.5 s였던 두 스캔이 캐시 덕에 642 ms), 얼린다. 결과는 장면 ②와 똑같은 <code>FrozenRun</code>. 거절은 같은 봉투 모양으로 나간다.",
              "<code>refuse_a_path</code>(#13) → <code>Workspace.open</code>(#14, 43 ms) → <code>run_definition</code>(#598) → <code>preflight_run</code>(#600, 907 ms: <code>require_judged</code> #601 642 ms → preflight.py의 <code>preflight_run</code> #4149 264 ms) → <code>FrozenRun</code>(#8103) → <code>execute_run</code>.",
              fn="_run_one() → preflight_run()", code=at("src/vqapr/cli/run.py", "workspace = Workspace.open(project_root)", 9),
              mem={"frozen": "FrozenRun(sample-run-short) — check와 같은 것", "store_root": ".vqapr"}),
            F("06_run_short", 8131, "run.json을 먼저 쓴다 — 도중에 죽어도 무엇을 시도했는지 남도록",
              "집행표를 한 번 더 검증하고, 종목 명단을 <b>run당 한 번</b> 읽고(기록과 봉투가 이 한 번의 읽기에서 나온다), 두 parquet의 digest를 찍고, <code>runs/sample-run-short/run.json</code>을 쓴다. 전략은 아직 돌지 않았다.",
              "<code>_own_output_or_refuse</code>(#8132) → <code>validate_execution_table</code>(#8138, 44 ms) → <code>registered_roster</code>(#8190, 556 ms: <code>read_roster_table</code> #8196) → <code>_source_digests</code>(#8232) → <code>freeze_run_record</code>(#8237 → <code>write_run_record</code> #8248 → <code>write_atomically</code> #8314).",
              fn="orchestration.run()", code=at("src/vqapr/flow/orchestration.py", "roster = registered_roster(", 8),
              disk={".vqapr/runs/sample-run-short/run.json": "쓰임 (declared_digest ea6da225…, 종목 10, 체결 15:30 close)"},
              mem={"roster": "stock 10 · digest 875b5fe1…"}),
            F("06_run_short", 8316, "부품 셋을 로드하고, 등록 때와 같은 코드인지 본다",
              "전략 · 거래소 · 규칙을 실제로 로드한다. 로드된 바이트의 fingerprint를 다시 찍어 두는데(등록 후 파일을 고쳤다면 여기서 갈린다 — 기록엔 둘 다 적힌다), 전략이 읽겠다는 것이 얼린 것과 다르면 거절한다. "
              "이 검사들은 기록 디렉터리를 잡기 <b>전</b>이다: 어긋난 부품은 기록을 남기지 못한다.",
              "<code>load_strategy_model</code>(#8317, 2.7 ms) · <code>load_exchange</code>(#8362, 4.1 ms) · <code>load_compliance</code>(#8445, 1.2 ms) → <code>_as_loaded_fingerprints</code>(#8459) → <code>Component.requirements</code>(#8489 → 저자의 <code>inputs()</code> #8490) drift 검사 → <code>compliance_requirements</code>(#8517).",
              fn="_run_strategy() — 로드와 drift", code=at("src/vqapr/flow/orchestration.py", "strategy = load_strategy_model(", 12),
              mem={"strategy": "SampleReversal5d (memory {}, payload b'')", "exchange": "SampleExchange", "rules": "(NoShort('no-short'),)", "as_loaded": "셋 다 등록과 같음"}),
            F("06_run_short", 8529, "멤버 하나에게 자원 셋을 준다: duckdb 세션 · 관측 스토어 · 기록 writer",
              "전략이 돌 동안 쓸 것들을 한 곳에서 마련한다. duckdb 연결 하나(멤버 전체가 공유 — parquet 메타데이터 캐시가 연결별이라), 얼린 카탈로그 위의 관측 스토어, 그리고 기록 디렉터리를 잡고 lock 파일을 만드는 writer. "
              "전략이 죽으면 writer가 lock을 푼다. 끝나면 기록을 디스크에서 다시 읽어 돌려준다. datamodel run도 같은 함수를 지난다(장면 ⑨).",
              "<code>_run_member</code>(#8529, 3,413 ms, member_kind='strategy'): <code>_FrozenCatalog</code>(#8530) · <code>ScanSession</code>(#8531) · <code>DuckDbObservationStore</code>(#8532) · <code>RunRecordWriter.open</code>(#8536, 1.75 ms) → <code>body</code>(#8543, 3,407 ms) → <code>session.close</code>(#45277) → <code>read_record</code>(#45281).",
              fn="_run_member(member_kind='strategy')", code=at("src/vqapr/flow/orchestration.py", "catalog = _FrozenCatalog(frozen)", 16),
              disk={".vqapr/runs/sample-run-short/strategies/sample-reversal-5d@fb2406b9/": "디렉터리 + lock"},
              mem={"session": "ScanSession (duckdb 연결 1)", "writer": "RunRecordWriter (버퍼 비어 있음)"}),
            F("06_run_short", 8920, "루프를 조립한다: 부품(Part) 하나 + 시장 시계 하나",
              "먼저 run 상태(<code>RunStateRepository</code>: 초기 계좌 root, 전략 메모리, 규칙과 거래소의 메모리, 그리고 <b>sink=writer.append_chunk</b> — 적힌 행이 흘러갈 곳)를 만든다. 그 다음 생성자는 대조만 한다: 초기 계좌가 얼린 것과 같나, 거래소에 <code>execute</code>가 있나, 메모리를 든 부품이 정확히 실렸나. "
              "그리고 핸들러 다섯(콜백 · 발생 · 집행 · 평가 · 규칙)을 만들어 <code>RunLoop(part=StrategyPart, market=MarketClock)</code>으로 묶는다. 전략 run과 datamodel run의 차이는 <b>여기서 무엇을 조립했는가</b>뿐이다.",
              "body(#8543) 안: <code>_window_factory</code> ×2(#8915 전략 창 · #8916 규칙 창) → <code>StrategyEventLoop.__init__</code>(#8920, 5.4 ms): <code>FlowContext</code> → <code>CallbackHandler</code>(#8933) · <code>dispatch_order</code>(#8934: 16 occurrence) · <code>StrategyPart</code>(#9033) · <code>Accrual/Execution/Valuation/ComplianceHandler</code>(#9034–#9037) · <code>MarketClock</code>(#9038) → <code>RunLoop.__init__</code>(#9039) → <code>Account.bind</code>(#9042).",
              fn="StrategyEventLoop.__init__() → RunLoop(part, market)", code=at("src/vqapr/flow/run/loop.py", "part=StrategyPart(self._context, callback),", 16, before=3),
              mem={"loop": "RunLoop(schedule 16, part=StrategyPart, market=MarketClock)", "state": "root v0 · sink=writer.append_chunk · pending 없음"}),
            F("06_run_short", 9043, "걷기 시작: 정렬된 이벤트를 하나씩",
              "루프의 걷기는 여기 한 곳에 쓰여 있다: 시작 훅 → 이벤트를 시각순으로 정렬 → 하나씩 handle → 끝내기. 같은 시각이면 시장 이벤트가 결정보다 <b>먼저</b>다(체결·평가가 끝난 뒤 결정). 이 run에선 결정 08:00, 시장 15:30이라 겹치지 않는다. 32개 이벤트에 2,192 ms.",
              "<code>EventLoop.run</code>(#9043, 2,240 ms) → <code>start</code> → <code>events()</code> 정렬 → <code>RunLoop.handle</code> ×32 → <code>finish</code>.",
              fn="EventLoop.run() — 정렬된 걷기", code=at("src/vqapr/flow/engine/loop.py", "def run(self) -> ResultT:", 11),
              clock={"start_cutoff": "2022-01-04 00:00 +09:00"}),
            F("06_run_short", 9044, "시작 훅: 전략의 메모리를 root에서 싣는다",
              "전략 객체의 memory와 payload를 run 상태의 현재 root에서 복원하고, 규칙과 거래소의 메모리도 복원한다. 부품이 열고 닫는다 — 루프는 계좌도 거래소도 모른다.",
              "<code>RunLoop.start</code>(#9044) → <code>StrategyPart.start</code>(#9045) → <code>CallbackHandler.load_visible_state</code>(#9047, 0.96 ms) → <code>restore_component_memory</code>(#9064).",
              fn="RunLoop.start() → StrategyPart.start()", code=at("src/vqapr/flow/run/loop.py", "self._callback.load_visible_state()", 8, before=6),
              mem={"strategy.memory": "{} (root v0에서)", "component memory": "{no-short: {}, sample: {…}} 복원"}),
            F("06_run_short", 9068, "시계 둘을 한 줄로: 결정 16 + 시장 시각 16 = 이벤트 32",
              "전략 시계는 얼린 agenda의 16개 결정 시각이다. 시장 시계는 집행표에 행이 있는 시각 전부 — 장면 ②에서 7.1 s 걸린 그 질문을 run의 duckdb 세션으로 한 번 더 묻는다(14 ms). "
              "중요한 점: 결정이 체결될 수 있는 시각과 장부가 평가되는 시각은 <b>같은 목록</b>이다. 어떤 결정도 목록에 없는 시각에 체결되지 않는다.",
              "<code>RunLoop.events</code>(#9068, 17 ms): <code>schedule</code>(#9069) → <code>MarketClock.instants</code>(#9087) → <code>execution_horizon</code>(#9088, 14 ms → <code>build_horizon</code>).",
              fn="RunLoop.events() → MarketClock.instants() → execution_horizon()", code=at("src/vqapr/flow/run/loop.py", "def events(self)", 9),
              clock={"events": "32 = 결정 16 (08:00 KST) + 시장 16 (15:30 KST)", "horizon": "2022-01-04 15:30 … 2022-01-25 15:30"},
              disk={"sample/execution.parquet": "읽음 (시각 목록, 1회)"}),
        ],
        "remember": [
            "run은 check와 같은 판정·얼리기를 다시 하고, <b>run.json을 전략이 돌기 전에</b> 쓴다.",
            "부품 셋은 로드 후 등록 때의 코드와 대조된다. 어긋나면 기록 디렉터리를 잡기 전에 멈춘다.",
            "루프는 하나: <code>RunLoop(part, market)</code>. 전략 run은 Part=StrategyPart + MarketClock, datamodel run은 Part=DataModelPart + 시장 시계 없음. 걷기는 <code>EventLoop.run</code> 한 곳.",
            "이벤트 = 결정 시각 ∪ 시장 시각. 같은 시각이면 시장이 먼저.",
        ],
    },
    # ---------------------------------------------------------------- ④ strategy clock
    {
        "id": "decide", "key": "④", "title": "아침 8시: 전략이 결정한다",
        "sub": "occurrence 2022-01-11 08:00 (#21602, 36.5 ms)",
        "story": (
            "<b>지금 하는 일:</b> 2022년 1월 11일 아침 8시. 여섯 번째 결정 시각이다(앞의 다섯 번은 6일치 종가가 안 차서 Hold였다). 루프가 이 이벤트를 전략 부품에 넘긴다. "
            "전략은 창을 읽고 \"최근 5일 수익률 최하위 3종목을 각 30%\"라고 답한다. 프레임워크는 그 답에 도장을 찍어 <b>의도서</b>로 만들고, 오늘 오후 3시 반을 체결 시각으로 예약(<b>pending</b>)한 뒤, "
            "이 결정에서 적힌 행(비중 3행)을 publish 한 번으로 받아들인다."
        ),
        "frames": [
            F("06_run_short", 21602, "루프는 둘로만 나눈다: 시장 이벤트냐, 결정이냐",
              "이 이벤트는 결정(08:00)이므로 부품(<code>StrategyPart</code>)의 것이다. 시장 이벤트였다면 <code>MarketClock.at</code>으로 갔다. 이벤트 자체는 역할을 싣지 않는다 — 누가 처리하는지는 장면 ③의 조립에서 이미 정해졌다.",
              "<code>RunLoop.handle(OccurrenceEvent(sample-run-short.agenda-2022-01-11T0800))</code>(#21602) → <code>self._part.dispatch(occurrence)</code>.",
              fn="RunLoop.handle(OccurrenceEvent)", code=at("src/vqapr/flow/run/loop.py", "def handle(self, event", 9),
              clock={"event": "2022-01-11 08:00 +09:00 (결정 6/16)"}),
            F("06_run_short", 21605, "콜백 준비: 전략의 상태를 복원하고, 창과 기록장을 쥐여 준다",
              "전략 객체의 메모리를 현재 root의 것으로 되돌리고(직전 콜백이 남긴 것), 08:00 기준의 <b>창</b>(<code>ModelWindow</code>: 선언한 데이터만 읽을 수 있는 시야)을 만들고, 이 콜백이 적을 행을 받을 <b>기록장</b>(<code>InvocationRecorder</code>)을 만든다. 계좌는 아직 v0, 보유 없음.",
              "<code>StrategyPart.dispatch</code>(#21603, timed('callback')) → <code>CallbackHandler.dispatch</code>(#21605): <code>_visible_callback_state</code>(#21610) → <code>_restore_callback_state</code>(#21631) → <code>_strategy_window</code>(#21638, 1.8 ms) → <code>_callback_recorder</code>(#21682) → <code>_callback_account_view</code>(#21705) · <code>_account_history</code>(#21723).",
              fn="CallbackHandler.dispatch() — 준비", code=at("src/vqapr/flow/run/callback.py", "result = self._context.strategy.decide(", 13, before=4),
              mem={"window": "ModelWindow(08:00, 종목 10, 읽을 수 있는 것: sample-prices.close 최근 6행)", "recorder": "InvocationRecorder(STRATEGY_CALLBACK)", "account": "v0 (cash 100,000,000 · 보유 없음)"}),
            F("06_run_short", 21726, "당신의 decide: 창을 읽고 Rebalance 하나를 돌려준다",
              "<code>call.read('prices', 'close')</code>로 종목별 6개 종가를 받고, 6개가 다 있는 이름만 남기고, 5일 수익률이 가장 나쁜 3개(K000004 · K000005 · K000006)를 골라 각 30%, 현금 10%로 답한다. "
              "<b>경제만 말한다</b>. 의도서 id, 어느 계좌 버전을 봤는지, 무엇을 읽었는지는 프레임워크가 안다.",
              "<code>SampleReversal5d.decide</code>(#21726, 5.9 ms) → <code>Rebalance.__init__</code>(#21835).",
              fn="SampleReversal5d.decide(call)", author=True, code=("def", 14),
              mem={"result": "Rebalance(K000004 0.3 · K000005 0.3 · K000006 0.3, cash 0.1)"}),
            F("06_run_short", 21866, "도장: Rebalance → 의도서(EconomicPortfolioIntent)",
              "프레임워크가 다섯 가지를 붙인다: id(같은 run의 같은 결정은 항상 같은 id — uuid5), 전략 id, 실제로 읽은 데이터의 참조, 본 계좌 버전(0), 보이는 모델 상태. 그 다음 비중이 예산 안인지(0~1), 종목이 이 run이 거래하는 이름인지 본다.",
              "<code>_stamp_intent</code>(#21866, 4.6 ms) → <code>validate_economic_intent</code>(#21973, 1.3 ms) → <code>_validate_intent_authority</code>(#22007).",
              fn="_stamp_intent() → validate_economic_intent()", code=at("src/vqapr/flow/run/callback.py", "return EconomicPortfolioIntent(", 10),
              mem={"intent": "EconomicPortfolioIntent(951921ba…, targets 3, account_version_seen 0)"}),
            F("06_run_short", 22011, "체결 시각 예약: 오늘 15:30 (pending)",
              "의도서에 체결 시각을 붙인다. 후보는 장면 ③의 시장 시계 목록뿐이므로 \"08:00 이후 첫 15:30\" = 오늘 15:30. 이 시각은 반드시 걸어갈 시각이다. 의도서는 <b>pending</b>이 되어 그 시각을 기다린다 — 한 번에 하나만.",
              "<code>_accept_intent</code>(#22011) → <code>select_target</code>(#22016 → <code>FillRule.select_target</code> #22017) → <code>AcceptedIntent</code>(#22023).",
              fn="_accept_intent() → select_target()", code=at("src/vqapr/flow/run/callback.py", "target = execution_table.select_target(", 12, before=4),
              mem={"accepted": "AcceptedIntent(target 2022-01-11 15:30 KST)"}),
            F("06_run_short", 22028, "프레임워크가 스스로 적는 행: 비중 3행",
              "당신이 아무것도 적지 않아도 <code>vqapr.weight</code> 표에 종목마다 한 행(K000004 0.3 …)이 적힌다 — \"이 결정이 무엇을 원했나\"의 기록. 그 다음 전략이 남긴 메모리를 다음 상태 후보로 준비한다.",
              "<code>_record_defaults</code>(#22028) → <code>InvocationRecorder.append(vqapr.weight)</code> ×3(#22029 · #22037 · #22045) → <code>_candidate_callback_state</code>(#22059) → <code>_callback_evidence</code>(#22145).",
              fn="_record_defaults() → append(vqapr.weight) ×3", code=at("src/vqapr/flow/run/callback.py", 'for target in getattr(intent, "targets", ()):', 8, before=1),
              mem={"recorder.staged": "vqapr.weight 3행"}),
            F("06_run_short", 22347, "publish: 이 결정을 받아들인다 — 행은 sink로, root는 다음 버전으로",
              "run의 상태는 오직 이 문으로만 바뀐다. 기대한 버전이 맞는지 확인하고, 기록장의 행 묶음(비중 3행; 나머지 표는 빈 묶음)을 sink(writer)로 넘기고, 그 다음에야 root를 바꾼다. pending에 의도서가 실린다. "
              "루프에 돌려주는 것은 얇은 흔적(결정 · root 버전)뿐 — root 전체를 들고 있지 않는다.",
              "<code>_prepare_callback_publication</code>(#22256 → <code>prepare_callback</code> #22257) → <code>publish</code>(#22347, 2.9 ms): <code>_deliver</code> → <code>append_chunk</code>(#22349 weight 3행 · #22366 account · #22371 monitoring · #22376 fill: 빈 묶음) → root 교체 → <code>OccurrenceTrace</code>.",
              fn="RunStateRepository.publish()", code=at("src/vqapr/flow/engine/run_state.py", "def publish(", 9),
              mem={"state": "root 교체 · pending=AcceptedIntent(target 01-11 15:30)", "recorder.staged": None, "trace": "OccurrenceTrace(occurrence, intent, root_version)"},
              disk={"writer.buffer": "vqapr.weight +3행 (Arrow, 메모리)"}),
        ],
        "remember": [
            "결정 이벤트는 부품의 것, 시장 이벤트는 시장 시계의 것. 루프는 그 둘만 가른다.",
            "전략은 <b>경제만</b> 말한다(목표 비중). id · 본 계좌 버전 · 읽은 데이터 · 체결 시각은 프레임워크가 붙인다.",
            "체결 시각은 시장 시계 목록에서 고르므로 반드시 온다. 그때까지 의도서는 pending 하나로 기다린다.",
            "상태는 <code>publish</code>로만 바뀐다: 버전 확인 → 행 묶음을 sink로 → root 교체. 루프는 root가 아니라 root 버전만 든다.",
        ],
    },
    # ---------------------------------------------------------------- ⑤ read
    {
        "id": "read", "key": "⑤", "title": "읽기: \"최근 6일 종가\"",
        "sub": "첫 콜백(01-04, #9442 decide 457 ms) 그리고 그 뒤(01-05, #17482 decide 4.5 ms)",
        "story": (
            "<b>지금 하는 일:</b> 전략이 <code>call.read('prices', 'close')</code>라고 할 때 무슨 일이 일어나는지. 첫 번째 콜백(1월 4일)에서는 가격 parquet의 <b>등록된 기간 전체</b>를 한 번 읽어 (시각 × 종목) 판(Panel)으로 피벗해 둔다(0.4 s). "
            "그 뒤 15번의 콜백은 그 판을 인덱스 둘로 <b>썰기만</b> 한다(1 ms). 창은 선언하지 않은 것을 읽지 못하고, 미래를 읽지 못한다."
        ),
        "frames": [
            F("06_run_short", 9442, "첫 콜백의 decide는 457 ms — 거의 전부가 첫 읽기",
              "1월 4일 08:00, 전략이 처음으로 <code>read</code>를 부른다. alias 'prices'가 무엇인지(sample-prices의 close, 최근 6행)를 <code>inputs()</code> 선언에서 찾고, 그 dataset의 grain(종목×시각 판)을 확인한 뒤 판을 요청한다. 이 run에서 관측 parquet이 읽히는 것은 <b>이 한 번</b>뿐이다.",
              "<code>SampleReversal5d.decide</code>(#9442, 457 ms) → <code>_DeclaredReads.read</code>(#9443, 455 ms) → <code>requirements_for</code>(#9445) → <code>ModelWindow.grain</code>(#9458) → <code>ModelWindow.panel</code>(#9462, 454 ms).",
              fn="decide() → _DeclaredReads.read()", author=True, code=at("src/vqapr/authoring/context.py", "def read(", 10)),
            F("06_run_short", 9463, "판을 만든다: 등록된 기간 전체를 한 번 스캔해 피벗",
              "판의 identity(파일 digest · dataset · 필드 · 종목 · span)로 캐시를 보고, 없으니 스캔한다. 시점 규칙(<code>available_at &lt;= t</code>, lookback, 종목 목록)은 <b>이 SQL 한 곳</b>에만 쓰여 있다 — 필드는 그 창 안에서 계산되는 식이지 창을 다시 그리는 문장이 아니다. "
              "스캔 결과를 (시각 × 종목) 판으로 피벗한다: 없는 칸은 null, 0을 지어내지 않는다.",
              "<code>DuckDbObservationStore.panel_window</code>(#9463) → <code>panel_identity</code>(#9478) → 캐시 miss → <code>scan.observation_rows</code>(#9480, 425 ms: span 전체, run의 세션으로) → <code>Panel.from_rows</code>(#16422, 13.7 ms).",
              fn="panel_window() → observation_rows() → Panel.from_rows()", code=at("src/vqapr/data/store.py", "panel = self.__panels.get(identity)", 10),
              disk={"sample/observations.parquet": "읽음 (1회, span 전체)"},
              mem={"panels[identity]": "Panel(sample-prices, [close], 종목 10, 시각 735)"}),
            F("06_run_short", 16423, "창 = 판을 시각 축 인덱스 둘로 썬 것",
              "08:00 이하의 마지막 6개 시각 — 모든 종목에 <b>같은</b> 6개. 1월 4일 아침엔 1월 3일 15:30 하나뿐이라 값이 1개다. 종목별 실제 값 개수를 세어 두고(access 기록), 전략의 guard가 그것을 보고 <code>Hold('incomplete-lookback')</code>를 돌려준다.",
              "<code>Panel.window(field, evaluation_time=08:00, lookback=RowsLookback(6))</code>(#16423, 0.04 ms) → <code>PanelWindow.counts</code>(#16425).",
              fn="Panel.window() → PanelWindow", code=at("src/vqapr/data/panel.py", "def window(", 12),
              mem={"window": "PanelWindow(시각 1, 종목 10) → 01-04: Hold"}),
            F("06_run_short", 17482, "두 번째 콜백부터: 4.5 ms",
              "1월 5일. 같은 identity → 캐시 hit → 썰기 0.03 ms. 전략이 <code>window.values[name]</code>으로 열 하나씩 꺼낸다(pyarrow slice). 16번의 콜백이 같은 판을 쓴다.",
              "<code>decide</code>(#17482, 4.5 ms) → <code>read</code>(#17483, 2.1 ms) → <code>panel</code>(#17502, 1.3 ms) → <code>panel_window</code>(#17503 → identity #17516 같음 → <code>Panel.window</code> #17517) → <code>PanelWindow.values</code>(#17532 …) ×10.",
              fn="decide() → read() → panel (cache hit)", author=True, code=at("src/vqapr/data/panel.py", "def values", 8, before=1),
              mem={"window": "PanelWindow(시각 2 → … → 6)"}),
            F("06_run_short", 21638, "창은 두 공장에서 나온다: 전략의 것과 규칙의 것",
              "전략의 창은 전략이 선언한 것만 읽을 수 있고 consumer가 전략이다. 규칙의 창(장면 ⑥)은 규칙들이 선언한 것만 읽을 수 있고, 시장 시각 기준으로 만들어진다. 스토어는 같고 허용 목록만 다르다.",
              "<code>_strategy_window</code>(#21638) → <code>_window_factory.at(08:00)</code> → <code>ModelWindow(evaluation_time, instruments, store, allowed_requirements=layer.requirements, consumer_id='sample-reversal-5d')</code>. 규칙 쪽 공장은 #8916(allowed=compliance_requirements, consumer None).",
              fn="_strategy_window() → _window_factory.at()", code=at("src/vqapr/flow/orchestration.py", "def at(instant: datetime) -> ModelWindow:", 9),
              mem={"window(strategy)": "allowed [sample-prices.close×6], consumer sample-reversal-5d", "window(compliance)": "allowed [], consumer None"}),
        ],
        "remember": [
            "관측 parquet은 run당 <b>한 번</b> 읽힌다: 등록된 기간 전체를 스캔해 판으로 피벗하고, 모든 콜백은 판을 썬다.",
            "시점 규칙(<code>available_at &lt;= t</code> · lookback · 종목)은 SQL 한 곳에만 있다. 미래를 읽는 길이 없다.",
            "<code>RowsLookback(6)</code>은 판의 마지막 6개 시각 — 모든 종목에 같은 6개. 값이 모자란 종목은 그냥 값이 적다.",
            "창은 선언한 것만 읽는다. 전략의 창과 규칙의 창은 허용 목록이 다르다.",
        ],
    },
    # ---------------------------------------------------------------- ⑥ market clock
    {
        "id": "market", "key": "⑥", "title": "오후 3시 반: 체결 → 평가 → 판정",
        "sub": "MarketEvent 2022-01-11 15:30 (#22386, 73.5 ms) · 보유만인 날(01-04, #16812, 46 ms)",
        "story": (
            "<b>지금 하는 일:</b> 같은 날 오후 3시 반, 시장 시계의 한 점. 아침에 예약한 의도서가 이 시각에 도착했다(<b>due</b>). 한 점에서 일어나는 일은 항상 같은 다섯 줄이다: "
            "① 발생(아직 빈 자리) → ② <b>체결</b>: 집행표의 그 시각 행을 보고 주문을 계획하고 거래소에 보내 장부에 적는다 → ③ <b>평가</b>: 방금 적힌 장부를 같은 가격으로 값 매긴다 → "
            "④ <b>판정</b>: 규칙 no-short가 평가된 장부를 본다 → ⑤ <b>마감</b>: 결과를 남긴다. 체결할 것이 없는 날(1월 4일)도 ②만 건너뛰고 나머지는 똑같이 지난다."
        ),
        "frames": [
            F("06_run_short", 22387, "한 점 = 다섯 줄. 각 단계가 같은 값을 받아 자기 칸을 채워 돌려준다",
              "pending의 체결 시각이 지금이면 <code>due</code>다(이미 지났다면 버그로 본다). 그 다음 <code>MarketInstant(at, due)</code> 하나를 accrue → fill → mark → observe → close가 차례로 받아 <code>filled · marked · monitoring · result</code> 칸을 채운다. 뒤 단계는 앞 단계가 남긴 것만 볼 수 있다. 순서는 wiring 테이블이 정하고 테스트가 지킨다.",
              "<code>MarketClock.at</code>(#22387, 73.5 ms): timed('due') · guard(DUE_SNAPSHOT) → pending 확인 → fold 다섯 줄 → <code>DueExecutionTrace(event, result, root.version)</code>.",
              fn="MarketClock.at(event)", code=at("src/vqapr/flow/run/loop.py", "at = MarketInstant(at=instant, due=due)", 10, before=2),
              clock={"event": "2022-01-11 15:30 +09:00 · due = 아침의 의도서"},
              mem={"at": "MarketInstant(at, due, filled None, marked None, monitoring None, result None)"}),
            F("06_run_short", 22391, "① 발생(ACCRUE): 자리만 있다",
              "보유 기간 동안 생긴 것(배당 · 이자 …)을 인식할 자리. 오너 결정으로 지금은 비어 있고, 값을 그대로 돌려준다. wiring 테이블의 다섯 행 중 하나.",
              "<code>AccrualHandler.accrue</code>(#22391, 0.12 ms).",
              fn="AccrualHandler.accrue()", code=at("src/vqapr/flow/run/accrual.py", "def accrue", 6)),
            F("06_run_short", 22394, "② 체결(EXECUTE): 그 시각의 가격 → 주문 계획 → 거래소 → 장부 → commit",
              "집행표에서 15:30의 행(종목별 가격 · 거래 가능 여부)을 꺼낸다 — 이 장면 마지막 프레임의 미리 읽어 둔 창에서 썰어서, 0.56 ms. NAV(현금 + 보유×가격)를 계산하고 목표 비중을 주문(매수 3)으로 바꾼다. "
              "거래소 <code>execute</code>가 주문을 체결로 답하면(3건), 장부(<code>Account.append</code>)가 그것을 받아도 되는지 허락하고, 계좌 v0 → v1로 commit한다. 체결 행 3개가 적힌다.",
              "<code>ExecutionHandler.fill</code>(#22394, 33.5 ms): <code>select_snapshot</code>(#22402 → <code>ExecutionSnapshots.at</code> #22404 0.56 ms) → <code>require_declared</code> → <code>plan_orders</code>(#22439, 9.2 ms) → <code>AcademicExchange.execute</code>(#22660, 4.2 ms: Fill ×3) → <code>fill_entries</code>(#22768) → <code>Account.append</code>(#22794) → <code>prepare_account</code>(#22835: <code>_fill_rows</code> #22977) → <code>commit_append</code>(#23050) → <code>_publish_account_commit</code>(#23056).",
              fn="ExecutionHandler.fill()", code=at("src/vqapr/flow/run/execution.py", "fills = self._context.exchange.execute(", 10),
              mem={"at.filled": "Filled(fills 3, committed_root, snapshot)", "account": "v0 → v1 (첫 체결: 매수 K000004 · K000005 · K000006, cash −29,791,121.70)", "state.pending": "소비됨"},
              disk={"writer.buffer": "vqapr.fill +3행"}),
            F("06_run_short", 23089, "③ 평가(VALUATION): 방금 적힌 장부를 같은 가격으로 값 매긴다",
              "체결에 쓴 그 스냅샷의 가격으로 보유를 평가해 NAV를 정하고, 장부에 mark를 붙여 publish한다. 이때 <code>vqapr.account</code> 표에 행이 적힌다: <code>_ACCOUNT</code> 행(현금 · NAV) + 보유 종목당 한 행 — <b>열로</b> 적는다(장면 ⑦). "
              "체결이 없는 날(1월 4일)은 <code>mark_held</code>: 같은 시각, 같은 가격 원천, 주문만 없다. 계좌 버전은 소비하지 않는다.",
              "<code>ValuationHandler.mark</code>(#23089) → <code>mark_fill</code>(#23090, 13.1 ms): <code>_marks_from_execution_snapshot</code>(#23094) → <code>ValuationService.mark</code>(#23110) → <code>Account.mark</code>(#23160) → <code>append_columns(vqapr.account)</code>(#23215) → <code>prepare_account</code>(#23254) → <code>commit_mark</code>(#23273) → <code>publish_marked</code>(#23279). 보유만인 날: <code>mark_held</code>(#16822).",
              fn="ValuationHandler.mark() → mark_fill()", code=at("src/vqapr/flow/run/valuation.py", "def mark(self, instant: MarketInstant)", 8),
              mem={"at.marked": "Marked(root, NAV, evidence, 3종목 가격)"}, disk={"writer.buffer": "vqapr.account +4행 (_ACCOUNT + 3)"}),
            F("06_run_short", 23325, "④ 판정(COMPLIANCE): 규칙이 Call 하나를 받는다",
              "규칙 <code>no-short</code>가 <b>방금 평가된 그 장부</b>를 본다 — 다시 평가하지도, root를 다시 읽지도 않는다. 규칙은 인자 하나(<code>call</code>)를 받고, 장부는 <code>call.account</code>다(0.11.0). 음수 보유가 없으니 held. "
              "판정 결과는 <code>vqapr.monitoring</code>에 한 행으로 적히고 publish된다. 규칙이 없는 run이면 이 단계는 '판정할 것 없음'(빈 보고가 아니라 None)이다.",
              "<code>ComplianceHandler.observe</code>(#23325, 18.9 ms) → <code>_observe</code>(#23328): <code>require_marked</code>(#23329) → 규칙 창 → <code>evaluate_compliance</code>(#23379 → <code>build_account_view</code> #23387 → <code>NoShort.observe(call)</code> #23397 0.74 ms) → <code>_record_findings</code>(#23432 → append monitoring #23448 → <code>prepare_monitoring</code> #23463 → <code>publish_infallible</code> #23616).",
              fn="ComplianceHandler.observe() → NoShort.observe(call)", code=at("src/vqapr/compliance/evaluation.py", "rule.observe(", 10, before=3),
              mem={"at.monitoring": "MonitoringResult(no-short: passed, measured 0, held)"}, disk={"writer.buffer": "vqapr.monitoring +1행"}),
            F("06_run_short", 23660, "⑤ 마감(close): 결과를 남긴다",
              "체결이 있었으니 feedback(체결 · 평가 요약)을 publish하고 <code>DueExecutionResult</code>를 남긴다. 보유만인 날은 <code>HeldResult</code>. 결과가 없으면 오류 — 한 점은 반드시 결과를 남긴다.",
              "<code>ExecutionHandler.close</code>(#23660, 1.2 ms): <code>FeedbackEvidence</code> → <code>prepare_feedback</code>(#23672) → <code>publish_infallible</code>(#23675). 보유만인 날: <code>close</code>(#17350, 0.07 ms).",
              fn="ExecutionHandler.close()", code=at("src/vqapr/flow/run/execution.py", "def close(self, instant: MarketInstant)", 10),
              mem={"at.result": "DueExecutionResult(account v1, monitoring)", "trace": "DueExecutionTrace(event, result, root_version)"}),
            F("06_run_short", 16831, "(맨 처음에) 집행표를 창으로 미리 읽어 둔다",
              "첫 시장 시각(1월 4일)에 집행표를 시각 여러 개 분량으로 한 번에 읽어 둔다(이 run에선 16개 시각 전부가 한 창에 든다). 그 뒤 모든 체결·평가는 그 창에서 slice만 한다(0.56 ms). 시각마다 쿼리하는 옛길은 0회. 체결과 평가는 같은 읽기의 같은 행을 본다.",
              "1월 4일 <code>mark_held</code>(#16822) 안: <code>execution_snapshot</code>(#16826) → <code>ExecutionSnapshots.__init__</code>(#16829) → <code>at</code>(#16830) → <code>_ensure</code>(#16831, 18 ms → <code>execution_window_table</code> 1회). 이후 <code>at</code> #22404 0.56 ms. <code>exact_execution_snapshot</code> 0회.",
              fn="ExecutionSnapshots.at() → _ensure() (read-ahead)", code=at("src/vqapr/exchange/execution_table.py", "window = self._table.slice(start, stop - start)", 8, before=4),
              disk={"sample/execution.parquet": "읽음 (창 1회; 이후 slice)"}),
        ],
        "remember": [
            "시장 시계 한 점은 다섯 줄이다: 발생 → 체결 → 평가 → 판정 → 마감. 한 값이 단계를 지나며 칸을 채운다.",
            "평가는 <b>체결에 쓴 그 가격</b>으로 방금 적힌 장부를 값 매긴다. 체결 없는 날도 같은 시계, 같은 가격으로 평가한다.",
            "규칙은 평가된 장부를 본다 — 다시 평가하지 않는다. 규칙은 <code>observe(call)</code> 하나를 받고 장부는 <code>call.account</code>다.",
            "집행표는 처음에 창으로 미리 읽고 이후는 썬다. 시각당 쿼리는 없다.",
        ],
    },
    # ---------------------------------------------------------------- ⑦ rows
    {
        "id": "rows", "key": "⑦", "title": "적힌 행은 어디로 가나",
        "sub": "recorder(열) → chunk → publish → sink(writer, 메모리) ×203 → run 끝에 seal → 4 parquet + strategy.json → 배분 dataset",
        "story": (
            "<b>지금 하는 일:</b> 장면 ④와 ⑥에서 '행이 적힌다'고 했다. 그 행은 dict가 아니라 <b>열</b>로 쌓이고, 표마다 한 묶음(<code>RecordChunk</code>)이 되어 publish 때 sink(writer)로 넘어가 Arrow 표로 메모리에 쌓인다. "
            "도는 동안 디스크에 행은 없다(lock과 progress.json만). 32개 이벤트가 끝나면 표 넷을 parquet으로 굳히고(seal), <code>strategy.json</code>을 쓰고, 마지막으로 이 전략의 비중을 다른 전략이 읽을 수 있는 dataset으로 등록한다."
        ),
        "frames": [
            F("06_run_short", 16933, "행은 열로 적힌다",
              "평가가 account 표에 적을 때 \"행 N개\"가 아니라 \"열 7개(instrument, cash, nav, quantity, price, observed_at, account_version)\"를 건넨다. 3,000종목의 장부도 dict 3,000개가 아니라 튜플 일곱이다. 검사도 열 단위. "
              "행마다 <code>sequence</code>가 붙는데, 이 번호는 <b>run 전체의 한 카운터</b>에서 나온다 — 결정 행 · 평가 행 · 체결 행이 한 순서에 선다.",
              "평가의 recorder(#16923, stage VALUATION) → <code>append_columns(vqapr.account)</code>(#16933, 0.86 ms) → <code>next_sequence</code>(#16949 → <code>RunStateRepository.next_sequence</code> #16950). 저자의 <code>append</code>(행 하나, #22029)도 같은 recorder의 열에 쌓인다.",
              fn="InvocationRecorder.append_columns()", code=at("src/vqapr/authoring/records.py", "def append_columns", 16),
              mem={"recorder._columns[vqapr.account]": "열 7 × 1행 (01-04: 보유 0)", "sequence": "run 카운터"}),
            F("06_run_short", 16955, "표마다 묶음 하나: RecordChunk",
              "publish 직전에 recorder가 표(weight · account · monitoring · fill)마다 묶음을 만든다. 저자/평가의 열에 봉투 열 다섯(run_id · producer_id · stage · event_time · sequence)을 붙인다. 묶음은 떼어낸 뒤 다시 검사하지 않는다 — 모든 셀은 이미 append에서 통과했다.",
              "<code>staged_chunks</code>(#16955, 0.45 ms) → <code>RecordChunk</code> ×4(#16957–#16963) → <code>RunStateRepository._stage</code>: sink가 있으면 root는 아무것도 들지 않고 묶음은 prepared 후보에 실린다.",
              fn="InvocationRecorder.staged_chunks() → RecordChunk ×4", code=at("src/vqapr/domain/shapes.py", "class RecordChunk", 12),
              mem={"prepared.new_chunks": "(weight 0행, account 1행, monitoring 0행, fill 0행)"}),
            F("06_run_short", 16978, "publish 안에서 sink로 — root를 바꾸기 전에",
              "받아들이기 직전, 묶음들을 차례로 sink(<code>writer.append_chunk</code>)에 넘긴다. root를 바꾸기 <b>전</b>이라, 디스크가 꽉 차서 sink가 실패하면 이 이벤트가 실패하고 직전까지의 상태는 온전하다. run 전체에서 71번의 publish가 203개의 묶음을 넘겼다(빈 묶음 포함).",
              "<code>publish_infallible</code>(#16977) → <code>_deliver</code>(#16978, 3.4 ms) → <code>self._sink(chunk)</code> ×4.",
              fn="RunStateRepository._deliver() → sink", code=at("src/vqapr/flow/engine/run_state.py", "def _deliver", 12)),
            F("06_run_short", 16984, "writer: 열에서 곧장 Arrow 표로, 메모리에",
              "빈 묶음이면 heartbeat만(lock의 시각을 갱신, 5초마다 progress.json). 아니면 열에서 바로 Arrow 표를 만들어 표별 버퍼에 붙인다 — 행을 걷지 않는다. 버퍼가 한계를 넘으면 임시 파일로 흘리는데(spill), 이 run에선 0회. 도는 동안 디스크에 행은 없다.",
              "<code>RunRecordWriter.append_chunk</code>(#16984, 1.9 ms — account 1행): <code>row_count</code> 0이면 <code>heartbeat</code>(#16979 weight). 아니면 <code>_arrow_table</code> → buffer. run 전체: append_chunk 203 · heartbeat 235 · checkpoint 1 · _spill 0.",
              fn="RunRecordWriter.append_chunk()", code=at("src/vqapr/record/writer.py", "def append_chunk", 29),
              disk={"…/sample-reversal-5d@fb2406b9/progress.json": "checkpoint 1회", "writer.buffer": "account 1행 (Arrow)"}),
            F("06_run_short", 22977, "체결 행은 recorder를 거치지 않는다",
              "체결 행은 장부의 entry에서 바로 묶음이 된다(zero-dealt 체결도 — 시장의 사실은 남긴다). 봉투 열 다섯은 여기서 직접 찍고, sequence는 같은 run 카운터에서 받는다. 그래서 체결 행도 결정·평가 행과 한 순서에 선다.",
              "<code>prepare_account(PreparedAppend)</code>(#22835) → <code>_fill_rows</code>(#22977) → <code>next_sequence</code> ×3(#22978–#22980) → <code>_stage</code>(#23043) → <code>_publish_account_commit</code>의 publish에서 sink로.",
              fn="_fill_rows() → _stage()", code=at("src/vqapr/flow/engine/run_state.py", "rows = _fill_rows(", 8, before=3),
              mem={"chunk": "vqapr.fill 3행 (K000004 · K000005 · K000006, kind stock)"}),
            F("06_run_short", 44651, "32개 이벤트가 끝나면: pending이 없어야 하고, 마지막 상태를 확정한다",
              "마지막 결정(1월 25일 08:00)은 그날 15:30에 체결됐으니 pending은 비어 있다(남아 있으면 오류). 마지막 root를 finalize하고, 걷는 데 든 시간을 phase별로 모아 결과를 만든다(callback 0.98 s · due 1.21 s · total 2.24 s).",
              "<code>RunLoop.finish</code>(#44651) → <code>StrategyPart.finish</code>(#44652, 0.68 ms) → <code>FinalizationEvidence</code> → <code>state.finalize</code> → <code>SimulationResult(traces 32, root v11, timing)</code>.",
              fn="RunLoop.finish() → StrategyPart.finish()", code=at("src/vqapr/flow/run/loop.py", "root = self._context.state.finalize(RunFinalization(finalization))", 6, before=5),
              mem={"result": "SimulationResult(32 traces, root v11, timing{callback 0.98, due 1.21, total 2.24})"}),
            F("06_run_short", 44678, "굳히기(seal): 표 넷을 parquet으로, 그 다음 strategy.json",
              "버퍼의 Arrow 표들을 표마다 <code>all.parquet</code> 하나로 쓴다(account 49행 · fill 41행 · monitoring 16행 · weight 33행). 그 다음에야 <code>strategy.json</code>(계좌 · 계약 보고 · timing · 로드된 fingerprint)을 원자적으로 쓰고 lock을 푼다. "
              "<b>표가 먼저, 기록이 나중</b>: strategy.json이 있다 = 끝까지 갔다. 이 트레이스에선 account 표 쓰기가 769 ms.",
              "<code>freeze_strategy_record</code>(#44678, 806 ms): <code>writer.counts</code>(#44684) · <code>contract_report</code>(#44685: no-short 16/16 held) → <code>StrategyRecord</code> → <code>RunRecordWriter.finish</code>(#44768): <code>_seal</code>(#44879, 789 ms → <code>_write_parquet</code> ×4: #44882 769 ms · #44902 · #44917 · …) → <code>write_atomically</code>(#44953) → <code>_unlock</code>(#44955).",
              fn="freeze_strategy_record() → RunRecordWriter.finish() → _seal()", code=at("src/vqapr/record/writer.py", "def _seal", 22),
              disk={"…/tables/vqapr.account/all.parquet": "49행 · 16 시각", "…/tables/vqapr.fill/all.parquet": "41행 · 11", "…/tables/vqapr.monitoring/all.parquet": "16행 · 16", "…/tables/vqapr.weight/all.parquet": "33행 · 11", "…/strategy.json": "쓰임 (atomic)", "…/progress.json": None, "writer.buffer": None}),
            F("06_run_short", 44961, "비중을 dataset으로 등록한다 — 다음 전략이 읽을 수 있게",
              "run이 약속한 <code>writes: sample-reversal-5d-short-weights</code>. 방금 쓴 weight 표를 기록에서 다시 읽어(저장된 run은 메모리에 행을 남기지 않으므로) available_at=결정 시각인 dataset으로 만들고, datamodel과 <b>같은 문</b>(<code>RunOutput.register</code>: 굳히기 → 네 단계 검증 → 등록부 트랜잭션)으로 등록한다. "
              "그 다음 봉투를 만들며 끝난다.",
              "<code>_publish_allocation</code>(#44961, 340 ms): <code>read_table(vqapr.weight)</code>(#44962, 93 ms) → <code>RunOutput.register</code>(#45045, 240 ms: <code>_seal</code> #45069 → <code>validate</code> → <code>Workspace.transaction</code> #45173 → <code>register_dataset</code> #45191 → <code>commit</code> #45198) → <code>_strategy_envelope</code>(#45290) → <code>success('run.complete')</code>(#45430).",
              fn="_publish_allocation() → RunOutput.register()", code=at("src/vqapr/flow/orchestration.py", "output = RunOutput(", 12),
              disk={".vqapr/materialized/sample-reversal-5d-short-weights/all.parquet": "쓰임 (33행)", ".vqapr/workspace.yaml": "다시 쓰임 (dataset +1)"},
              mem={"envelope": "ok · run.complete · strategies{sample-reversal-5d: completed, account_version 11, fills{orders 41, dealt 24}, contract{no-short ok}}"}),
        ],
        "remember": [
            "행은 열로 쌓이고, 표마다 묶음이 되어 publish 안에서 sink로 간다 — root를 바꾸기 전에. 도는 동안 디스크에 행은 없다.",
            "sequence는 run 하나의 카운터다: 결정 행 · 평가 행 · 체결 행이 한 순서에 선다.",
            "끝에 한 번: 표 넷을 parquet으로 굳히고, 그 다음 strategy.json. 파일이 있다 = 끝까지 갔다.",
            "run의 <code>writes</code>는 datamodel과 같은 문으로 등록부에 dataset이 된다.",
        ],
    },
    # ---------------------------------------------------------------- ⑧ readers
    {
        "id": "readers", "key": "⑧", "title": "결과 읽기",
        "sub": "list runs (689 호출 · 59 ms) · show run (30 · 13 ms) · show strategy (27 · 11 ms) · list strategies --run (30 · 12 ms) · usage 거절 (35 · 14 ms)",
        "story": (
            "<b>지금 하는 일:</b> 결과를 보는 명령 넷. <code>list runs</code>만 등록부를 펼치고(그게 비용의 전부), 나머지는 <b>기록 파일</b>(run.json · strategy.json)만 읽는다 — parquet도 등록부도 열지 않아 10 ms대다. "
            "'끝났다'는 파일 하나의 존재로 정의된다."
        ),
        "frames": [
            F("08_list_runs", 11, "list runs: 등록부를 펼쳐 run마다 한 줄",
              "run 셋(sample-run · sample-run-short · sample-features-run)을 종류 · 모델 · 거래소 · 체결 규칙 · writes와 함께, 그리고 <b>recorded</b>(끝난 기록의 ref)를 붙여 보여준다. 689 호출 중 630이 등록부 읽기다.",
              "<code>list_.run</code>(#11) → <code>Workspace.open</code>(#12, 45 ms: <code>read_workspace</code> #17 → <code>_linked</code> #18) → <code>run_definitions</code>(#643) → <code>_summarize</code> ×3(#648 · #652 · #658).",
              fn="list_.run() → Workspace.open() → _summarize() ×3", code=at("src/vqapr/cli/list_.py", "def _summarize", 8),
              mem={"envelope": "count 3 · sample-run-short.recorded [sample-reversal-5d@fb2406b9]"}),
            F("09_show_run", 11, "show run: run.json 하나",
              "등록부를 열지 않는다. runs/ 아래 run.json이 있는 디렉터리를 세고, 그 파일을 읽고, 아래에 strategy.json이 <b>있는</b> 전략 디렉터리만 ref로 보여준다. 봉투엔 얼렸던 것들(digest · 종목 · 체결 규칙 · 초기 계좌 · 소스 digest)이 그대로 있다.",
              "<code>show.run</code>(#11, 2.1 ms) → <code>run_ids</code>(#12) → <code>read_run_record</code>(#16) → <code>record_view</code>(#19) → <code>strategy_refs</code>(#20) · <code>datamodel_refs</code>(#23) → <code>success('run.show')</code>(#24).",
              fn="show.run() → read_run_record() → strategy_refs()", code=at("src/vqapr/record/reader.py", "def strategy_refs", 14),
              disk={".vqapr/runs/sample-run-short/run.json": "읽음"}),
            F("10_show_strategy", 12, "show strategy <run>/<id>@<fp8>: strategy.json 하나",
              "ref를 풀어 strategy.json을 읽는다. 표는 읽지 않는다 — 봉투의 표 크기(account 49/16 · fill 41/11 · monitoring 16/16 · weight 33/11)는 writer가 쓰면서 셌던 수다. 최종 계좌(cash 10,688,433 · 보유 3), 계약 보고, timing, 로드된 fingerprint도 기록에서.",
              "<code>resolve_strategy</code>(#12) → <code>resolve_member</code>(#13) → <code>strategy_refs</code>(#14) → <code>read_strategy_record</code>(#17 → <code>read_member_record</code> #18 → <code>_mapping_at</code> #20) → <code>success('strategy.show')</code>(#21).",
              fn="resolve_member() → read_member_record()", code=at("src/vqapr/record/reader.py", "def read_member_record", 12),
              disk={"…/strategies/sample-reversal-5d@fb2406b9/strategy.json": "읽음"}),
            F("10b_show_strategy_usage", 13, "짧게 부르면 거절하고, 고치는 법을 말한다",
              "<code>show strategy sample-run-short</code>(run id만)는 거절이다: 봉투에 \"<code>&lt;run-id&gt;/&lt;strategy-id&gt;@&lt;fp8&gt;</code>가 필요하다\", 그리고 \"<code>vqapr list strategies --run &lt;run-id&gt;</code>로 ref를 보라\". status 400, exit 1.",
              "<code>resolve_member</code>(#13) → <code>InputError</code>(#14, 3.1 ms — <code>Cause.here</code> #16이 'vqapr/cli/show.py:317 (resolve_member)'를 적는다) → <code>failure</code>(#23) → 봉투 <code>argument.value_invalid</code>.",
              fn="resolve_member() → InputError → failure()", code=at("src/vqapr/cli/show.py", "if not slash or not rest", 8),
              mem={"envelope": "ok:false · argument.value_invalid (400) · retry: list strategies --run"}),
            F("12_list_strategies", 12, "list strategies --run: 끝난 기록 + 끝나지 않은 디렉터리",
              "strategy.json이 있는 디렉터리는 <code>completed</code>로(계좌 버전 · 계약 실패 여부 · 표 목록), 없는 디렉터리는 <code>running</code>(lock이 신선) 또는 <code>unfinished</code>(죽었거나 거절됨)로. 이 run엔 완료 하나.",
              "<code>_strategies</code>(#12, 1.6 ms) → <code>strategy_refs</code>(#14) → <code>read_strategy_record</code>(#17) → <code>unfinished_strategy_refs</code>(#21 → <code>unfinished_member_refs</code> #22).",
              fn="_strategies() → strategy_refs() · unfinished_strategy_refs()", code=at("src/vqapr/cli/list_.py", "for ref in strategy_refs(root, run_id)", 12),
              mem={"envelope": "count 1 · [sample-reversal-5d@fb2406b9: completed, account_version 11]"}),
        ],
        "remember": [
            "<code>list runs</code>는 등록부를, 나머지는 기록 파일만 읽는다. parquet은 열지 않는다.",
            "'끝났다'는 파일 하나다: run은 run.json, 전략은 strategy.json. 없으면 unfinished.",
            "기록 ref는 <code>&lt;run-id&gt;/&lt;id&gt;@&lt;fp8&gt;</code>. 짧게 부르면 거절하고 <code>list strategies --run</code>을 가리킨다.",
        ],
    },
    # ---------------------------------------------------------------- ⑨ datamodel
    {
        "id": "dm", "key": "⑨", "title": "datamodel: 같은 루프, 시계 하나",
        "sub": "vqapr run sample-features-run · 1,724 ms · 20,128 호출 · 16 세션 · 108 행",
        "story": (
            "<b>지금 하는 일:</b> <code>features.py</code>는 매일 16:00에 종목별 5일 수익률 하나를 계산해 내놓는 datamodel이다. 같은 <code>vqapr run</code>, 같은 판정·얼리기, 같은 멤버 자원, 같은 <code>RunLoop</code> — 다른 것은 조립뿐이다: "
            "부품이 <code>DataModelPart</code>이고 시장 시계가 <b>없다</b>. 계좌도 거래소도 없으므로 세션 사이에 아무 일도 없다. 끝나면 결과가 dataset <code>sample-features-values</code>로 등록된다."
        ),
        "frames": [
            F("07_run_features", 12, "같은 _run_one, datamodel로 얼려진다",
              "판정 중 '전략이 읽을 데이터가 충분한가'가 이번엔 datamodel의 첫 세션에 대해 묻고(254 ms), 얼리기는 datamodel 버전으로 간다: 코드 로드 · <code>inputs()</code>(sample-prices.close 최근 6행) · agenda 16:00 · 출력 필드 [value]. 거래소 · 집행표 · 계좌는 없다.",
              "<code>preflight_run</code>(#624, 456 ms) → <code>_preflight_datamodel_run</code> → <code>_freeze_datamodel</code>(#7341, 11.9 ms: import #7351 → <code>inputs()</code> #7355) → <code>FrozenRun(datamodel=…)</code> → <code>orchestration.run</code> → <code>_run_datamodels</code>(#7616).",
              fn="_run_one() → preflight_run() → _freeze_datamodel()", code=at("src/vqapr/flow/declaration/preflight.py", "def _freeze_datamodel", 8),
              mem={"frozen": "FrozenRun(sample-features-run: datamodel sample-features, value_fields [value], 세션 16 (16:00))"}),
            F("07_run_features", 7745, "같은 멤버 자원: 세션 · 스토어 · writer",
              "run.json을 먼저 쓰고, 코드를 로드해 등록과 대조하고, 장면 ③과 같은 <code>_run_member</code>로 들어간다(<code>member_kind='datamodel'</code>만 다르다).",
              "<code>freeze_run_record</code>(#7620) → <code>_run_datamodel</code>(#7668) → <code>_run_member</code>(#7745, 1,181 ms) → body(#7759).",
              fn="_run_datamodel() → _run_member()", code=at("src/vqapr/flow/orchestration.py", "return _run_member(", 8),
              disk={".vqapr/runs/sample-features-run/run.json": "쓰임", "…/datamodels/sample-features@67d5fa16/": "디렉터리 + lock"}),
            F("07_run_features", 7766, "조립: RunLoop(part=DataModelPart, market=None)",
              "출력 문(<code>RunOutput</code>: 어느 dataset으로, 어떤 필드로, 어느 run·기록이 만들었는지)을 만들고, 창 공장 하나, 그리고 <code>ComputeHandler</code>를 부품으로 감싸 <code>RunLoop</code>에 넣는다. 시장 시계 인자는 없다.",
              "<code>RunOutput.__init__</code>(#7762) → <code>DataModelEventLoop.__init__</code>(#7766, 5.7 ms): <code>ComputeHandler</code>(#7767) → <code>DataModelPart</code>(#7879) → <code>RunLoop.__init__</code>(#7880).",
              fn="DataModelEventLoop.__init__() → RunLoop(part, market=None)", code=at("src/vqapr/flow/run/loop.py", "part=DataModelPart(compute, output),", 6, before=3),
              mem={"loop": "RunLoop(schedule 16, part=DataModelPart, market=None)"}),
            F("07_run_features", 7883, "걷기: 시작 훅이 출력 디렉터리를 비우고, 이벤트는 16개뿐",
              "<code>start</code>가 죽은 run이 남긴 출력 디렉터리를 치운다. <code>events()</code>는 시장 시계가 없으니 세션 16개만(장면 ③의 17 ms 대 0.97 ms). 1,059 ms 중 첫 handle이 846 ms.",
              "<code>EventLoop.run</code>(#7883) → <code>RunLoop.start</code>(#7884) → <code>DataModelPart.start</code>(#7885) → <code>RunOutput.open</code>(#7886) → <code>RunLoop.events</code>(#7887, 0.97 ms) → handle ×16 → <code>finish</code>(#19687).",
              fn="EventLoop.run() → DataModelPart.start() → RunOutput.open()", code=at("src/vqapr/flow/run/loop.py", "self._output.open()", 10, before=4),
              clock={"events": "16 (16:00 KST, days_from sample-prices)"}),
            F("07_run_features", 8028, "한 세션: 창 → compute(당신) → 검증 → available_at 도장 → 출력에 붙임",
              "장면 ⑤와 같은 읽기(첫 세션에서 판을 만든다: 805 ms). 당신의 <code>compute</code>가 종목별 dict를 돌려주면, 선언된 종목·필드만 남기고, 창의 접근 기록에서 <code>available_at</code>(이 값이 언제부터 알 수 있었나)을 정해 붙이고, 출력에 쌓는다. 첫 세션은 6일치가 안 차서 0행. 두 번째 세션부터 6.7 ms.",
              "<code>ComputeHandler.dispatch</code>(#8028, 846 ms): <code>ModelWindow</code>(#8033) → <code>SampleFeatures.compute</code>(#8069, 843 ms → <code>read</code> #8070 → <code>panel_window</code> #8090 → <code>observation_rows</code> #8107 805 ms) → <code>validated_output</code>(#15115) → <code>derived_available_at</code>(#15118) → <code>RunOutput.append</code>(#15120, rows=[]). 두 번째: #15125 6.7 ms.",
              fn="ComputeHandler.dispatch() → SampleFeatures.compute()", code=at("src/vqapr/flow/run/compute.py", "raw = self._model.compute(", 12, before=3),
              disk={"sample/observations.parquet": "읽음 (1회, span 전체)"},
              mem={"trace": "DataModelTrace(row_count 0, accesses)"}),
            F("07_run_features", 15120, "출력은 세션마다 Arrow로 메모리에 쌓인다",
              "첫 비어 있지 않은 세션의 행이 스키마를 정하고, 뒤 세션이 안 맞으면 pyarrow의 문장 그대로 거절한다. value는 float(dataset 필드는 DOUBLE). 16 세션 동안 디스크 쓰기 0회.",
              "<code>RunOutput.append</code> ×16 → <code>pa.Table.from_pylist</code>. <code>_write</code>(spill) 0회.",
              fn="RunOutput.append()", code=at("src/vqapr/flow/run/output.py", "table = pa.Table.from_pylist(", 8, before=2),
              mem={"output": "buffered (Arrow) · rows 108 / sessions 16"}),
            F("07_run_features", 19721, "끝: 굳히기 → 네 단계 검증 → 등록부 트랜잭션 → 그 다음에야 datamodel.json",
              "108행을 <code>all.parquet</code> 하나로 쓰고, 장면 ①과 <b>같은 네 단계</b>로 검증하고(73 ms), 등록부에 dataset으로 등록한다(어느 run·어느 기록이 만들었는지 함께). 실패하면 디렉터리를 지운다. 그 다음에 기록 <code>datamodel.json</code>. "
              "순서가 이렇다: <b>등록이 상품</b>이고 기록은 '끝났다'의 표시다.",
              "<code>DataModelPart.finish</code>(#19688) → <code>RunOutput.register</code>(#19721, 95 ms): <code>with_producer</code>(#19737) → <code>_seal</code>(#19744) → <code>validate</code>(#19746, 73 ms) → <code>Workspace.transaction</code> → <code>register_dataset</code>(#19866) → <code>commit</code>(#19873) → <code>freeze_datamodel_record</code> → <code>RunRecordWriter.finish(kind='datamodel')</code>(#19985) → <code>_datamodel_envelope</code>(#20121).",
              fn="RunOutput.register() → validate() → Transaction.commit() → finish(kind='datamodel')", code=at("src/vqapr/flow/run/output.py", "self._seal()", 8, before=1),
              disk={".vqapr/materialized/sample-features-values/all.parquet": "쓰임 (108행)", ".vqapr/workspace.yaml": "다시 쓰임 (dataset +1)", "…/datamodels/sample-features@67d5fa16/datamodel.json": "쓰임"},
              mem={"envelope": "ok · run.complete · datamodels{sample-features: rows 108, sessions 16, dataset_id sample-features-values}"}),
        ],
        "remember": [
            "datamodel run은 <b>같은 RunLoop</b>다: 부품만 <code>DataModelPart</code>, 시장 시계는 없음. 세션 사이에 아무 일도 없다.",
            "판정 · 얼리기 · 멤버 자원 · 읽기(판 1회) · 출력 검증 네 단계 — 전부 전략 run과 같은 길이다.",
            "끝의 순서: 굳히기 → 검증 → 등록 → 기록. 등록이 상품이고 기록은 완료 표시다.",
        ],
    },
    # ---------------------------------------------------------------- ⑩ refusal
    {
        "id": "refuse", "key": "⑩", "title": "거절: 옛 규칙을 등록하면",
        "sub": "vqapr register stale.yaml · 334 ms · 805 호출 · exit 1 — component.signature_invalid (422)",
        "story": (
            "<b>지금 하는 일:</b> 0.10.0식으로 쓴 규칙 <code>observe(self, call, account)</code>를 등록해 본다. 0.11.0에서 규칙은 인자 하나(<code>call</code>)를 받고 장부는 <code>call.account</code>다. "
            "등록은 장면 ①과 같은 길을 가다가 코드 계약 검사에서 멈춘다: 스테이징도 commit도 없고, 봉투가 <b>어떻게 고칠지</b>를 그대로 말한다."
        ),
        "frames": [
            F("11_register_stale", 14, "같은 _apply, 같은 순서 — components에서 멈춘다",
              "문서엔 component 하나(<code>stale-cap</code>, kind compliance, <code>stale_rule.py</code>)뿐. 트랜잭션을 열고 그 섹션으로 간다.",
              "<code>_apply</code>(#14, 317 ms) → 트랜잭션(#649) → <code>_require_declared_ids</code> → <code>_component</code>(#667, 14.2 ms).",
              fn="_apply() → _component()", code=at("src/vqapr/project/registration.py", 'for component_id, body in section("components")', 5),
              mem={"transaction.staged": "[]"}),
            F("11_register_stale", 670, "fingerprint는 되고, import와 생성도 된다",
              "바이트는 읽히고 fingerprint가 찍힌다. 코드는 import되고 <code>StaleCap(compliance_id='stale-cap')</code>도 만들어진다 — 문제는 그 다음이다.",
              "<code>prepare_component</code>(#670) → <code>fingerprint_component</code>(#671) → <code>conformance</code>(#755) → <code>load_compliance</code>(#757 → <code>_load</code> #758 → <code>StaleCap.__init__</code> #767).",
              fn="prepare_component() → conformance() → load_compliance()", code=at("src/vqapr/extension/conformance.py", "component = _LOADERS[ref.kind]", 6, before=2),
              mem={"component": "StaleCap (생성됨)"}),
            F("11_register_stale", 770, "계약 검사: observe는 인자 하나여야 한다",
              "프레임워크는 <code>observe</code>를 위치 인자로 부르므로 이름이 아니라 <b>개수</b>를 본다. 계약은 2(self 포함), 이 클래스는 3. 거절 하나가 만들어진다: 코드 <code>component.signature_invalid</code>, 관찰 \"StaleCap.observe takes 3 (3 required)\", 고치는 법 \"define it as observe(self, arg1)\".",
              "<code>_check_methods</code>(#770, 4.5 ms) → <code>accepts_contract_call</code>(#771 → <code>positional_arity</code> #772 · #773) → <code>_signature_hint</code>(#776) → <code>Failure.bounded</code>(#779) → <code>_Collector.add</code>(#788).",
              fn="_check_methods() → accepts_contract_call() → Failure.bounded()", code=at("src/vqapr/extension/conformance.py", '"component.signature_invalid"', 16, before=6),
              mem={"found": "[component.signature_invalid (422)]"}),
            F("11_register_stale", 790, "거절 → 트랜잭션은 비어 있고 commit은 없다",
              "<code>raise_if_failed</code>가 <code>VqaprError(stage=register)</code>를 던진다. <code>register_component</code>에 닿지 않았으니 스테이징된 것이 없고, 등록부는 그대로다.",
              "<code>Diagnosis.raise_if_failed</code>(#790) → <code>VqaprError.__init__</code>(#791).",
              fn="Diagnosis.raise_if_failed() → VqaprError", code=at("src/vqapr/domain/errors.py", "def raise_if_failed", 6),
              disk={".vqapr/workspace.yaml": "변화 없음"}, mem={"transaction.staged": None}),
            F("11_register_stale", 795, "봉투: ok:false, 422, 그리고 쓸 시그니처",
              "main의 except가 같은 봉투 모양으로 낸다: <code>requirement \"Compliance.observe() must accept 2 positional arguments\" · observed \"StaleCap.observe takes 3 (3 required)\" · fix \"define it as observe(self, arg1) …\" · where \"vqapr/extension/conformance.py:154 (_check_methods)\" · mutation false</code>. exit 1.",
              "<code>failure</code>(#795) → <code>VqaprError.as_dict</code>(#796) → <code>emit</code>(#804).",
              fn="failure() → emit()", code=at("src/vqapr/cli/envelope.py", "def failure", 6),
              mem={"envelope": "ok:false · register · component.signature_invalid (422) · mutation false"}),
        ],
        "remember": [
            "0.11.0의 계약: 규칙은 <code>observe(self, call)</code> 하나를 받고 장부는 <code>call.account</code>다. 옛 시그니처는 <b>등록 시점</b>에 거절된다 — run까지 가지 않는다.",
            "계약 검사는 import·생성까지 한 뒤 인자 <b>개수</b>를 본다. 이름은 상관없다.",
            "거절은 트랜잭션 밖이다: 스테이징도 commit도 없고, 봉투의 fix가 쓸 시그니처를 말한다.",
        ],
    },
]

TABLE = {
    "title": "트레이스가 확인한 것 — 0.11.0이 바꾼 여섯 가지가 보이는 자리",
    "rows": [
        ["<b>루프는 하나다</b> — Part가 전략 시계, MarketClock이 시장 시계 (기록 227)",
         "run: <code>EventLoop.run</code> #9043 → <code>RunLoop.handle</code> ×32 → <code>StrategyPart.dispatch</code> ×16 · <code>MarketClock.at</code> ×16 · datamodel: <code>RunLoop.handle</code> ×16 → <code>DataModelPart.dispatch</code>, <code>RunLoop.events</code> #7887 0.97 ms(market None). 같은 <code>flow/engine/loop.py:102</code>",
         "<code>StrategyEventLoop</code>·<code>DataModelEventLoop</code>는 조립(생성자)만 남았다. 무엇이 다른지는 <code>RunLoop(part, market)</code>의 인자가 다 말한다"],
        ["<b>시장 시계 한 점은 fold</b> — 발생 → 체결 → 평가 → 판정 → 마감 (기록 226)",
         "#22387: <code>accrue</code> #22391 → <code>fill</code> #22394 (33.5 ms) → <code>mark</code> #23089 → <code>observe</code> #23325 → <code>close</code> #23660 · 보유만인 점 #16813: <code>fill</code> 0.003 ms(due None) → <code>mark_held</code> #16822",
         "모양이 다른 지역변수 넷 대신 <code>MarketInstant</code> 하나가 단계마다 자기 칸을 채운다. 순서는 wiring 테이블이 말하고 테스트가 붙든다"],
        ["<b>행은 열로 흐른다</b> (기록 221)",
         "<code>append_columns(vqapr.account)</code> #16933 · #23215 → <code>staged_chunks</code> #16955 → <code>RecordChunk</code> ×4 → <code>_deliver</code> #16978 → <code>append_chunk</code> ×203 (Arrow 메모리) · <code>_spill</code> 0 · 끝에 <code>_seal</code> #44879 → <code>_write_parquet</code> ×4",
         "3,000 이름의 평가 행은 dict 3,000이 아니라 튜플 일곱이다. exp_221: 3,000종목 1일 117 s → 34 s"],
        ["<b>집행표는 미리 읽는다</b> (기록 222)",
         "<code>ExecutionSnapshots.__init__</code> #16829 · <code>_ensure</code> #16831 18 ms → <code>execution_window_table</code> 1회 · 이후 <code>at</code> #22404 0.56 ms(slice) · <code>exact_execution_snapshot</code> 0회",
         "체결과 평가가 같은 읽기의 같은 행을 본다. 시각당 쿼리가 사라졌다"],
        ["<b>sequence는 run 하나의 순서</b> (기록 225)",
         "<code>RunStateRepository.next_sequence</code> #16950(평가 recorder) · #22978–#22980(<code>_fill_rows</code>) · 콜백 recorder도 같은 sequencer",
         "결정·평가·체결 행이 한 카운터에 선다. 표를 합쳐 정렬해도 순서가 보존된다"],
        ["<b>역할은 Call 하나</b> — observe(call), call.account (기록 229)",
         "<code>NoShort.observe</code> #23397 (인자: <code>ComplianceContext(window, account, instruments, reads)</code>) · <code>StaleCap.observe(call, account)</code> → <code>_check_methods</code> #770 → <code>component.signature_invalid</code> #779, 등록에서",
         "네 역할이 같은 모양이 됐다: Call 하나 받고 Judgment 하나 돌려준다. 옛 시그니처는 run이 아니라 register에서 죽는다"],
        ["<b>멤버의 자원은 한 함수</b> (기록 228)",
         "<code>_run_member</code> #8529 [strategy] · #7745 [datamodel]: <code>ScanSession</code> 1 · <code>RunRecordWriter.open</code> → body → <code>session.close</code> → <code>read_record</code> · <code>_window_factory</code> #8915(전략) · #8916(규칙)",
         "세 루프가 손으로 만들던 것(세션·스토어·writer·창)이 한 곳에 있다"],
        ["검증은 물리 IO마다 붙어 있지만 <b>한 문이 아니다</b> (다음 캠페인 후보)",
         "dataset: <code>datasets.validate</code> #133(4단계) · 집행표: 같은 <code>validate</code> #321 <b>그리고</b> <code>validate_execution_table</code> check #7490 · run #8138(schema · key · price를 다시) · datamodel 출력: <code>validate</code> #19746 · 명단: <code>read_roster_table</code> #46 · 코드: <code>conformance</code> #524",
         "같은 집행표가 등록 1회 + preflight 1회 + run 1회 = 세 번 스캔된다. 오너 관찰(2026-09-10): 물리 읽기의 검증을 전담하는 문 하나로 모을 것"],
        ["cold 스캔이 절대치를 지배한다",
         "register <code>check_span</code> #210 9,463 ms · check <code>_judge_execution_ordering</code> #624 11,460 ms · run의 같은 판정 <code>require_judged</code> #601 642 ms · 첫 panel <code>observation_rows</code> #9480 425 ms / #8107 805 ms",
         "판끼리 절대치를 비교하지 말 것. 구조의 값은 상대 비교에 있다: 두 번째 콜백 4.5 ms, 두 번째 세션 6.7 ms"],
    ],
}
