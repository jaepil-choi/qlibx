# 066 -- `register` from a subdirectory creates a second workspace silently, and the refusal that follows names the missing datasets but not the workspace it looked in

**Status:** open. Found 2026-09-03 by the scenario testbed run 2
(`kaist-thesis/vqapr-scenario-testbed/`, FINDINGS **F-004**, `Unsure`; the evaluator files it as a
message defect), against `vqapr-0.3.0`. Confirmed against source the same day.

**Touches:** `src/vqapr/workspace.py:261-267` (`Workspace.create`: open if `.vqapr` exists here,
else write a fresh one; no look at parent directories); `src/vqapr/cli/main.py:186` (`--root`,
*"workspace root (defaults to the current directory)"*); `src/vqapr/cli/envelope.py` (no
`workspace_root` in the success or failure envelope).

## What happens

`vqapr register ff6_resid.yaml` run with cwd `work/decl/` succeeded -- into a brand-new
`work/decl/.vqapr`. `vqapr check mat_smoke.yaml` from the same cwd then refused:
*"every dataset the model declares it reads must be registered / unregistered: kr-daily,
kr-factors"*, fix *"register the missing datasets"*. The datasets had been registered five minutes
earlier from the project root. Following the fix would have registered duplicates into the wrong
workspace. The only clue was `work/decl/.vqapr/diagnostics` in the `detail` path of the
oversized-payload dump; the agent noticed it, deleted the stray workspace, and re-ran from the
root.

The default is documented, so the trap is not undocumented. But a refusal that names the cure
without naming the place it looked is a message defect of the `015`/`016` family: correct, and
not enough to act on.

## What to do

- Every envelope carries `workspace_root: <absolute path>`; a refusal about registration state
  says which workspace has that state.
- `Workspace.create` warns -- or refuses without `--root` -- when it is about to create a
  `.vqapr` while an ancestor directory already holds one. Git's discovery rule is the model: walk
  up, and say when you did.
