# ruff: noqa: E501, RUF001 -- prose data: long lines and typographic characters are the content
# The 0.11.0 spine stepper: ten scenes, every frame standing on a call the profiler recorded.
#
# Rendered by `render.py` (which executes this file with `REPO` bound to the tree the traces
# were taken on). A frame names its trace and call index; `render.py` fills in the definition
# line, the qualified name and the milliseconds from the trace, and reads the code window from
# the tree. The prose is written after reading the traces with `summarize.py`; a number that
# appears in it appears in a trace. Traces: `experiments/exp_230_the_spine_trace/README.md`.


def at(file: str, needle: str, n: int = 8, before: int = 0) -> list[str]:
    """`n` source lines of `file` starting `before` lines above the first line holding `needle`."""
    lines = (REPO / file).read_text(encoding="utf-8").splitlines()  # noqa: F821 - bound by render.py
    for index, line in enumerate(lines):
        if needle in line:
            start = max(0, index - before)
            return [item.rstrip() for item in lines[start : start + n]]
    raise KeyError((file, needle))


def F(trace: str, idx: int, title: str, what: str, **extra) -> dict:
    return {"trace": trace, "idx": idx, "title": title, "what": what, **extra}


HEADER = {
    "title": "vqapr 0.11.0 척추 디버거",
    "storage_key": "vqapr-stepper-0110",
    "eyebrow": "vqapr 0.11.0 · develop (records 221–229, the one-loop campaign) · 2026-09-10 · 실제 실행을 sys.setprofile로 추적한 결과",
    "h1": "vqapr 0.11.0 척추 디버거 — 루프 하나, 시계 둘, 행은 열로",
    "lede": (
        "이 페이지의 모든 프레임은 <b>상상이 아니라 트레이스</b>입니다. <code>vqapr new sample</code>이 만든 sample door(10종목, "
        "2022-01-03 ~ 2024-12-30)에 15세션짜리 전략 run(<code>sample-run-short</code>, Compliance <code>no-short</code> 하나)과 "
        "datamodel run(<code>sample-features-run</code>)을 선언하고, <code>vqapr register → check → run(전략) → run(datamodel) → "
        "list runs → show run → show strategy → list strategies → register(거절)</code>를 <b>명령마다 별도 프로세스</b>에서 "
        "<code>sys.setprofile</code>로 추적했습니다(<code>experiments/exp_230_the_spine_trace/</code>). 프레임의 <code>file:line</code>은 "
        "트레이스가 기록한 함수 정의 줄, <code>#idx</code>는 그 명령 안에서 몇 번째 호출인지, <code>ms</code>는 프로파일러가 켜진 채 잰 "
        "시간입니다. 스니펫은 요약이 아니라 그 시점의 소스 줄입니다. 0.6.0판과 같은 여정을 밟되, 0.11.0이 바꾼 것 — "
        "<b>루프 하나</b>(RunLoop · Part · MarketClock, 기록 227), <b>시장 시계 한 점은 다섯 줄의 fold</b>(기록 226), "
        "<b>행은 열로 흐른다</b>(RecordChunk, 기록 221), <b>집행표는 미리 읽는다</b>(기록 222), <b>run 전체의 sequence</b>(기록 225), "
        "<b>역할은 Call 하나를 받는다</b>(<code>observe(call)</code>, 기록 229) — 가 어느 프레임에서 보이는지를 적었습니다."
    ),
    "facts": [
        {
            "k": "데이터",
            "v": "10 × 735",
            "s": "종목 × 세션, sample door. run 구간은 그중 15세션: 2022-01-04 ~ 2022-01-25. 콜백 16 · 시장 시각 16 · 이벤트 32 (Hold 5 · Rebalance 11)",
        },
        {
            "k": "호출 수",
            "v": "run 45,436",
            "s": "register 945 · check 8,137 · run(datamodel) 20,128 · list runs 689 · show run 30 · show strategy 27 · list strategies 30 · register(거절) 805. 0.6.0판 run은 15세션에 48,220 — 같은 자릿수",
        },
        {
            "k": "디스크에 닿는 파일",
            "v": "4 + 2 + 1",
            "s": "tables/{account · fill · monitoring · weight}/all.parquet · strategy.json · run.json, 그리고 materialized/…-short-weights/all.parquet. 도는 동안은 lock과 progress.json뿐(heartbeat 235회 · checkpoint 1회 · _spill 0회)",
        },
        {
            "k": "시장 시계 한 점",
            "v": "5 줄",
            "s": "accrue → fill → mark → observe → close (<code>MarketClock.at</code>). 16점 중 11점에서 체결(주문 41 · 체결 24 · no_trade 17), 5점은 보유 평가만. no-short: checked 16 · held 16",
        },
        {
            "k": "결과",
            "v": "account v11",
            "s": "cash 10,688,433 · 보유 3(K000002 145 · K000003 46 · K000008 18) · 기록 <code>sample-reversal-5d@fb2406b9</code> · timing callback 0.98 s / due 1.21 s(그중 compliance 0.36) / total 2.24 s",
        },
        {
            "k": "datamodel",
            "v": "108 행",
            "s": "16세션 → <code>sample-features-values</code> all.parquet 하나 · 기록 <code>sample-features@67d5fa16</code> · 같은 RunLoop, 시장 시계 없음",
        },
    ],
    "fix": (
        "<strong>시간 읽는 법.</strong> 모든 ms는 <code>sys.setprofile</code>이 켜진 상태의 값이라 절대치는 실제보다 큽니다. 같은 트레이스 안의 "
        "<b>상대 비교</b>만 읽으십시오. 이 머신에서 parquet의 첫 읽기가 유난히 큽니다 — register의 <code>check_span</code> 9.5 s, check의 "
        "집행표 두 스캔 11.5 s, 첫 panel 읽기 425 ms / 805 ms. 같은 질문을 <code>run</code>이 다시 물을 땐 642 ms입니다(디스크 캐시). "
        "호출 수는 <code>src/vqapr</code>와 프로젝트 component만 센 값이라 판끼리 비교해도 됩니다."
    ),
}

MAP = [
    ("①", "등록", "트랜잭션 1회 · conformance"),
    ("②", "검사", "판정 넷 → freeze"),
    ("③", "run 시작", "preflight · run.json · 루프 조립"),
    {
        "loop": [
            ("④", "전략 시계", "decide → intent → publish"),
            ("⑤", "읽기", "panel 1회 · 슬라이스"),
            ("⑥", "시장 시계", "fold 다섯 줄"),
            ("⑦", "행의 길", "열 → chunk → sink → seal"),
        ]
    },
    ("⑧", "기록 읽기", "list · show · 거절"),
    ("⑨", "datamodel run", "같은 루프 · 시계 하나"),
    ("⑩", "거절", "observe(call) 아니면 등록 전에"),
]

SCENES = [
    # ---------------------------------------------------------------- ① register
    {
        "id": "reg",
        "key": "①",
        "title": "등록",
        "sub": "vqapr register sample.yaml · 15,052 ms · 945 호출 · dataset 2 · component 2 · run 1 · spoken 4문장 — 그리고 short.yaml(compliance no-short + run) 169 ms · 769 호출",
        "frames": [
            F(
                "01_register",
                0,
                "argparse가 register 핸들러를 고른다",
                "<code>build_parser</code>(#1, 7.9 ms: verb 8개의 <code>add_arguments</code>) → <code>parse_args</code> → <code>_resolve_project_root</code>(#10) → "
                "<code>args.handler(args, project_root=...)</code>. 모든 실패는 같은 JSON 봉투로 나가고 <code>workspace_root</code>가 찍힌다. "
                "이 트레이스의 15,052 ms 중 15,041 ms가 핸들러 안이다.",
                fn="main() → handler",
                code=at("src/vqapr/cli/main.py", "def main(", 14),
                mem={
                    "argv": "['--project-root', '.../sample', 'register', '.../sample/sample.yaml']"
                },
                disk={".vqapr/": "없음"},
            ),
            F(
                "01_register",
                11,
                "YAML 하나를 읽어 apply로",
                "<code>read_yaml_mapping</code>(#12, 31 ms) — 선언 문서가 dict 하나로 올라온다. 섹션은 instruments · datasets · components · runs. "
                "이 문서는 instruments 10, dataset 둘(sample-prices · sample-execution), component 둘(전략 · exchange), run 하나(sample-run)다. "
                "<code>apply</code>(#13, registration.py:822)의 반환은 <code>Registered</code> — dict에 <code>.spoken</code>이 붙은 것.",
                fn="register.run() → read_yaml_mapping() → apply()",
                code=at("src/vqapr/cli/register.py", "declaration = Path(args.declaration)", 6),
                mem={"document": "dict (instruments 1, datasets 2, components 2, runs 1)"},
            ),
            F(
                "01_register",
                14,
                "모르는 섹션은 먼저 거절, 그 다음 트랜잭션 하나",
                "<code>set(document) - set(SECTIONS)</code>가 비어야 한다. 그 다음 <code>Workspace.transaction</code>(#15, 0.7 ms — 스냅샷, 디스크는 아직) → "
                "<code>_require_declared_ids</code>(#25) → 섹션 순서대로: instruments(#43, 679 ms: <code>read_roster_table</code> #46이 instruments parquet을 읽는다) → "
                "datasets → components → runs. 문은 하나다 — <code>Transaction.register_*</code>.",
                fn="_apply() — 섹션 순서",
                code=at(
                    "src/vqapr/project/registration.py",
                    'for dataset_id, body in section("datasets")',
                    7,
                ),
                mem={"transaction.staged": "[instruments: stock 10]"},
            ),
            F(
                "01_register",
                133,
                "parquet을 실제로 연다 — 네 단계 검사. 이 트레이스에선 check_span 9.5 s",
                "<code>_dataset</code>(#87, 80 ms)이 <code>DatasetRegistration</code>과 <code>SourceSpec</code>을 만들고, <code>validate</code>(#133, <b>13,556 ms</b>)가 "
                "스키마 → key(유일성) → span(min/max 실측, <code>check_span</code> #210 <b>9,463 ms</b>) → 값(NaN·inf) 순으로 묻는다. 등록 15 s 중 13.6 s가 여기다 — "
                "이 머신의 첫 parquet 읽기. 집행표(sample-execution)는 두 번째 <code>validate</code>(#321)가 76 ms(check_span #384 12.6 ms)로 끝난다. "
                "통과하면 <code>Transaction.register_dataset</code>(#275, #431)로 스테이징.",
                fn="validate() — 4단계",
                code=at("src/vqapr/data/datasets.py", "def validate(", 12),
                disk={
                    "sample/observations.parquet": "읽음 (schema · key · span · values)",
                    "sample/execution.parquet": "읽음",
                },
                mem={
                    "transaction.staged": "[instruments, dataset:sample-prices, dataset:sample-execution]"
                },
            ),
            F(
                "01_register",
                443,
                "component: fingerprint + 저자 코드를 import해서 conformance",
                "<code>_component</code>(#440) → <code>prepare_component</code>(#443, 273 ms: 전략 · #589, 196 ms: exchange) → <code>fingerprint_component</code>(sha256(metadata ‖ bytes)) → "
                "<code>ComponentRef.of</code> → <code>conformance</code>(#524): <code>_LOADERS[kind]</code>가 <code>reversal_5d.py</code>·<code>exchange.py</code>를 <b>실제로 import하고 생성</b>한 뒤 "
                "<code>_check_methods</code>가 계약 메서드의 <b>arity</b>를 본다. 쓰는 것은 없다 — 거절할 수 있는 절반만.",
                fn="prepare_component() ×2 → conformance()",
                n=2,
                code=at(
                    "src/vqapr/extension/prepare.py", "fingerprint = fingerprint_component(", 17
                ),
                mem={
                    "transaction.staged": "[…, component:sample-reversal-5d, component:sample-exchange]"
                },
                tip="0.11.0에서 이 검사가 잡는 것이 하나 늘었다: <code>observe(self, call)</code>이 아닌 Compliance는 여기서 <code>component.signature_invalid</code>로 거절된다(장면 ⑩).",
            ),
            F(
                "04_register_short",
                483,
                "no-short: 배포된 Compliance도 같은 문으로",
                "두 번째 선언(short.yaml)은 <code>src/vqapr/compliance/builtin/no_short.py</code>의 <code>NoShort</code>를 component <code>no-short</code>로 등록한다. "
                "<code>prepare_component</code>(#483, kind=compliance, 18.6 ms) → <code>fingerprint_component</code>(#484, 13.5 ms) → <code>conformance</code>(#568) → "
                "<code>load_compliance</code>(#570) → <code>NoShort.__init__(compliance_id='no-short')</code>(#580) → <code>_check_methods</code>(#583, 0.28 ms) → "
                "<code>Transaction.register_component</code>(#589). run <code>sample-run-short</code>는 <code>register_run</code>(#656)에서 <code>_require_run_references</code>(#661)가 "
                "strategy_model · compliance · exchange 셋을 확인한 뒤 스테이징된다.",
                fn="prepare_component(kind=compliance) → conformance()",
                code=at(
                    "src/vqapr/compliance/builtin/no_short.py",
                    "def observe(self, call: ComplianceCall)",
                    12,
                    before=2,
                ),
                mem={"transaction.staged": "[component:no-short, run:sample-run-short]"},
            ),
            F(
                "01_register",
                794,
                "run은 저장된 철자로 한 번 더 읽힌다",
                "runs 섹션의 body는 <code>RunDefinition._from_the_stored_spelling</code>(#794, 24 ms)이 codec으로 받는다 — 선언에서 읽든 문서에서 읽든 run은 같은 길로 온다. "
                "<code>_refuse_a_run_fed_by_a_sibling</code>(#845) → <code>Transaction.register_run</code>(#849) → <code>RunDefinition.spoken</code>(#861)이 봉투의 두 문장을 낸다: "
                "\"fills against dataset 'sample-execution': the first execution instant after the decision, at 15:30:00 Asia/Seoul, at its 'close' price\", "
                '"the model is called every 1d at 08:00:00 Asia/Seoul, over the days its execution table has rows for".',
                fn="RunDefinition._from_the_stored_spelling() → register_run()",
                code=at(
                    "src/vqapr/project/registration.py", 'for run_id, body in section("runs")', 8
                ),
                mem={"transaction.staged": "[…, run:sample-run]"},
            ),
            F(
                "01_register",
                874,
                "commit: 락 · 읽기 · 재생 · 쓰기 각 1회",
                "<code>_exclusive</code>(#875 → <code>filelock.exclusive</code> #877) → <code>_read_or_empty</code>(#878) → 스테이징을 재생(<code>_merge_dataset</code> ×2 · <code>_merge_component</code> ×2 · <code>_merge_run</code> #889) → "
                "<code>_write</code>(#896, 88.6 ms → <code>write_workspace</code> #898 83 ms → <code>write_atomically</code> #932) → <code>_write_roster</code>(#935, instruments.json). "
                "commit 전엔 디스크에 아무것도 없었다. 봉투는 <code>success('workspace.register', registered=..., spoken=...)</code>(#939).",
                fn="Transaction.commit()",
                code=at("src/vqapr/project/store.py", "def commit", 12),
                disk={".vqapr/workspace.yaml": "쓰임 (atomic)", ".vqapr/instruments.json": "쓰임"},
                mem={
                    "transaction.staged": None,
                    "envelope": "ok · registered{datasets 2, components 2, instruments[stock 10], runs 1} · spoken 4",
                },
            ),
        ],
        "remember": [
            "등록은 트랜잭션 하나: 스테이징 → commit에서 락·읽기·재생·쓰기 각 1회. 문은 <code>Transaction.register_*</code> 하나다.",
            "dataset은 parquet을 실제로 열어 네 단계(schema · key · span · values)를 묻는다. 이 머신에선 첫 읽기가 9.5 s — 절대치가 아니라 '어디서'를 읽을 것.",
            "component는 import + 생성 + <code>_check_methods</code>(arity)까지 등록 시점에 실행된다. 배포된 <code>NoShort</code>도 저자 코드와 같은 문으로 들어온다.",
            "봉투가 시점 규칙을 말한다(spoken): dataset · run마다 한 문장. run은 '집행표에 행이 있는 날마다 08:00에 호출되고, 결정은 그 뒤 첫 집행 시각 15:30에 체결된다'.",
        ],
    },
    # ---------------------------------------------------------------- ② check
    {
        "id": "check",
        "key": "②",
        "title": "검사",
        "sub": "vqapr check sample-run-short · 11,789 ms · 8,137 호출 · passed [workspace, run, judgments, preflight] — 11.5 s가 집행표의 cold 스캔 둘",
        "frames": [
            F(
                "05_check_short",
                12,
                "네 phase: workspace → run → judgments → preflight",
                "<code>refuse_a_path</code>(#13) → phase 넷. 각 phase는 앞 phase의 결과에 <code>needs</code>로 의존하고, 거절되어도 멈추지 않고 할 수 있는 phase는 다 돌려 한 봉투에 "
                "passed / failures / blocked / skipped를 담는다. 답하지 못한 판정은 통과가 아니다(blocked). 이 run은 넷 다 passed.",
                fn="check() — 네 phase",
                code=at("src/vqapr/cli/check.py", "for phase in phases", 8),
                mem={"phases": "[workspace, run, judgments, preflight]"},
            ),
            F(
                "05_check_short",
                14,
                "workspace 열기 — 문서 하나를 읽고 codec으로 도메인화",
                "<code>Workspace.open</code>(#14, 43 ms) → <code>_read</code> → <code>read_workspace</code>(#19, 42.7 ms): source · dataset · component · run 문서를 <code>_decoded</code>로 풀고 "
                "<code>DatasetCodec.to_domain</code> 등으로 도메인 객체를 만든다. 이 하나의 스냅샷을 판정과 freeze가 같이 본다(이슈 070). <code>run_definition</code>(#598)이 대상 run을 꺼낸다.",
                fn="Workspace.open() → read_workspace()",
                code=at("src/vqapr/project/store.py", "def open(", 8),
                mem={
                    "workspace": "datasets 2 · components 3(전략 · exchange · no-short) · runs 1",
                    "definition": "sample-run-short (strategy, exchange sample-exchange, compliance [no-short])",
                },
            ),
            F(
                "05_check_short",
                600,
                "judgments: 판정 여섯을 모아서 묻는다",
                "<code>judgments</code>(#600, <b>11,470 ms</b>)는 거절을 raise하지 않고 <b>모은다</b>: <code>_judge_universe</code>(#613) · <code>_judge_roster</code>(#615) · <code>_judge_period</code>(#622) · "
                "<code>_judge_execution_ordering</code>(#624) · <code>_judge_member_datasets</code>(#4013, 7 ms) · <code>_judge_weights</code>(#4144) · <code>_judge_outputs</code>(#4146). "
                "agenda는 <code>_agenda_once</code>(#605)로 한 번만 파생되어 판정들이 나눠 쓴다.",
                fn="judgments() — 모아서",
                code=at("src/vqapr/flow/declaration/judgments.py", "def judgments(", 8),
                mem={"judged": "[]", "could_not_answer": "[]"},
            ),
            F(
                "05_check_short",
                624,
                "AC-C5: 모든 결정에 그 뒤 체결 시각이 있는가 — 시장 시계에게 묻는다",
                "<code>derived_agenda</code>(#626, <b>4,340 ms</b>: <code>Workspace.evaluation_times</code> #627 4,263 ms가 집행표의 distinct trade_at을 duckdb로 읽고, <code>OperationAgenda.expand</code> #2871 41 ms가 16 occurrence로 편다) → "
                "<code>bound_execution_table</code> → <code>ExecutionTable.build_horizon</code>(#3871, <b>7,114 ms</b> → <code>FillRule.build_horizon</code> → <code>candidate_instants</code> #3873: 집행표의 모든 시각) → "
                "occurrence마다 <code>select_target</code>이 None이면 late. 16개 모두 15:30에 체결 시각이 있다. 11.8 s 중 11.5 s가 이 두 cold 스캔이다.",
                fn="_judge_execution_ordering() → derived_agenda() · build_horizon()",
                code=at(
                    "src/vqapr/flow/declaration/judgments.py",
                    "occurrences = agenda().occurrences",
                    12,
                ),
                disk={
                    "sample/execution.parquet": "읽음 ×2 (distinct trade_at · candidate_instants)"
                },
                mem={
                    "agenda": "sample-run-short.agenda: 16 occurrences (08:00 Asia/Seoul)",
                    "horizon": "instants 16 (15:30 KST)",
                    "late": "[]",
                },
                caution="같은 두 스캔을 <code>run</code>이 다시 하면 642 ms(장면 ③ #601)다. check의 11.8 s는 구조가 아니라 디스크 캐시의 값이다 — 판끼리 절대치를 비교하지 말 것.",
            ),
            F(
                "05_check_short",
                4149,
                "preflight: run 층을 한 번 풀고 그 위에 전략을 얼린다",
                "<code>preflight_run</code>(preflight.py:735, #4149, 266 ms): <code>_require_execution_authority</code> → <code>derived_agenda</code>(#4153, 169 ms — 다시, 이번엔 캐시가 데워져서) → "
                "<code>_registered_exchange</code>(#7379) → <code>require_declared_roster</code>(#7383) → <code>load_exchange</code>(#7389, 5 ms: exchange.py import) → <code>bound_execution_table</code>(#7471) → "
                "<code>validate_execution_table</code>(#7490, 43.5 ms: schema · key · price) → <code>_validate_execution_requirements</code> · <code>_validate_instrument_universe</code> · <code>_validate_initial_account</code> → "
                "<code>_refuse_taken_output</code>(#7561: writes가 이미 등록된 dataset이면 거절).",
                fn="preflight_run() — run 층",
                code=at("src/vqapr/flow/declaration/preflight.py", "decide = derived_agenda", 14),
                mem={
                    "exchange": "sample-exchange (SampleExchange, listings 10)",
                    "execution_table": "sample-execution · fill at 15:30 close",
                },
            ),
            F(
                "05_check_short",
                7567,
                "전략 하나를 얼린다: 모델 로드 · 초기 상태 · agenda · 집행 타깃",
                "<code>_freeze_strategy</code>(#7567, 41.5 ms): <code>load_strategy_model</code>(#7572, 3 ms: reversal_5d.py import + <code>_validate_callback_signature(decide)</code>) → "
                "<code>_validate_initial_model_state</code>(#7617) → <code>Component.requirements</code>(#7672: 저자의 <code>inputs()</code> — sample-prices.close, RowsLookback 6) → "
                "<code>_freeze_agenda</code>(#7719, 6.4 ms) → <code>_validate_execution_targets</code>(#7855, 21.9 ms: 16 occurrence 각각의 타깃 시각). "
                "compliance [no-short]의 requirements(빈 dict)도 여기서 합쳐진다. 그 다음 <code>_freeze_sources</code>(#8080) → <code>FrozenRun.__post_init__</code>(#8103).",
                fn="_freeze_strategy() → FrozenRun",
                code=at("src/vqapr/flow/declaration/preflight.py", "def _freeze_strategy", 8),
                mem={
                    "frozen": "FrozenRun(sample-run-short: strategy sample-reversal-5d, compliance [no-short], instants 16, requirements 1, sources 2)"
                },
            ),
            F(
                "05_check_short",
                8131,
                "봉투: passed 넷, 거절 0",
                "<code>success('check')</code>(#8131). 봉투는 <code>ok:true · passed [workspace, run, judgments, preflight] · checked 같은 넷 · blocked [] · skipped []</code>. "
                "check는 디스크에 아무것도 쓰지 않는다 — 판정과 freeze는 메모리에서 끝난다.",
                fn="success('check')",
                code=at("src/vqapr/cli/envelope.py", "def success", 4),
                mem={"envelope": "ok · passed 4 · blocked 0 · skipped 0"},
                disk={".vqapr/": "변화 없음"},
            ),
        ],
        "remember": [
            "check는 phase 넷을 <b>모아서</b> 답한다. 거절되어도 할 수 있는 phase는 다 돌린다; 답하지 못한 판정은 blocked이지 통과가 아니다.",
            "AC-C5(결정마다 그 뒤 체결 시각)는 벽시계가 아니라 <b>집행표의 시각</b>에게 묻는다 — <code>build_horizon</code>이 시장 시계 전체를 읽는다.",
            "preflight는 run 층(venue · 집행표 · roster · 계좌)을 한 번 풀고 그 위에 전략 하나를 얼린다. compliance의 requirements가 전략의 것과 합쳐져 panel 집합이 된다.",
            "이 트레이스의 11.8 s는 두 cold duckdb 스캔의 값이다. 같은 판정을 run이 다시 하면 0.6 s.",
        ],
    },
    # ---------------------------------------------------------------- ③ run start
    {
        "id": "runstart",
        "key": "③",
        "title": "run 시작",
        "sub": "vqapr run sample-run-short · 5,005 ms · 45,436 호출 — preflight(907 ms) → run.json → _run_strategy → _run_member → StrategyEventLoop 조립 → EventLoop.run(2,240 ms)",
        "frames": [
            F(
                "06_run_short",
                12,
                "run도 같은 판정을 먼저 묻는다 — 이번엔 raise",
                "<code>refuse_a_path</code>(#13) → <code>Workspace.open</code>(#14, 43 ms) → <code>run_definition</code>(#598) → <code>preflight_run</code>(orchestration.py:86, #600, <b>907 ms</b>): "
                "<code>require_judged</code>(#601, 642 ms — check가 11.5 s 걸린 그 두 스캔, 캐시가 데워진 뒤) → <code>preflight_run</code>(preflight.py:735, #4149, 264 ms) → <code>FrozenRun</code>(#8103). "
                "TypeError/ValueError는 <code>VqaprError(stage=FREEZE)</code>로 감싸 같은 봉투로 나간다(이슈 076). 그 다음 <code>execute_run</code>.",
                fn="_run_one() → preflight_run()",
                code=at("src/vqapr/cli/run.py", "workspace = Workspace.open(project_root)", 9),
                mem={
                    "frozen": "FrozenRun(sample-run-short) — check와 같은 것",
                    "store_root": ".vqapr",
                },
            ),
            F(
                "06_run_short",
                8131,
                "run(): 집행표 검증 · roster 1회 읽기 · run.json 먼저",
                "<code>_own_output_or_refuse</code>(#8132) → <code>validate_execution_table</code>(#8138, 44 ms) → <code>registered_roster</code>(#8190, <b>556 ms</b>: <code>read_roster_table</code> #8196 — instruments parquet, run당 <b>한 번</b>; 기록과 봉투가 이 읽기에서 나온다, 이슈 070) → "
                "<code>_source_digests</code>(#8232: 소스 둘의 physical digest) → <code>freeze_run_record</code>(#8237, 7.6 ms → <code>write_run_record</code> #8248 → <code>write_atomically</code> #8314). "
                "<b>전략이 돌기 전에</b> run.json이 있다 — 도중에 죽어도 무엇을 시도했는지 남는다.",
                fn="orchestration.run()",
                code=at("src/vqapr/flow/orchestration.py", "roster = registered_roster(", 8),
                disk={
                    ".vqapr/runs/sample-run-short/run.json": "쓰임 (declared_digest ea6da225…, instruments 10, execution fill 15:30 close)"
                },
                mem={"roster": "stock 10 · digest 875b5fe1…"},
            ),
            F(
                "06_run_short",
                8316,
                "_run_strategy: 로드 셋과 drift 검사, 기록 디렉터리를 잡기 전에",
                "<code>load_strategy_model</code>(#8317, 2.7 ms) · <code>load_exchange</code>(#8362, 4.1 ms) · <code>load_compliance</code>(#8445, 1.2 ms) → "
                "<code>_as_loaded_fingerprints</code>(#8459: 셋의 <b>실제 로드된 바이트</b>의 fingerprint — 등록 후 편집됐다면 여기서 갈린다, 기록엔 둘 다 적힌다) → "
                "<code>Component.requirements</code>(#8489 → 저자의 <code>inputs()</code> #8490) vs <code>layer.requirements</code> drift 검사 → <code>compliance_requirements</code>(#8517). "
                "이 모든 것이 <code>_run_member</code> <b>앞</b>이다: drift한 component는 기록 디렉터리를 잡지 못한다(기록 228).",
                fn="_run_strategy() — 로드와 drift",
                code=at("src/vqapr/flow/orchestration.py", "strategy = load_strategy_model(", 12),
                mem={
                    "strategy": "SampleReversal5d (memory {}, payload b'')",
                    "exchange": "SampleExchange (Component: memory 있음)",
                    "rules": "(NoShort('no-short'),)",
                    "as_loaded": "{sample-reversal-5d, sample-exchange, no-short}: 등록과 같음",
                },
            ),
            F(
                "06_run_short",
                8529,
                "_run_member: 멤버 하나의 자원 — 세션 하나 · 스토어 하나 · writer 하나",
                "기록 228이 전략과 datamodel에서 같은 것을 뽑아낸 자리. <code>_FrozenCatalog</code>(#8530) · <code>ScanSession</code>(#8531: duckdb 연결 하나, 멤버 전체가 쓴다 — parquet 메타데이터 캐시가 연결별이라) · "
                "<code>DuckDbObservationStore</code>(#8532) · <code>RunRecordWriter.open</code>(#8536, 1.75 ms: 디렉터리 + lock 파일, <code>O_EXCL</code>) → <code>body(observation_store, session, writer)</code>(#8543, 3,407 ms) → "
                "끝나면 <code>session.close</code>(#45277) → <code>read_record</code>(#45281: 기록을 디스크에서 다시 읽어 돌려준다). body가 죽으면 <code>writer.release()</code>가 lock을 푼다.",
                fn="_run_member(member_kind='strategy')",
                code=at("src/vqapr/flow/orchestration.py", "catalog = _FrozenCatalog(frozen)", 16),
                disk={
                    ".vqapr/runs/sample-run-short/strategies/sample-reversal-5d@fb2406b9/": "디렉터리 + lock"
                },
                mem={
                    "session": "ScanSession (연결 1)",
                    "writer": "RunRecordWriter (buffer 비어 있음, sink 역할)",
                },
            ),
            F(
                "06_run_short",
                8920,
                "StrategyEventLoop.__init__: 권한 대조, 핸들러 다섯, 그리고 RunLoop 하나",
                "body 안(#8543)에서 <code>RunStateRepository</code>(초기 account root · 모델 메모리 · 규칙과 venue의 초기 메모리 · <b>sink=writer.append_chunk</b>)를 만들고 <code>_window_factory</code> 둘(#8915 전략 창 · #8916 규칙 창)을 만든 뒤 여기로. "
                "생성자는 대조만 한다: layer가 run의 전략인가, exchange에 execute가 있나, 초기 스냅샷·모드가 frozen과 같나, 상태가 든 component의 메모리가 정확히 실렸나. 그 다음 <code>FlowContext</code> 하나, "
                "<code>CallbackHandler</code>(#8933) · <code>StrategyPart</code>(#9033) · <code>Accrual · Execution · Valuation · ComplianceHandler</code>(#9034–#9037) · <code>MarketClock</code>(#9038) → "
                "<code>RunLoop.__init__</code>(#9039 → <code>EventLoop.__init__</code> #9040: schedule은 <code>dispatch_order</code> #8934의 16 occurrence) → <code>Account.bind</code>(#9042).",
                fn="StrategyEventLoop.__init__() → RunLoop(part, market)",
                code=at(
                    "src/vqapr/flow/run/loop.py",
                    "part=StrategyPart(self._context, callback),",
                    16,
                    before=3,
                ),
                mem={
                    "loop": "RunLoop(schedule 16, part=StrategyPart, market=MarketClock)",
                    "state": "RunStateRepository v0 · sink=writer.append_chunk · pending None",
                },
                tip="전략 run과 datamodel run의 차이는 <b>여기서 무엇을 조립했는가</b>뿐이다(기록 227). 장면 ⑨의 <code>DataModelEventLoop</code>는 market 없이 같은 <code>RunLoop</code>를 만든다.",
            ),
            F(
                "06_run_short",
                9043,
                "EventLoop.run: 걷기는 여기 한 번 쓰여 있고 override할 수 없다",
                "<code>start(cutoff)</code> → <code>events()</code>를 <code>sort_key</code>로 정렬 → 이벤트마다 <code>on_progress</code>(writer.heartbeat) + <code>handle</code> → <code>finish(traces)</code>. "
                "2,240 ms 중 <code>RunLoop.handle</code> 32회가 2,192 ms. 정렬 키는 UTC 시각과 우선순위: <code>MarketEvent</code>는 <code>-1</code>이라 같은 시각의 결정보다 앞선다(§3.1) — 이 run에선 결정 08:00 KST, 시장 15:30 KST라 겹치지 않는다.",
                fn="EventLoop.run() — 정렬된 걷기",
                code=at("src/vqapr/flow/engine/loop.py", "def run(self) -> ResultT:", 11),
                clock={"start_cutoff": "2022-01-04 00:00 +09:00"},
            ),
            F(
                "06_run_short",
                9044,
                "start: 전략의 보이는 상태를 싣는다",
                "<code>RunLoop.start</code>(#9044) → <code>StrategyPart.start</code>(#9045) → <code>guard(SimulationStage.START)</code> 안에서 <code>CallbackHandler.load_visible_state</code>(#9047, 0.96 ms): "
                "root의 <code>current_model_state_ref</code>로 memory와 payload를 싣고, <code>restore_component_memory</code>(#9064)로 규칙·venue의 메모리도 root에서 복원한다(기록 181). "
                "루프는 account · venue · warehouse · record 중 아무것도 모른다 — Part가 열고 닫는다.",
                fn="RunLoop.start() → StrategyPart.start()",
                code=at(
                    "src/vqapr/flow/run/loop.py", "self._callback.load_visible_state()", 8, before=6
                ),
                mem={
                    "strategy.memory": "{} (root v0에서)",
                    "component memory": "{no-short: {}, sample: {…}} 복원",
                },
            ),
            F(
                "06_run_short",
                9068,
                "events: 전략 시계 16 + 시장 시계 16 = 32",
                "<code>RunLoop.events</code>(#9068, 17 ms): <code>schedule</code>(#9069)의 16 occurrence를 <code>OccurrenceEvent</code>로, 그리고 <code>MarketClock.instants</code>(#9087, 14 ms) → "
                "<code>CallbackHandler.execution_horizon</code>(#9088: <code>build_horizon</code>을 run당 <b>한 번</b>, run의 ScanSession으로 — check에서 7.1 s였던 그 질문이 여기선 14 ms)의 16 시각을 <code>MarketEvent</code>로. "
                "이 horizon이 체결 타깃 선택(<code>select_target</code>)과 평가 시각의 <b>한 집합</b>이다: 결정이 체결될 수 있는 시각과 장부가 평가되는 시각은 같은 시계다.",
                fn="RunLoop.events() → MarketClock.instants() → execution_horizon()",
                code=at("src/vqapr/flow/run/loop.py", "def events(self)", 9),
                clock={
                    "events": "32 = occurrence 16 (08:00 KST) + market 16 (15:30 KST)",
                    "horizon": "2022-01-04 15:30 … 2022-01-25 15:30",
                },
                disk={"sample/execution.parquet": "읽음 (candidate_instants, 1회)"},
            ),
        ],
        "remember": [
            "run은 check와 같은 판정을 raise 모드로 먼저 묻고(<code>require_judged</code>), run.json을 <b>전략이 돌기 전에</b> 쓴다.",
            "로드 셋과 drift 검사는 <code>_run_member</code> 앞이다: drift한 component는 기록 디렉터리를 잡지 못한다. <code>_run_member</code>는 세션 하나·스토어 하나·writer 하나를 멤버에게 준다(기록 228).",
            "<code>StrategyEventLoop</code>는 <b>조립</b>이다: 권한 대조 → 핸들러 다섯 → <code>RunLoop(part=StrategyPart, market=MarketClock)</code>. 걷기는 <code>EventLoop.run</code>에 한 번 쓰여 있다.",
            "events는 전략 시계와 시장 시계의 합집합이고, 시장 시계는 집행표를 run당 한 번 읽은 horizon이다. 같은 시각이면 시장(-1)이 먼저.",
        ],
    },
    # ---------------------------------------------------------------- ④ strategy clock
    {
        "id": "decide",
        "key": "④",
        "title": "전략 시계 한 점",
        "sub": "occurrence 2022-01-11 08:00 (#21602, 36.5 ms) — RunLoop.handle → StrategyPart.dispatch → CallbackHandler.dispatch → decide(저자, 5.9 ms) → Rebalance → intent 도장 → accept → publish. 16점 중 Hold 5 · Rebalance 11",
        "frames": [
            F(
                "06_run_short",
                21602,
                "handle: OccurrenceEvent는 Part의 것, MarketEvent는 시장 시계의 것",
                "<code>RunLoop.handle</code>은 둘로만 나눈다: <code>MarketEvent</code>면 <code>self._market.at(event)</code>, 아니면 <code>self._part.dispatch(event.occurrence)</code>. occurrence는 역할을 실어 나르지 않는다(기록 182) — "
                "어느 Part인지는 조립에서 정해졌다. 이 점은 <code>OccurrenceEvent(sample-run-short.agenda-2022-01-11T0800)</code>.",
                fn="RunLoop.handle(OccurrenceEvent)",
                code=at("src/vqapr/flow/run/loop.py", "def handle(self, event", 9),
                clock={"event": "2022-01-11 08:00 +09:00 (occurrence 6/16)"},
            ),
            F(
                "06_run_short",
                21603,
                "StrategyPart.dispatch: 'callback' 시간에 넣고 핸들러로",
                "<code>timed('callback')</code>이 감싼다 — 기록의 <code>timing.callback</code>(이 run 0.982 s)은 창 만들기와 저자의 <code>decide</code>를 합친 값이다(이슈 068). "
                "Part는 자기 receiver(RunStateRepository)를 알고 루프는 모른다.",
                fn="StrategyPart.dispatch()",
                code=at(
                    "src/vqapr/flow/run/loop.py",
                    "def dispatch(self, occurrence: OperationOccurrence) -> OccurrenceTrace:",
                    7,
                ),
            ),
            F(
                "06_run_short",
                21605,
                "CallbackHandler.dispatch: 보이는 상태 복원 → 창 → recorder → decide",
                "<code>_visible_callback_state</code>(#21610: current ref · memory · payload) → <code>visible_component_memory</code> → <code>_restore_callback_state</code>(#21631) → <code>_strategy_window</code>(#21638, 1.8 ms: <code>_window_factory.at(08:00)</code> → <code>ModelWindow</code>) → "
                "<code>_callback_recorder</code>(#21682: <code>InvocationRecorder</code>, stage STRATEGY_CALLBACK, sequencer=<code>next_sequence</code>) → <code>_callback_account_view</code>(#21705) · <code>_account_history</code>(#21723) → "
                "<code>strategy.decide(StrategyModelContext(occurrence, window, account, reads, account_history))</code>(#21726). 실패하면 except에서 상태를 되돌린다.",
                fn="CallbackHandler.dispatch()",
                code=at(
                    "src/vqapr/flow/run/callback.py",
                    "result = self._context.strategy.decide(",
                    13,
                    before=4,
                ),
                mem={
                    "window": "ModelWindow(08:00, instruments 10, allowed [sample-prices.close ×6])",
                    "recorder": "InvocationRecorder(STRATEGY_CALLBACK, tables vqapr.* 4)",
                    "account": "v0 (cash 100,000,000 · 보유 없음 — 앞의 5점은 Hold였다)",
                },
            ),
            F(
                "06_run_short",
                21726,
                "저자의 decide: 창을 읽고 Rebalance 하나를 돌려준다",
                "<code>call.read('prices', 'close')</code> → 종목별 6개 종가 → lookback이 다 찬 이름만 → 5일 수익률 최하위 3 → <code>Rebalance(target_weights={K000004, K000005, K000006: 0.3}, cash_weight 0.1, budget)</code>. "
                "경제만 말한다 — intent id · strategy id · 본 account version · source ref는 프레임워크가 찍는다. 앞의 5점(01-04 ~ 01-10)은 lookback 6이 안 차서 <code>Hold('incomplete-lookback')</code>였다.",
                fn="SampleReversal5d.decide(call)",
                author=True,
                code=("def", 14),
                mem={"result": "Rebalance(K000004 0.3 · K000005 0.3 · K000006 0.3, cash 0.1)"},
            ),
            F(
                "06_run_short",
                21866,
                "도장: Rebalance → EconomicPortfolioIntent",
                "<code>_stamp_intent</code>(#21866, 4.6 ms): id는 <code>uuid5(strategy_id/occurrence_id)</code>라 같은 run의 같은 결정은 같은 id(재생이 바이트 단위로 같다), strategy_id · 정렬된 targets · cash · budget · "
                "<code>_actual_source_refs(window)</code>(실제 읽은 것) · <code>account.version</code>(본 것) · 모델 상태 ref. 그 다음 <code>validate_economic_intent</code>(#21973, 1.3 ms: budget 범위) → <code>_validate_intent_authority</code>(#22007: 이 run이 거래하는 instrument인가).",
                fn="_stamp_intent() → validate_economic_intent()",
                code=at("src/vqapr/flow/run/callback.py", "return EconomicPortfolioIntent(", 10),
                mem={
                    "intent": "EconomicPortfolioIntent(951921ba…, targets 3, account_version_seen 0)"
                },
            ),
            F(
                "06_run_short",
                22011,
                "accept: 집행 타깃을 시장 시계에서 고른다",
                "<code>_accept_intent</code>(#22011): <code>execution_table.select_target(decision_time=08:00, end, horizon)</code>(#22016 → <code>FillRule.select_target</code> #22017) — 결정 뒤 첫 15:30. "
                "<code>AcceptedIntent(intent, occurrence, decision_time, target)</code>(#22023). horizon은 장면 ③에서 읽은 그 집합이라, 이 타깃은 반드시 걸어갈 시장 시각이다.",
                fn="_accept_intent() → select_target()",
                code=at(
                    "src/vqapr/flow/run/callback.py",
                    "target = execution_table.select_target(",
                    12,
                    before=4,
                ),
                mem={
                    "accepted": "AcceptedIntent(target 2022-01-11 15:30 KST = 06:30 UTC, dataset sample-execution)"
                },
            ),
            F(
                "06_run_short",
                22028,
                "패키지가 스스로 적는 것: weight 3행",
                "<code>_record_defaults</code>(#22028, 1.2 ms): 타깃마다 <code>vqapr.weight</code> 한 행(#22029 K000004 0.3 · #22037 K000005 · #22045 K000006 — 문자열 그대로). account 행은 평가가 이미 적었으면 쓰지 않는다(이슈 010). "
                "그 다음 <code>_candidate_callback_state</code>(#22059: 저자가 남긴 memory/payload → <code>prepare_model_state</code>) → <code>_callback_evidence</code>(#22145).",
                fn="_record_defaults() → InvocationRecorder.append(vqapr.weight) ×3",
                code=at(
                    "src/vqapr/flow/run/callback.py",
                    'for target in getattr(intent, "targets", ()):',
                    8,
                    before=1,
                ),
                mem={"recorder.staged": "vqapr.weight 3행 (sequence 3개, run 전체 카운터)"},
            ),
            F(
                "06_run_short",
                22347,
                "publish: 유일한 가변 동작 — chunk를 sink로, root를 바꾼다",
                "<code>_prepare_callback_publication</code>(#22256 → <code>prepare_callback</code> #22257: 다음 root 후보 + <code>_staged</code>가 recorder의 <code>staged_chunks</code>를 뗀다) → <code>publish</code>(#22347, 2.9 ms): "
                "<code>expected_version</code> 대조 → <code>_deliver</code>(#22348 → <code>append_chunk</code> #22349 weight 3행 · #22366 account · #22371 monitoring · #22376 fill — 뒤 셋은 빈 chunk) → <code>self._root = prepared.root</code>. "
                "pending에 AcceptedIntent가 실린다. 반환은 <code>OccurrenceTrace(occurrence, result, root.version)</code> — root 자체는 들고 있지 않다(기록 224).",
                fn="RunStateRepository.publish()",
                code=at("src/vqapr/flow/engine/run_state.py", "def publish(", 9),
                mem={
                    "state": "root 교체 · pending=AcceptedIntent(target 01-11 15:30)",
                    "recorder.staged": None,
                    "trace": "OccurrenceTrace(occurrence, intent, root_version)",
                },
                disk={"writer.buffer": "vqapr.weight +3행 (Arrow, 메모리)"},
            ),
        ],
        "remember": [
            "<code>RunLoop.handle</code>은 둘로만 나눈다: 시장 이벤트면 <code>MarketClock.at</code>, 아니면 <code>Part.dispatch</code>. occurrence는 역할을 싣지 않는다.",
            "콜백은 복원 → 창 → recorder → <code>decide</code> → 도장 → accept → 패키지 행 → 후보 → publish 순이다. 저자는 <b>경제만</b> 말하고 나머지 다섯 필드는 프레임워크가 찍는다.",
            "집행 타깃은 시장 시계(horizon)에서 고르므로 반드시 걸어갈 시각이다. pending은 하나뿐이고 그 타깃이 지나갔다면 invariant 위반이다.",
            "publish는 유일한 가변 동작: <code>expected_version</code> 대조 → chunk를 sink로 → root 교체. 트레이스는 root가 아니라 root_version만 든다(기록 224).",
        ],
    },
    # ---------------------------------------------------------------- ⑤ read
    {
        "id": "read",
        "key": "⑤",
        "title": "읽기",
        "sub": "call.read('prices', 'close') — 첫 콜백(01-04, #9442 decide 457 ms: observation_rows 425 ms, 물리 읽기 1회) 그리고 그 뒤(01-05, #17482 decide 4.5 ms: panel 1.3 ms, 슬라이스)",
        "frames": [
            F(
                "06_run_short",
                9442,
                "첫 decide는 457 ms — 거의 전부가 첫 읽기",
                "첫 occurrence(01-04 08:00)의 <code>decide</code>(#9442, 457 ms) → <code>_DeclaredReads.read</code>(#9443, 455 ms): alias 'prices'의 requirement(<code>requirements_for</code> #9445: sample-prices.close, RowsLookback 6) → "
                "<code>ModelWindow.grain</code>(#9458: instrument_instant) → <code>ModelWindow.panel</code>(#9462, 454 ms). 그 안이 이 run의 <b>유일한</b> 관측 parquet 읽기다.",
                fn="SampleReversal5d.decide() → _DeclaredReads.read()",
                author=True,
                code=at("src/vqapr/authoring/context.py", "def read(", 10),
            ),
            F(
                "06_run_short",
                9463,
                "panel_window: 등록된 span 전체를 한 번 스캔해서 panel을 만든다",
                "<code>DuckDbObservationStore.panel_window</code>(#9463): alias의 requirement들은 한 dataset · 한 lookback이어야 한다 → <code>panel_identity</code>(#9478: source digest · dataset · fields · instruments · span) → 캐시 miss → "
                "<code>scan.observation_rows</code>(#9480, <b>425 ms</b>: <code>available_at &lt;= span[1]</code>, <code>lower_bound=span[0]</code> — 등록된 span 전체, run의 ScanSession으로) → <code>Panel.from_rows</code>(#16422, 13.7 ms: (available_at × instrument) 피벗, 없는 칸은 null). "
                "PIT 술어는 <code>observation_rows</code> 한 곳에만 쓰여 있다(이슈 049).",
                fn="DuckDbObservationStore.panel_window() → observation_rows() → Panel.from_rows()",
                code=at("src/vqapr/data/store.py", "panel = self.__panels.get(identity)", 10),
                disk={"sample/observations.parquet": "읽음 (1회, span 전체)"},
                mem={
                    "panels[identity]": "Panel(sample-prices, fields [close], instruments 10, instants 735)"
                },
            ),
            F(
                "06_run_short",
                16423,
                "window: 그 다음은 산술 — 시각 축의 인덱스 둘",
                "<code>Panel.window(field, evaluation_time=08:00, lookback=RowsLookback(6))</code>(#16423): cutoff 이하의 마지막 6 instant — 모든 이름에 같은 6개. <code>PanelWindow.counts</code>(#16425)가 이름별 실제 값 개수를 세어 access 기록에 남긴다. "
                "01-04 08:00 시점엔 01-03 15:30 하나뿐이라 값 1개 — 저자의 guard가 <code>Hold('incomplete-lookback')</code>를 돌려준다.",
                fn="Panel.window() → PanelWindow",
                code=at("src/vqapr/data/panel.py", "def window(", 12),
                mem={"window": "PanelWindow(instants 1, instruments 10) → 01-04: Hold"},
            ),
            F(
                "06_run_short",
                17482,
                "두 번째 콜백부터: decide 4.5 ms, panel 1.3 ms",
                "01-05의 <code>decide</code>(#17482, 4.5 ms) → <code>read</code>(#17483, 2.1 ms) → <code>panel</code>(#17502, 1.3 ms) → <code>panel_window</code>(#17503: <code>panel_identity</code> #17516 같음 → 캐시 hit → <code>Panel.window</code> #17517 0.03 ms). "
                "그 뒤 <code>window.values[name]</code>(#17532 <code>PanelWindow.values</code> → <code>_LazyColumns.__getitem__</code> → <code>_cells</code>: 열 하나를 pyarrow slice로) ×10. "
                "<code>observation_rows</code>는 이 run에서 <b>1회</b>다; 16 콜백이 같은 Panel을 슬라이스한다.",
                fn="decide() → read() → panel (cache hit)",
                author=True,
                code=at("src/vqapr/data/panel.py", "def values", 8, before=1),
                mem={"window": "PanelWindow(instants 2 → … → 6)"},
            ),
            F(
                "06_run_short",
                21638,
                "규칙의 창은 다른 공장에서 나온다 — 같은 스토어, 다른 허용 목록",
                "<code>_strategy_window</code>(#21638) → <code>_window_factory.at</code>(orchestration.py:438): <code>ModelWindow(evaluation_time, frozen.instruments, store, allowed_requirements=layer.requirements, consumer_id='sample-reversal-5d')</code>. "
                "규칙 쪽 공장(#8916)은 <code>allowed_requirements=layer.compliance_requirements</code>, <code>consumer_id=None</code> — 시장 시각에 <code>compliance_window_at(instant)</code>로 불린다(장면 ⑥). 창은 선언하지 않은 것을 읽지 못한다.",
                fn="_strategy_window() → _window_factory.at()",
                code=at(
                    "src/vqapr/flow/orchestration.py",
                    "def at(instant: datetime) -> ModelWindow:",
                    9,
                ),
                mem={
                    "window(strategy)": "allowed [sample-prices.close×6], consumer sample-reversal-5d",
                    "window(compliance)": "allowed [], consumer None",
                },
            ),
        ],
        "remember": [
            "관측 parquet은 run당 <b>한 번</b> 읽힌다(<code>observation_rows</code> 1회): 등록된 span 전체를 스캔해 Panel로 피벗하고, 모든 콜백은 시각 축 인덱스 둘로 슬라이스한다.",
            "PIT 술어(<code>available_at &lt;= t</code> · lookback · instruments)는 <code>observation_rows</code> 한 곳에만 쓰여 있다. 필드는 그 창 안에서 평가되는 식이지 창을 다시 그리는 문장이 아니다.",
            "<code>RowsLookback(n)</code>은 표의 마지막 n instant — 모든 이름에 같은 n. 값이 모자란 이름은 그냥 값이 적다(null), 저자의 guard가 그것을 읽는다.",
            "창은 공장(<code>_window_factory</code>) 둘에서 나온다: 전략 것과 규칙 것. 허용 목록과 consumer만 다르고 스토어는 같다.",
        ],
    },
    # ---------------------------------------------------------------- ⑥ market clock
    {
        "id": "market",
        "key": "⑥",
        "title": "시장 시계 한 점",
        "sub": "MarketEvent 2022-01-11 15:30 (#22386, 73.5 ms) — accrue → fill(33.5) → mark(13.2) → observe(18.9) → close(1.2). 보유만인 점(01-04 #16812, 46 ms): fill 0.003 ms · mark_held · observe · close",
        "frames": [
            F(
                "06_run_short",
                22387,
                "MarketClock.at: 다섯 줄의 fold",
                "<code>timed('due')</code> + <code>guard(DUE_SNAPSHOT)</code> 안에서: pending이 있고 그 타깃이 이 시각이면 <code>due</code>, 타깃이 이미 지났으면 invariant 위반(RuntimeError). 그 다음 <code>MarketInstant(at, due)</code>를 다섯 단계가 차례로 받아 자기 필드를 채워 돌려준다: "
                "<code>accrue → fill → mark → observe → close</code>. 순서는 <code>domain.wiring.MARKET_CLOCK_ORDER</code>가 말하고 wiring 테스트가 붙든다. 반환은 <code>DueExecutionTrace(event, at.result, root.version)</code>.",
                fn="MarketClock.at(event)",
                code=at(
                    "src/vqapr/flow/run/loop.py",
                    "at = MarketInstant(at=instant, due=due)",
                    10,
                    before=2,
                ),
                clock={
                    "event": "2022-01-11 15:30 +09:00 (06:30 UTC) · due=AcceptedIntent(01-11 08:00)"
                },
                mem={
                    "at": "MarketInstant(at, due, filled None, marked None, monitoring None, result None)"
                },
            ),
            F(
                "06_run_short",
                22391,
                "ACCRUE: 자리만 있다",
                "<code>AccrualHandler.accrue</code>(#22391, 0.12 ms): <code>guard(MARKET_ACCRUE)</code> 안에서 instant를 그대로 돌려준다 — 오너 결정으로 비어 있는 자리(§7.3). wiring 테이블의 다섯 행 중 하나이고 시계는 시장.",
                fn="AccrualHandler.accrue()",
                code=at("src/vqapr/flow/run/accrual.py", "def accrue", 6),
            ),
            F(
                "06_run_short",
                22394,
                "EXECUTE: 스냅샷(미리 읽어 둔 창에서) → 주문 계획 → venue → 장부 append → commit",
                "<code>fill</code>(#22394, 33.5 ms): <code>select_snapshot</code>(#22402 → <code>execution_snapshot</code> → <code>ExecutionSnapshots.at</code> #22404 <b>0.56 ms</b>: 기록 222의 read-ahead 창을 slice, 열 단위) → NAV = cash + Σ 보유×가격 → "
                "<code>require_declared</code> → <code>plan_orders</code>(#22439, 9.2 ms: <code>_apply_venue_rules</code> #22469 → 매수 3, <code>_settle_payable</code>) → <code>restore_component_memory</code> → "
                "<code>exchange.execute(ExecutionCall(at, orders, account, snapshot, instruments, rules))</code>(#22660 <code>AcademicExchange.execute</code> 4.2 ms: <code>validate_requests</code> → Fill ×3 → <code>FillBatch</code>) → "
                "<code>fill_entries</code>(#22768) → <code>Account.append</code>(#22794, 1.3 ms: 장부의 허락) → <code>prepare_account</code>(#22835, 9.1 ms: <code>_fill_rows</code> #22977, sequence는 run 카운터) → <code>commit_append</code>(#23050) → <code>_publish_account_commit</code>(#23056 → <code>publish_infallible</code> #23057).",
                fn="ExecutionHandler.fill()",
                code=at(
                    "src/vqapr/flow/run/execution.py", "fills = self._context.exchange.execute(", 10
                ),
                mem={
                    "at.filled": "Filled(fills 3, committed_root, snapshot)",
                    "account": "v0 → v1 (첫 체결: 매수 K000004 · K000005 · K000006, cash_delta −29,791,121.70)",
                    "state.pending": "소비됨",
                },
                disk={"writer.buffer": "vqapr.fill +3행"},
            ),
            F(
                "06_run_short",
                23089,
                "VALUATION: 체결에 쓴 그 스냅샷으로 방금 commit된 장부를 평가한다",
                "<code>mark</code>(#23089) → <code>filled</code>가 있으니 <code>mark_fill</code>(#23090, 13.1 ms): <code>_marks_from_execution_snapshot</code>(#23094: 체결 스냅샷의 가격, 이전 mark로 채움) → <code>ValuationService.mark</code>(#23110, 1.7 ms) → <code>Account.mark</code>(#23160) → "
                "<code>measurement_recorder</code>가 <code>append_columns(vqapr.account)</code>(#23215, 1.8 ms: <code>_ACCOUNT</code> 행 + 보유 이름당 한 행, <b>열로</b>) → <code>prepare_account</code>(#23254) → <code>commit_mark</code>(#23273) → <code>publish_marked</code>(#23279, 3.7 ms). "
                "보유만인 점(#16821)은 <code>mark_held</code>: 같은 시계, 같은 스냅샷, 주문만 없다 — account version은 소비하지 않는다.",
                fn="ValuationHandler.mark() → mark_fill()",
                code=at(
                    "src/vqapr/flow/run/valuation.py", "def mark(self, instant: MarketInstant)", 8
                ),
                mem={"at.marked": "Marked(root, mark NAV, evidence, selected 3)"},
                disk={"writer.buffer": "vqapr.account +4행 (_ACCOUNT + 3)"},
            ),
            F(
                "06_run_short",
                23325,
                "COMPLIANCE: 규칙이 Call 하나를 받는다 — call.account는 방금 mark된 장부",
                "<code>observe</code>(#23325, 18.9 ms) → 규칙이 없으면 <code>monitoring None</code>(빈 보고가 아니라 '판정할 것 없음') → <code>_observe</code>(#23328): <code>require_marked</code>(#23329 — VALUATION 뒤에만 올 수 있다) → 규칙 창 <code>compliance_window_at(15:30)</code> → "
                "<code>restore_component_memory</code> → <code>evaluate_compliance</code>(#23379, 2.1 ms: <code>build_account_view</code> #23387 → <code>NoShort.observe(ComplianceContext(window, account, instruments, reads))</code> #23397 0.74 ms — <b>인자 하나</b>, 기록 229) → "
                "<code>_record_findings</code>(#23432, 11.5 ms: <code>vqapr.monitoring</code> 한 행 #23448 → <code>prepare_monitoring</code> #23463 → <code>publish_infallible</code> #23616). 결과 held.",
                fn="ComplianceHandler.observe() → evaluate_compliance() → NoShort.observe(call)",
                code=at("src/vqapr/compliance/evaluation.py", "rule.observe(", 10, before=3),
                mem={
                    "at.monitoring": "MonitoringResult(no-short: passed, measured 0, verdict held)"
                },
                disk={"writer.buffer": "vqapr.monitoring +1행"},
            ),
            F(
                "06_run_short",
                23660,
                "close: 체결이면 feedback 발행, 보유만이면 HeldResult",
                "<code>close</code>(#23660, 1.2 ms): <code>filled</code>가 있으니 <code>FeedbackEvidence</code>(fills · mark summary · root_version) → <code>DueExecutionEvidence(commit, mark, feedback)</code> → <code>prepare_feedback</code>(#23672) → <code>publish_infallible</code>(#23675) → "
                "<code>result = DueExecutionResult(pending_id, account.version, evidence, monitoring)</code>. 보유만인 점(#17350, 0.07 ms)은 <code>HeldResult(mark evidence, monitoring)</code>. result가 없으면 RuntimeError — 한 점은 반드시 결과를 남긴다.",
                fn="ExecutionHandler.close()",
                code=at(
                    "src/vqapr/flow/run/execution.py", "def close(self, instant: MarketInstant)", 10
                ),
                mem={
                    "at.result": "DueExecutionResult(account v1, monitoring)",
                    "trace": "DueExecutionTrace(event, result, root_version)",
                },
            ),
            F(
                "06_run_short",
                16831,
                "첫 시장 시각에 집행표를 창으로 미리 읽는다 (기록 222)",
                "첫 점(01-04)의 <code>mark_held</code>(#16822, 28 ms) 안에서 <code>FlowContext.execution_snapshot</code>(#16826)이 <code>ExecutionSnapshots</code>(#16829)를 만들고 <code>at</code>(#16830, 18.4 ms) → <code>_ensure</code>(#16831, 18.1 ms → <code>execution_window_table</code>: "
                "horizon의 시각 중 <code>_WINDOW_ROWS // len(instruments)</code>개를 한 쿼리로) — 이 run에선 <b>1회</b>. 그 뒤 <code>ExecutionSnapshots.at</code>는 <code>_offsets</code>로 slice만 한다(#22404, 0.56 ms). "
                "<code>exact_execution_snapshot</code>(시각당 쿼리)은 0회. 체결과 평가는 같은 read에서 같은 행을 본다.",
                fn="ExecutionSnapshots.at() → _ensure() (read-ahead)",
                code=at(
                    "src/vqapr/exchange/execution_table.py",
                    "window = self._table.slice(start, stop - start)",
                    8,
                    before=4,
                ),
                disk={"sample/execution.parquet": "읽음 (창 1회; 이후 slice)"},
            ),
        ],
        "remember": [
            "시장 시계 한 점은 <code>MarketInstant</code>를 다섯 단계가 차례로 받아 자기 필드를 채우는 <b>fold</b>다: accrue → fill → mark → observe → close. 순서는 wiring 테이블이 말하고 테스트가 붙든다(기록 226).",
            "EXECUTE는 스냅샷 → 계획 → venue → 장부 append → commit. VALUATION은 <b>그 스냅샷</b>으로 방금 commit된 장부를 평가하고, 보유만인 점도 같은 시계·같은 가격으로 평가한다.",
            "COMPLIANCE는 VALUATION이 남긴 mark를 판정한다 — 두 번째 평가도, root 재읽기도 아니다. 규칙은 <code>observe(call)</code> 하나를 받고 <code>call.account</code>가 장부다(기록 229).",
            "집행표는 첫 시장 시각에 창으로 미리 읽히고(1회) 이후는 slice다(기록 222). 시각당 쿼리(<code>exact_execution_snapshot</code>)는 0회.",
        ],
    },
    # ---------------------------------------------------------------- ⑦ rows
    {
        "id": "rows",
        "key": "⑦",
        "title": "행의 길",
        "sub": "recorder(열) → staged_chunks → RecordChunk → publish → _deliver → writer.append_chunk(Arrow, 메모리) ×203 → 끝에 finish → _seal → _write_parquet ×4 → strategy.json → 배분을 warehouse에. _spill 0 · heartbeat 235 · checkpoint 1",
        "frames": [
            F(
                "06_run_short",
                16933,
                "행은 열로 적힌다 (기록 221)",
                "평가의 recorder(#16923, stage VALUATION)에 <code>append_columns(vqapr.account, {instrument: [_ACCOUNT, …held], cash, nav, quantity, price, observed_at, account_version})</code>(#16933, 0.86 ms): 3,000 이름의 장부가 3,000 dict가 아니라 <b>튜플 일곱</b>이고 "
                "열 단위로 타입 검사한다(<code>normalize_column</code>). sequence는 <code>next_sequence</code>(#16949 → <code>RunStateRepository.next_sequence</code> #16950: run 전체의 한 카운터, 기록 225) — 콜백·평가·체결 행이 한 순서에 선다. "
                "저자의 <code>append</code>(행 하나)도 같은 recorder로 들어와 열에 쌓인다(#22029 weight).",
                fn="InvocationRecorder.append_columns()",
                code=at("src/vqapr/authoring/records.py", "def append_columns", 16),
                mem={
                    "recorder._columns[vqapr.account]": "열 7 × 1행 (01-04: 보유 0)",
                    "sequence": "run 카운터",
                },
            ),
            F(
                "06_run_short",
                16955,
                "staged_chunks: 표마다 RecordChunk 하나, 봉투 열 다섯을 붙여서",
                "<code>staged_chunks</code>(#16955, 0.45 ms) → 선언된 표(vqapr.weight · account · monitoring · fill)마다 <code>RecordChunk(table_id, columns)</code>(#16957–#16963): 저자/평가의 열 + <code>run_id · producer_id · stage · event_time</code>(각 count번 반복) + <code>sequence</code>. "
                "chunk는 떼어내진 뒤 다시 검사되지 않는다 — 모든 셀은 append에서 이미 통과했다. <code>RunStateRepository._stage</code>: sink가 있으면 root는 아무것도 들지 않고 chunk는 prepared 후보에 실려 publish까지 간다.",
                fn="InvocationRecorder.staged_chunks() → RecordChunk ×4",
                code=at("src/vqapr/domain/shapes.py", "class RecordChunk", 12),
                mem={"prepared.new_chunks": "(weight 0행, account 1행, monitoring 0행, fill 0행)"},
            ),
            F(
                "06_run_short",
                16978,
                "_deliver: swap 전에 sink로 — 디스크가 못 받으면 이 occurrence가 실패한다",
                "<code>publish_infallible</code>(#16977) → <code>_deliver</code>(#16978, 3.4 ms): <code>prepared.new_chunks</code>를 차례로 <code>self._sink(chunk)</code> — 이 run에선 <code>RunRecordWriter.append_chunk</code>. <b>swap 전</b>이라 sink가 실패하면 root가 바뀌지 않고 직전 occurrence까지는 이미 디스크(버퍼)에 있다. "
                "run 전체에서 <code>_deliver</code> 71회 · <code>append_chunk</code> 203회(빈 chunk 포함).",
                fn="RunStateRepository._deliver() → sink",
                code=at("src/vqapr/flow/engine/run_state.py", "def _deliver", 12),
            ),
            F(
                "06_run_short",
                16984,
                "append_chunk: 열에서 곧장 Arrow — 행은 걷지 않는다",
                "<code>append_chunk</code>(#16984, 1.9 ms — account 1행): <code>row_count</code> 0이면 heartbeat만(#16979 weight). 아니면 <code>_arrow_table(chunk.columns)</code> → 표별 buffer에 append, nbytes 누적, <code>event_time</code>의 distinct 집합으로 instants를 센다(행마다가 아니라). "
                "<code>heartbeat</code>: lock의 mtime을 touch하고 5초마다 <code>checkpoint</code>(progress.json). buffer가 <code>spill_bytes</code>를 넘으면 <code>_spill</code> — 이 run은 <b>0회</b>. 도는 동안 디스크에 행은 없다.",
                fn="RunRecordWriter.append_chunk()",
                code=at("src/vqapr/record/writer.py", "def append_chunk", 29),
                disk={
                    "…/strategies/sample-reversal-5d@fb2406b9/progress.json": "checkpoint 1회 (5초 주기)",
                    "writer.buffer": "account 1행 (Arrow)",
                },
            ),
            F(
                "06_run_short",
                22977,
                "체결 행은 recorder를 거치지 않는다 — 장부 entry에서 바로 chunk로",
                "<code>prepare_account(PreparedAppend)</code>(#22835) 안의 <code>_fill_rows</code>(#22977): 체결 entry 하나당 <code>vqapr.fill</code> 한 행(zero-dealt도 — 시장 사실은 기록된다), 봉투 다섯 필드는 여기서 찍고 <code>sequence</code>는 run의 sequencer(#22978–#22980)에서. "
                "<code>_stage</code>(#23043)로 chunk가 되어 <code>_publish_account_commit</code>의 publish에서 sink로 간다(기록 211: 이전엔 fill 행이 기록을 얼릴 때만 디스크에 닿았다).",
                fn="_fill_rows() → _stage()",
                code=at("src/vqapr/flow/engine/run_state.py", "rows = _fill_rows(", 8, before=3),
                mem={
                    "chunk": "vqapr.fill 3행 (K000004 · K000005 · K000006, kind stock, sequence run 카운터)"
                },
            ),
            F(
                "06_run_short",
                44651,
                "finish: pending이 없어야 하고, root를 finalize한다",
                "32 이벤트 뒤 <code>RunLoop.finish</code>(#44651) → <code>StrategyPart.finish</code>(#44652, 0.68 ms): pending이 남아 있으면 RuntimeError(마지막 결정 01-25 08:00은 01-25 15:30에 체결됐다) → <code>FinalizationEvidence</code> → <code>guard(FINALIZE)</code> 안에서 <code>state.finalize</code> → "
                "<code>SimulationResult(traces 32, root, timing)</code>. <code>timing</code>은 context가 모은 phase별 초 + <code>total</code>(루프만; panel 빌드와 freeze는 바깥, 이슈 068).",
                fn="RunLoop.finish() → StrategyPart.finish()",
                code=at(
                    "src/vqapr/flow/run/loop.py",
                    "root = self._context.state.finalize(RunFinalization(finalization))",
                    6,
                    before=5,
                ),
                mem={
                    "result": "SimulationResult(32 traces, root v11, timing{callback 0.98, due 1.21, …, total 2.24})"
                },
            ),
            F(
                "06_run_short",
                44678,
                "기록은 run이 끝날 때 한 번: seal → strategy.json",
                "<code>freeze_strategy_record</code>(#44678, 806 ms): <code>recorder_rows</code>는 비어 있다(sink가 다 가져갔다) → <code>writer.counts</code>(#44684) · <code>contract_report</code>(#44685: no-short checked 16 · held 16) · as_loaded · roster · exchange settings → <code>StrategyRecord</code> → "
                "<code>RunRecordWriter.finish</code>(#44768, 802 ms): <code>_seal</code>(#44879, <b>789 ms</b> → <code>_write_parquet</code> ×4: account #44882 769 ms(<code>_conform</code> ×16 chunk) · fill #44902 5.8 · monitoring #44917 6.2 · weight) → <code>write_atomically</code>(#44953, strategy.json) → <code>_unlock</code>(#44955). "
                "표가 먼저, 기록이 나중: strategy.json이 있다는 것이 '끝까지 갔다'는 뜻이다.",
                fn="freeze_strategy_record() → RunRecordWriter.finish() → _seal()",
                code=at("src/vqapr/record/writer.py", "def _seal", 22),
                disk={
                    "…/tables/vqapr.account/all.parquet": "49행 · 16 instants",
                    "…/tables/vqapr.fill/all.parquet": "41행 · 11",
                    "…/tables/vqapr.monitoring/all.parquet": "16행 · 16",
                    "…/tables/vqapr.weight/all.parquet": "33행 · 11",
                    "…/strategy.json": "쓰임 (atomic)",
                    "…/progress.json": None,
                    "writer.buffer": None,
                },
            ),
            F(
                "06_run_short",
                44961,
                "배분을 warehouse에: 기록에서 다시 읽어, datamodel과 같은 문으로",
                "<code>_publish_allocation</code>(#44961, 340 ms): 저장된 run은 행을 root에 남기지 않으므로 <code>read_table(vqapr.weight)</code>(#44962, 93 ms)로 기록에서 읽는다(기록 210) → available_at=event_time, weight는 DOUBLE → "
                "<code>RunOutput.open/append/register</code>(#45045, 240 ms: <code>_seal</code> #45069 → <code>_write</code> → <code>validate</code> → <code>Workspace.transaction</code> #45173 → <code>register_dataset</code> #45191 → <code>commit</code> #45198 15.5 ms). "
                "run의 <code>writes</code>가 dataset <code>sample-reversal-5d-short-weights</code>로 등록된다 — 나중 전략이 <code>DataRequirement</code>로 읽는다. 그 다음 <code>_strategy_envelope</code>(#45290: fill 표를 읽어 <code>fill_summary</code>) → <code>success('run.complete')</code>(#45430).",
                fn="_publish_allocation() → RunOutput.register()",
                code=at("src/vqapr/flow/orchestration.py", "output = RunOutput(", 12),
                disk={
                    ".vqapr/materialized/sample-reversal-5d-short-weights/all.parquet": "쓰임 (33행)",
                    ".vqapr/workspace.yaml": "다시 쓰임 (dataset +1)",
                },
                mem={
                    "envelope": "ok · run.complete · strategies{sample-reversal-5d: completed, account_version 11, fills{orders 41, dealt 24}, contract{no-short ok}} · roster"
                },
            ),
        ],
        "remember": [
            "행은 recorder에 <b>열</b>로 쌓이고(<code>append_columns</code>), 표마다 <code>RecordChunk</code> 하나가 되어 publish의 <code>_deliver</code>에서 sink(<code>writer.append_chunk</code>)로 간다 — swap 전에. 기록 221.",
            "sequence는 run 하나의 카운터다(기록 225): 콜백 행·평가 행·체결 행이 한 순서에 선다. 체결 행은 recorder 없이 장부 entry에서 chunk가 된다(기록 211).",
            "도는 동안 디스크에 닿는 것은 lock과 progress.json뿐(heartbeat 235 · checkpoint 1 · spill 0). 기록은 끝에 한 번: <code>_seal</code>이 표 넷을 all.parquet로, 그 다음 strategy.json.",
            "run의 <code>writes</code>는 기록에서 weight를 다시 읽어 datamodel과 같은 <code>RunOutput</code> 문으로 warehouse에 등록된다.",
        ],
    },
    # ---------------------------------------------------------------- ⑧ readers
    {
        "id": "readers",
        "key": "⑧",
        "title": "기록 읽기",
        "sub": "list runs (689 호출 · 59 ms) · show run (30 · 13 ms) · show strategy (27 · 11 ms) · list strategies --run (30 · 12 ms) · show strategy sample-run-short (usage 거절, 35 · 14 ms)",
        "frames": [
            F(
                "08_list_runs",
                11,
                "list runs: 워크스페이스 문서를 읽고 run마다 한 줄",
                "<code>Workspace.open</code>(#12, 45 ms — 689 호출 중 630이 여기: <code>read_workspace</code> #17 → <code>_linked</code> #18 31 ms, source 4 · dataset 4 · component 4 · run 3을 <code>_decoded</code>) → <code>run_definitions</code>(#643) → <code>_summarize</code> ×3(#648 datamodel · #652 · #658 strategy). "
                "봉투: <code>count 3</code>, run마다 kind · model · exchange · execution · writes · <b>recorded</b>(기록 ref: sample-run-short → [sample-reversal-5d@fb2406b9], sample-run → []).",
                fn="list_.run() → Workspace.open() → _summarize() ×3",
                code=at("src/vqapr/cli/list_.py", "def _summarize", 8),
                mem={
                    "envelope": "count 3 · items[sample-features-run (datamodel), sample-run, sample-run-short]"
                },
            ),
            F(
                "09_show_run",
                11,
                "show run: run.json 하나와 그 아래 기록 ref들",
                "워크스페이스를 열지 않는다. <code>run_ids</code>(#12, 0.6 ms: runs/ 아래 run.json이 있는 디렉터리) → <code>read_run_record</code>(#16 → <code>run_record_path</code> → <code>_mapping_at</code>) → <code>record_view</code>(#19) → <code>strategy_refs</code>(#20: strategy.json이 <b>있는</b> 디렉터리만) · <code>datamodel_refs</code>(#23) → <code>success('run.show')</code>(#24). "
                "봉투: declared_digest · instruments 10 · execution(fill 15:30 close) · initial_account · datasets(source_digest) · recorded [sample-reversal-5d@fb2406b9].",
                fn="show.run() → read_run_record() → strategy_refs()",
                code=at("src/vqapr/record/reader.py", "def strategy_refs", 14),
                disk={".vqapr/runs/sample-run-short/run.json": "읽음"},
            ),
            F(
                "10_show_strategy",
                12,
                "show strategy <run>/<id>@<fp8>: ref를 풀고 strategy.json을 읽는다",
                "<code>resolve_strategy</code>(#12) → <code>resolve_member(kind='strategy')</code>(#13): 식별자를 <code>run_id/rest</code>로 나누고 <code>strategy_refs</code>(#14)의 known에 있는지 → <code>read_strategy_record</code>(#17 → <code>read_member_record</code> #18 → <code>record_directory</code> → <code>_mapping_at</code> #20, 0.5 ms) → <code>success('strategy.show')</code>(#21). "
                "표는 읽지 않는다 — 봉투의 <code>tables</code>(account 49/16 · fill 41/11 · monitoring 16/16 · weight 33/11)는 writer가 셌던 수다. account(cash 10,688,433 · 보유 3) · contract · timing · as_loaded(등록과 같음)도 기록에서.",
                fn="resolve_member() → read_member_record()",
                code=at("src/vqapr/record/reader.py", "def read_member_record", 12),
                disk={"…/strategies/sample-reversal-5d@fb2406b9/strategy.json": "읽음"},
            ),
            F(
                "10b_show_strategy_usage",
                13,
                "짧은 이름은 거절: argument.value_invalid, 고치는 법과 함께",
                "<code>show strategy sample-run-short</code>(run id만): <code>resolve_member</code>(#13)가 <code>/</code>가 없으니 <code>InputError(VALUE_INVALID)</code>(#14, 3.1 ms — <code>Cause.here</code> #16이 프레임을 걸어 올라가 'vqapr/cli/show.py:317 (resolve_member)'를 적는다) → "
                'main의 except → <code>failure</code>(#23) → 봉투 <code>ok:false · stage usage · status 400 · requirement "show strategy takes `&lt;run-id&gt;/&lt;strategy-id&gt;@&lt;fp8&gt;`" · fix "run `vqapr list strategies --run &lt;run-id&gt;` to see the records, then show one" · mutation false</code>. exit 1.',
                fn="resolve_member() → InputError → failure()",
                code=at("src/vqapr/cli/show.py", "if not slash or not rest", 8),
                mem={
                    "envelope": "ok:false · argument.value_invalid (400) · retry: list strategies --run"
                },
            ),
            F(
                "12_list_strategies",
                12,
                "list strategies --run: 끝난 기록 + 끝나지 않은 디렉터리",
                "<code>_strategies</code>(#12, 1.6 ms): <code>strategy_refs</code>(#14)마다 <code>read_strategy_record</code>(#17) → <code>status completed</code> · account_version 11 · contract_failed [] · period(occurrences 32) · tables 4; 그 다음 <code>unfinished_strategy_refs</code>(#21 → <code>unfinished_member_refs</code> #22: strategy.json이 없는 디렉터리 — 이 run엔 없다). "
                "죽은/거절된 전략은 여기 <code>unfinished</code>로, 도는 중인 것은 lock이 신선하면 <code>running</code>으로 보인다.",
                fn="_strategies() → strategy_refs() · unfinished_strategy_refs()",
                code=at("src/vqapr/cli/list_.py", "for ref in strategy_refs(root, run_id)", 12),
                mem={
                    "envelope": "count 1 · [sample-reversal-5d@fb2406b9: completed, account_version 11, contract_failed []]"
                },
            ),
        ],
        "remember": [
            "<code>list runs</code>는 워크스페이스 문서를 읽고(그게 비용의 전부), <code>show run · show strategy · list strategies</code>는 <b>기록 파일만</b> 읽는다 — 문서도, parquet도 열지 않는다.",
            "'끝났다'의 정의는 파일 하나다: run은 run.json, 전략은 strategy.json. 없으면 <code>strategy_refs</code>가 세지 않고 <code>unfinished_*</code>가 센다.",
            "기록 ref는 <code>&lt;run-id&gt;/&lt;id&gt;@&lt;fp8&gt;</code>. 짧은 이름은 usage 거절(400)이고 봉투가 <code>list strategies --run</code>을 가리킨다.",
        ],
    },
    # ---------------------------------------------------------------- ⑨ datamodel
    {
        "id": "dm",
        "key": "⑨",
        "title": "datamodel run",
        "sub": "vqapr run sample-features-run · 1,724 ms · 20,128 호출 — 같은 RunLoop, market=None · 16 세션 · 첫 compute 843 ms(panel 읽기) 이후 4~15 ms · RunOutput.register → sample-features-values · datamodel.json",
        "frames": [
            F(
                "07_run_features",
                12,
                "같은 _run_one, datamodel로 얼려진다",
                "<code>preflight_run</code>(#624, 456 ms: judgments의 <code>_judge_member_datasets</code> → <code>_first_decision</code> 254 ms) → <code>_preflight_datamodel_run</code> → <code>_freeze_datamodel</code>(#7341, 11.9 ms: features.py import #7351 → <code>inputs()</code> #7355: sample-prices.close, RowsLookback 6) → "
                "<code>FrozenRun(datamodel=…)</code>. 그 다음 <code>orchestration.run</code>은 <code>frozen.datamodel</code>이 있으니 <code>_run_datamodels</code>(#7616)로 — venue도, 집행표도, 계좌도 없다.",
                fn="_run_one() → preflight_run() → _freeze_datamodel()",
                code=at("src/vqapr/flow/declaration/preflight.py", "def _freeze_datamodel", 8),
                mem={
                    "frozen": "FrozenRun(sample-features-run: datamodel sample-features, value_fields [value], agenda 16:00 days_from sample-prices)"
                },
            ),
            F(
                "07_run_features",
                7745,
                "_run_member(member_kind='datamodel'): 전략과 같은 자원",
                "<code>freeze_run_record</code>(#7620, run.json) → <code>_run_datamodel</code>(#7668: <code>load_data_model</code>, as_loaded, requirements drift 검사) → <code>_run_member</code>(#7745, 1,181 ms): 카탈로그 · ScanSession · 스토어 · <code>RunRecordWriter.open</code> → body(#7759). "
                "장면 ③의 #8529와 같은 함수, <code>member_kind</code>만 다르다(기록 228).",
                fn="_run_datamodel() → _run_member()",
                code=at("src/vqapr/flow/orchestration.py", "return _run_member(", 8),
                disk={
                    ".vqapr/runs/sample-features-run/run.json": "쓰임",
                    "…/datamodels/sample-features@67d5fa16/": "디렉터리 + lock",
                },
            ),
            F(
                "07_run_features",
                7766,
                "DataModelEventLoop: RunLoop(part=DataModelPart, market=None)",
                "body 안에서 <code>RunOutput</code>(#7762: writes=sample-features-values, value_fields, run_id, record_ref) → <code>_window_factory</code> 하나 → <code>DataModelEventLoop.__init__</code>(#7766, 5.7 ms): layer 대조 → <code>ComputeHandler</code>(#7767) → "
                "<code>RunLoop.__init__(schedule=dispatch_order(layer), part=DataModelPart(compute, output))</code>(#7880) — <b>market 없음</b>. 조립만 다르고 걷기는 같다(기록 227).",
                fn="DataModelEventLoop.__init__() → RunLoop(part, market=None)",
                code=at(
                    "src/vqapr/flow/run/loop.py",
                    "part=DataModelPart(compute, output),",
                    6,
                    before=3,
                ),
                mem={"loop": "RunLoop(schedule 16, part=DataModelPart, market=None)"},
            ),
            F(
                "07_run_features",
                7883,
                "EventLoop.run: start가 warehouse 문을 열고, events는 16개뿐",
                "<code>RunLoop.start</code>(#7884) → <code>DataModelPart.start</code>(#7885) → <code>RunOutput.open</code>(#7886: 죽은 run이 남긴 디렉터리를 치운다) → <code>RunLoop.events</code>(#7887, 0.97 ms: market이 None이라 occurrence 16만; 장면 ③의 17 ms와 비교) → <code>handle</code> ×16 → <code>finish</code>(#19687). "
                "1,059 ms 중 첫 handle(#8026)이 846 ms.",
                fn="EventLoop.run() → DataModelPart.start() → RunOutput.open()",
                code=at("src/vqapr/flow/run/loop.py", "self._output.open()", 10, before=4),
                clock={"events": "16 (16:00 KST, days_from sample-prices)"},
            ),
            F(
                "07_run_features",
                8028,
                "ComputeHandler.dispatch: 창 → compute(저자) → 검증 → available_at 도장 → output.append",
                "<code>_window_for_occurrence</code>(#8033 → <code>ModelWindow</code>) → <code>model.compute(DataModelContext(window, reads))</code>(#8069, <b>843 ms</b> — <code>read</code> #8070 → <code>panel</code> #8089 → <code>panel_window</code> #8090 → <code>observation_rows</code> #8107 805 ms → <code>Panel.from_rows</code> #15049 20.6 ms; 장면 ⑤와 같은 길) → "
                "<code>validated_output</code>(#15115: instrument · value_fields, 선언된 instrument만) → <code>derived_available_at</code>(#15118: 창의 access에서) → <code>RunOutput.append</code>(#15120: 이 세션은 <code>rows=[]</code> — lookback이 안 찼다). "
                "저자 예외는 <code>datamodel.compute_failed</code>(CRASHED)로 감싸진다. 두 번째 세션(#15125)은 6.7 ms.",
                fn="ComputeHandler.dispatch() → SampleFeatures.compute()",
                code=at(
                    "src/vqapr/flow/run/compute.py", "raw = self._model.compute(", 12, before=3
                ),
                disk={"sample/observations.parquet": "읽음 (1회, span 전체)"},
                mem={
                    "panels": "Panel(sample-prices) 캐시",
                    "trace": "DataModelTrace(row_count 0, accesses)",
                },
            ),
            F(
                "07_run_features",
                15120,
                "RunOutput.append: pyarrow가 첫 비어 있지 않은 세션에서 스키마를 고정한다",
                "<code>append</code>(16회, 이 run은 <code>_write</code>(spill) 0회 — 세션 표는 Arrow로 메모리에): <code>pa.Table.from_pylist(rows, schema)</code>; 첫 비어 있지 않은 세션의 추론 스키마가 그 뒤 모든 세션의 기준이고, 안 맞으면 <code>schema_mismatch</code>(pyarrow의 문장 그대로, 이슈 079). "
                "value는 float — dataset 필드는 DOUBLE이지 DECIMAL이 아니다(기록 173).",
                fn="RunOutput.append()",
                code=at(
                    "src/vqapr/flow/run/output.py", "table = pa.Table.from_pylist(", 8, before=2
                ),
                mem={"output": "buffered (Arrow, 메모리) · rows 108 / sessions 16"},
            ),
            F(
                "07_run_features",
                19721,
                "register: seal → validate(4단계) → 트랜잭션 → 그 다음에야 datamodel.json",
                "<code>DataModelPart.finish</code>(#19688) → body가 <code>output.register(Workspace.open)</code>(#19721, 95 ms): <code>DatasetRegistration.of</code> · <code>with_producer(run_id, record_ref)</code>(#19737: 어느 run·어느 기록이 만들었는지) → <code>_seal</code>(#19744 → <code>_write</code> #19745: all.parquet 하나) → "
                "<code>validate</code>(#19746, 73 ms: describe · schema · key · span · values — 장면 ①의 그 네 단계) → <code>Workspace.transaction</code> → <code>register_dataset</code>(#19866) → <code>commit</code>(#19873, 16 ms). 실패하면 <code>_discard</code>가 디렉터리를 지운다. "
                "그 다음 <code>freeze_datamodel_record</code> → <code>RunRecordWriter.finish(kind='datamodel')</code>(#19985 → <code>_seal</code> #20101 → <code>write_atomically</code> #20105). 등록이 상품이고 기록은 '끝났다'의 표시다.",
                fn="RunOutput.register() → validate() → Transaction.commit() → finish(kind='datamodel')",
                code=at("src/vqapr/flow/run/output.py", "self._seal()", 8, before=1),
                disk={
                    ".vqapr/materialized/sample-features-values/all.parquet": "쓰임 (108행)",
                    ".vqapr/workspace.yaml": "다시 쓰임 (dataset +1, producer sample-features-run)",
                    "…/datamodels/sample-features@67d5fa16/datamodel.json": "쓰임",
                },
                mem={
                    "envelope": "ok · run.complete · datamodels{sample-features: rows 108, sessions 16, dataset_id sample-features-values, record sample-features@67d5fa16}"
                },
            ),
        ],
        "remember": [
            "datamodel run은 <b>같은 RunLoop</b>다: <code>RunLoop(part=DataModelPart, market=None)</code>. 시계가 하나라 events는 occurrence뿐이고, 세션 사이에 아무 일도 없다.",
            "<code>_run_member</code>는 전략과 같은 함수(<code>member_kind</code>만 다름): 세션 하나·스토어 하나·writer 하나·기록 재읽기.",
            "compute의 첫 세션이 판 읽기 비용을 진다(805 ms); 이후 세션은 슬라이스다. 출력은 세션마다 Arrow로 메모리에 쌓이고 <code>register</code>에서만 seal된다.",
            "등록 순서: seal → validate(네 단계) → 트랜잭션 commit → datamodel.json. 등록이 상품이고 기록은 완료 표시다 — 반대로 하면 '썼다'는 기록 옆에 없는 dataset이 생긴다.",
        ],
    },
    # ---------------------------------------------------------------- ⑩ refusal
    {
        "id": "refuse",
        "key": "⑩",
        "title": "거절",
        "sub": "vqapr register stale.yaml · 334 ms · 805 호출 · exit 1 — observe(self, call, account)로 쓴 0.10.0식 Compliance: conformance의 _check_methods가 component.signature_invalid(422)로 거절, 워크스페이스는 그대로",
        "frames": [
            F(
                "11_register_stale",
                14,
                "같은 _apply, 같은 순서 — components 섹션에서 멈춘다",
                "<code>_apply</code>(#14, 317 ms): 트랜잭션(#649) → <code>_require_declared_ids</code> → 섹션 순서대로. 이 문서엔 component 하나(<code>stale-cap</code>, kind compliance, <code>stale_rule.py</code>, config compliance_id) → <code>_component</code>(#667, 14.2 ms).",
                fn="_apply() → _component()",
                code=at(
                    "src/vqapr/project/registration.py",
                    'for component_id, body in section("components")',
                    5,
                ),
                mem={"transaction.staged": "[]"},
            ),
            F(
                "11_register_stale",
                670,
                "prepare_component: fingerprint는 되고, 그 다음 conformance",
                "<code>prepare_component(kind=compliance)</code>(#670, 14.0 ms) → <code>fingerprint_component</code>(#671, 0.7 ms: 바이트는 읽힌다) → <code>ComponentRef.of</code> → <code>conformance</code>(#755, 8.6 ms) → <code>load_compliance</code>(#757 → <code>_load</code> #758: import + <code>StaleCap(compliance_id='stale-cap')</code> #767 — 생성은 된다).",
                fn="prepare_component() → conformance() → load_compliance()",
                code=at(
                    "src/vqapr/extension/conformance.py",
                    "component = _LOADERS[ref.kind]",
                    6,
                    before=2,
                ),
                mem={"component": "StaleCap (생성됨)"},
            ),
            F(
                "11_register_stale",
                770,
                "_check_methods: 계약 메서드의 arity — observe는 인자 하나여야 한다 (기록 229)",
                "<code>_check_methods</code>(#770, 4.5 ms): <code>_CONTRACT_METHODS[compliance]</code>의 (base, name)마다 → <code>accepts_contract_call(implementation, contract)</code>(#771 → <code>positional_arity</code> #772 · #773) → 안 맞으니 <code>positional_arity</code>(#774 · #775) 로 wanted 2 / observed 3 → <code>_signature_hint</code>(#776) → "
                "<code>Failure.bounded('component.signature_invalid', 'Compliance.observe() must accept 2 positional arguments', status CONTRACT, observed 'StaleCap.observe takes 3 (3 required)', fix 'define it as observe(self, arg1) …')</code>(#779) → <code>_Collector.add</code>(#788). "
                "Flow는 위치 인자로 부르므로 이름이 아니라 <b>개수</b>를 본다.",
                fn="_check_methods() → accepts_contract_call() → Failure.bounded()",
                code=at(
                    "src/vqapr/extension/conformance.py",
                    '"component.signature_invalid"',
                    16,
                    before=6,
                ),
                mem={"found": "[component.signature_invalid (422)]"},
            ),
            F(
                "11_register_stale",
                790,
                "raise_if_failed → VqaprError(stage=register) — 스테이징된 것 없이",
                "<code>conformance</code>가 돌려준 <code>Diagnosis</code>의 <code>raise_if_failed</code>(#790) → <code>VqaprError.__init__(stage=REGISTER)</code>(#791). <code>prepare_component</code>는 쓰는 것이 없었고 <code>register_component</code>에 닿지 않았으니 트랜잭션은 비어 있고 commit은 없다. "
                "<code>files_after</code>: workspace.yaml은 그대로(장면 ⑦·⑨가 남긴 dataset 둘과 run 셋).",
                fn="Diagnosis.raise_if_failed() → VqaprError",
                code=at("src/vqapr/domain/errors.py", "def raise_if_failed", 6),
                disk={".vqapr/workspace.yaml": "변화 없음"},
                mem={"transaction.staged": None},
            ),
            F(
                "11_register_stale",
                795,
                "봉투: ok:false · stage register · 422 · fix가 쓸 시그니처를 말한다",
                'main의 except → <code>failure(error, stage=register)</code>(#795) → <code>VqaprError.as_dict</code>(#796) → <code>Failure.as_dict</code>(#797). 봉투: <code>code component.signature_invalid · status 422 · requirement "Compliance.observe() must accept 2 positional arguments" · observed "StaleCap.observe takes 3 (3 required)" · '
                'fix "define it as observe(self, arg1) so it accepts exactly 2 positional arguments" · cause.where "vqapr/extension/conformance.py:154 (_check_methods)" · retry_precondition "fix the component to match its contract, then register it again" · mutation false</code>. exit 1.',
                fn="failure() → emit()",
                code=at("src/vqapr/cli/envelope.py", "def failure", 6),
                mem={
                    "envelope": "ok:false · register · component.signature_invalid (422) · mutation false"
                },
            ),
        ],
        "remember": [
            "0.11.0의 계약: Compliance는 <code>observe(self, call)</code> 하나를 받고 장부는 <code>call.account</code>다(기록 229). 0.10.0식 <code>observe(self, call, account)</code>는 <b>등록 시점</b>에 거절된다 — run까지 가지 않는다.",
            "conformance는 import·생성까지 한 뒤 계약 메서드의 <b>arity</b>를 본다. 이름(<code>ctx</code>든 <code>call</code>이든)은 상관없고 개수가 맞아야 한다.",
            "거절은 트랜잭션 밖에서 일어난다: 스테이징도 commit도 없고 workspace.yaml은 그대로. 봉투의 <code>fix</code>가 쓸 시그니처를 그대로 말한다.",
        ],
    },
]

TABLE = {
    "title": "트레이스가 확인한 것 — 0.11.0이 바꾼 여섯 가지가 보이는 자리",
    "rows": [
        [
            "<b>루프는 하나다</b> — Part가 전략 시계, MarketClock이 시장 시계 (기록 227)",
            "run: <code>EventLoop.run</code> #9043 → <code>RunLoop.handle</code> ×32 → <code>StrategyPart.dispatch</code> ×16 (#21603 …) · <code>MarketClock.at</code> ×16 (#22387 …) · datamodel: <code>RunLoop.handle</code> ×16 → <code>DataModelPart.dispatch</code>, <code>RunLoop.events</code> #7887 0.97 ms(market None). 같은 <code>flow/engine/loop.py:102</code>",
            "<code>StrategyEventLoop</code>·<code>DataModelEventLoop</code>는 조립(생성자)만 남았다. 무엇이 다른지는 <code>RunLoop(part, market)</code>의 인자로 다 말해진다",
        ],
        [
            "<b>시장 시계 한 점은 fold</b> — accrue → fill → mark → observe → close (기록 226)",
            "#22387: <code>accrue</code> #22391 → <code>fill</code> #22394 (33.5 ms) → <code>mark</code> #23089 → <code>observe</code> #23325 → <code>close</code> #23660 · 보유만인 점 #16813: <code>fill</code> 0.003 ms(due None) → <code>mark_held</code> #16822 · <code>require_marked</code> #23329는 VALUATION 뒤에만",
            "네 개의 다른 모양 지역변수 대신 <code>MarketInstant</code> 하나가 단계마다 자기 필드를 채운다. 순서는 wiring 테이블이 말하고 테스트가 붙든다",
        ],
        [
            "<b>행은 열로 흐른다</b> (기록 221)",
            "<code>append_columns(vqapr.account)</code> #16933 · #23215 → <code>staged_chunks</code> #16955 → <code>RecordChunk</code> ×4 → <code>_deliver</code> #16978 → <code>append_chunk</code> ×203 (Arrow 메모리) · <code>_spill</code> 0 · 끝에 <code>_seal</code> #44879 → <code>_write_parquet</code> ×4",
            "3,000 이름의 평가 행은 dict 3,000이 아니라 튜플 일곱이다. exp_221: 3,000종목 1일 117 s → 34 s, 붙들린 Mark 1,167,000 → 3,000",
        ],
        [
            "<b>집행표는 미리 읽는다</b> (기록 222)",
            "<code>ExecutionSnapshots.__init__</code> #16829 · <code>_ensure</code> #16831 18 ms → <code>execution_window_table</code> 1회 · 이후 <code>at</code> #22404 0.56 ms(slice) · <code>exact_execution_snapshot</code> 0회 · <code>execution_horizon</code> #9088 14 ms 1회",
            "체결과 평가가 같은 read의 같은 행을 본다. 시각당 쿼리가 사라졌다",
        ],
        [
            "<b>sequence는 run 하나의 순서</b> (기록 225)",
            "<code>RunStateRepository.next_sequence</code> #16950(VALUATION recorder) · #22978–#22980(<code>_fill_rows</code>) · 콜백 recorder도 <code>sequencer=next_sequence</code>",
            "콜백·평가·체결 행이 한 카운터에 선다. 표를 합쳐 정렬해도 순서가 보존된다",
        ],
        [
            "<b>역할은 Call 하나</b> — observe(call), call.account (기록 229)",
            "<code>NoShort.observe</code> #23397 (인자: <code>ComplianceContext(window, account, instruments, reads)</code>) · <code>StaleCap.observe(call, account)</code> → <code>_check_methods</code> #770 → <code>component.signature_invalid</code> #779, 등록에서",
            "네 역할이 같은 모양이 됐다: Call 하나 받고 Judgment 하나 돌려준다. 옛 시그니처는 run이 아니라 register에서 죽는다",
        ],
        [
            "<b>멤버의 자원은 한 함수</b> (기록 228)",
            "<code>_run_member</code> #8529 [member_kind='strategy'] · #7745 [member_kind='datamodel']: <code>ScanSession</code> 1 · <code>RunRecordWriter.open</code> → body → <code>session.close</code> → <code>read_record</code> · <code>_window_factory</code> #8915(전략) · #8916(규칙)",
            "세 루프가 손으로 만들던 것(세션·스토어·writer·창 람다)이 한 곳에 있다",
        ],
        [
            "기록은 run 끝에 한 번, 리포트·show는 기록에서 (0.6.0과 같다)",
            "<code>freeze_strategy_record</code> #44678 → <code>finish</code> #44768 → <code>_seal</code> #44879 → strategy.json #44953 · <code>show strategy</code>: 27 호출, <code>read_member_record</code> #18 0.7 ms · <code>list strategies</code>: <code>unfinished_member_refs</code> #22",
            "도는 동안 디스크엔 lock + progress.json(heartbeat 235 · checkpoint 1). 읽는 쪽은 all.parquet과 json만 본다",
        ],
        [
            "cold 스캔이 절대치를 지배한다",
            "register <code>check_span</code> #210 9,463 ms · check <code>_judge_execution_ordering</code> #624 11,460 ms(evaluation_times 4,263 + candidate_instants 7,114) · run의 같은 판정 <code>require_judged</code> #601 642 ms · 첫 panel <code>observation_rows</code> #9480 425 ms / #8107 805 ms",
            "판끼리 절대치를 비교하지 말 것. 구조의 값은 상대 비교에 있다: 두 번째 콜백 4.5 ms, 두 번째 세션 6.7 ms",
        ],
    ],
}
