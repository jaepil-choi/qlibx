# 258 — The skills are installed at the workspace root, the root every other command and the stale-skill note use

| | |
|---|---|
| **작성 시각** | 2026-09-11 KST (+09:00) |
| **캠페인** | 없음 — testbed 보고 수정 (오너 지시로 `develop` 위에서 바로) |
| **이슈** | `docs/issues/report-2026-09-11-skill-install-writes-into-the-enclosing-repositorys-git-root-not-the-project-that-installed-vqapr.md` |
| **설계 근거** | PRD §11.2 설치 경로 — "package가 임의의 output location을 추측하지 않는다" |
| **브랜치** | `develop` |
| **앞선 기록** | `175`(skill은 집합이고 설치가 release를 선언한다), `095`(stale 메시지가 실제 명령을 댄다), `docs/issues/archive/066`(workspace root 규칙) |

---

## 왜 이 변경이 있는가

demo testbed가 다른 git 저장소(`kwam-enhanced-index/`) 한 단계 안에 자기 uv 프로젝트를 두고 문서의 두 줄
(`uv add vqapr`, `uv run vqapr skill install`)을 쳤다. skill 열 개와 manifest가 **바깥 저장소**의
`.claude/skills/`·`.agents/skills/`에 깔렸고, 그 저장소 루트에 열려 있던 Claude Code 세션이 곧바로 그것을 자기
skill로 올렸다 — vqapr와 무관한 프로젝트의 agent가 부르지 않은 지시를 읽은 것이다. 봉투는 `root`(바깥 `.git`)와
`workspace_root`(testbed)를 서로 다른 두 디렉터리로 보고하면서 `ok: true`였다. 같은 걷기가 두 가지를 더 냈다:
`--project-root .`에서는 `Path(".")`에 parents가 없어 바로 위의 `.git`도 못 찾고 404를 냈고(발견 2), `.git`이 없는
새 폴더 — 처음 쓰는 사람의 경로 — 에서는 거절하며 `fix`가 입력을 대지 못했다(발견 3, `retry`가 없어 기본 문장).

소스를 읽다 넷째가 나왔다. 다른 모든 명령이 부르는 stale 검사 `upgrade_note(project_root)`는 **workspace root**의
manifest를 읽는다. 그러니 `.git` 루트에 깔린 사본은 버전이 어긋나도 한 번도 경고되지 않았다.

쉽게 말하면 한 집에 주소가 둘이었다. 택배(설치)는 단지 관리실(가장 가까운 `.git`)로 배달되고, 우편함 점검(stale
검사)은 우리 집 현관(workspace root)에서 했다. 단지에 우리 집만 있으면 둘이 같은 곳이라 아무도 몰랐다.

## 무엇이 어떻게 바뀌었는가

**루트를 하나로.** `cli/skill.py::run`이 `root = Path(args.into or project_root).resolve()` — `install`·`list`·
`remove` 모두 workspace root(현재 디렉터리, 또는 `vqapr --project-root`)에서 일하고, `--into`는 그대로 명시적 다른
루트다. `_find_git_root`와 `argument.no_git_root` 거절은 지웠다: 루트가 언제나 있으므로 거절할 일이 없다. 발견
2·3은 따로 고칠 것이 없어졌다 — `resolve()`가 `.`을 절대 경로로 바꾸고, `.git`은 더 이상 묻지 않는다.

- `--into` help: "act on this directory instead of the workspace root (the current directory, or --project-root)".
- `vqapr skill --help`의 설명: record `175` 이후에도 "`.agents/skills/vqapr/`에 깔고 `.claude/skills/`에는 그것을
  가리키는 thin adapter"라고 말하고 있었다 — 두 target이 같은 bytes를 받는 지금의 계약과 루트를 말하도록 고쳤다.
- skill `introduce-vqapr/references/install-and-environment.md`, `agent/skills/README.md`, PRD §11.2 설치 경로가 같은
  말을 한다(PRD에 "조상의 `.git`을 찾아 올라가지 않는다" 한 문장).

## 바꾸지 않은 것, 그리고 왜 그것으로 충분한가

`.git` 걷기가 쓸모 있던 경우는 하나였다: 프로젝트의 하위 디렉터리에서 명령을 친 경우. 그 경우는 모든 명령이 이미
가진 `_resolve_project_root` 규칙(`archive/066`)이 막는다 — 조상에 workspace가 있고 여기에 없으면 둘 다 이름을 대며
거절한다. skill 설치만 따로 위로 걸을 이유가 남지 않는다. target 경로의 모양, `--into`, 판정(`agent/skillset.py`),
manifest는 그대로다.

## 깨지는 변화 (다음 릴리스 노트에 한 줄)

workspace가 git 루트보다 아래에 있고 그 workspace에서 설치한 프로젝트는 skill이 git 루트에 있다. 이제 그 workspace에서
`skill list`는 설치되지 않았다고 말하고 `skill install`은 workspace에 깐다. 옛 사본은 스스로 사라지지 않으므로
`vqapr skill remove --into <git 루트>`로 걷는다. workspace가 git 루트와 같은 흔한 경우는 아무것도 바뀌지 않는다.

## 검증

| 검사 | 결과 |
|---|---|
| `tests/cli/test_skills_install_where_the_workspace_is.py` (신규, 넷) | 다른 저장소 안의 프로젝트가 skill을 자기가 받는다(`root == workspace_root`, 바깥엔 `.claude`/`.agents` 없음); `--project-root .`이 생략과 같은 `root`·`written`; `.git` 없는 새 폴더가 설치된다; 설치한 곳을 stale 검사가 읽는다(manifest 버전을 바꾸면 `list datasets`의 stderr가 그것을 댄다) |
| 기존 skill 테스트 네 파일의 `(tmp_path / ".git").mkdir()` 13줄 | 삭제 — 더 이상 아무것도 그것을 읽지 않는 죽은 준비였다 |
| 신규 파일 + 그 네 파일 + `tests/cli/test_new_exchange.py`(`--into`) + `tests/agent` (`-m ""`) | 197 passed |
| 보고의 세 재현을 실제 CLI로 (scratchpad: `R/.git`, `R/P`, 빈 `fresh/`; `--target claude --dry-run`) | P에서 생략: `root == workspace_root == R\P`, 56개 · P에서 `--project-root .`: 같은 `root`, 56개 · `fresh`: `ok: true`, 56개. `R`에는 아무것도 생기지 않았다 |
| `uv run ruff check src/` · `uv run python -m pyright` (바뀐 파일) | clean · 0 errors |
| `test_all` (`uv run python -m pytest tests/ -q -m ""`) | 1771 passed, 1 skipped, 286.9 s |
