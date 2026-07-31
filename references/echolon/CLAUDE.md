# echolon

See `../CLAUDE.md` for all cross-repo operating law (pre-dispatch checklist, communication protocol, Fable-mode protocol, Codex dispatch incl. session-ID resume, compute/time discipline, instrument-consistency law, evidence law — same-data-twice & criteria freeze).

## Generic-mechanism-only boundary
echolon is PUBLIC open-source: no instrument names, calibration dates/values, selection
objectives, capital numbers, or profit-recipe details in code, tests, or comments.

## Cost/fee fields never silently default
Commission, slippage, and fee fields must never hardcode or default to 0 or a
placeholder — this exact pattern caused a live-record gap and the research-mode batch
void of 2026-07-16 (¥5-min-fee). Missing cost data is a hard failure, not a zero.
