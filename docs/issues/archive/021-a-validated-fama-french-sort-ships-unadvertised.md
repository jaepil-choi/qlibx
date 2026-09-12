# 021 — The package ships Fama-French sorting helpers and nothing points at them

**Status:** **closed** by `fix/021-skill-names-public` (docs-only, no implementation record). The skill now names `vqapr.public`, shows how to enumerate it, and names the three helper families.

**Status when filed:** open. Found 2026-08-30 by the final first-time-user journey in
`kwam-enhanced-index/vqapr-final-testbed/`, against `vqapr-0.2.0a1`. Recorded there as **F-002**,
`slowed` — and it is the finding with the largest gap between what the distribution contains and
what its documentation admits to.
**Touches:** the installed skill (426 lines, and it never says the word `public`),
`src/vqapr/public.py`.

## What the reporter expected

Nothing. They were planning a Fama-French 2x3 sort and had no reason to think the package had an
opinion about breakpoints, so they set out to hand-roll the 30/70 cut points and the bucket
assignment in their own prep code. The skill's "Writing a strategy" section shows
`inputs`/`decide`/`Rebalance.of` and nothing else, and its CLI reference says the CLI help is the
authoritative usage reference. Neither mentions a library surface beyond `vqapr.authoring`.

## What is actually there

`dir(vqapr.public)`, run out of habit before writing the venue, returned roughly 140 exported names
including:

```
fama_french_assign, fama_french_cut_points, proportional_weight, equal_weight,
signal_weight, net_members, neutralize, optimize, rank, information_coefficient,
rank_information_coefficient, nav_series, returns, drawdown, hit_rate, decay, rescale
```

`fama_french_cut_points(values, reference=..., fractions=(0.3, 0.7))` is exactly the breakpoint
call, and its own docstring says `linear` *"matches the pandas/numpy default used by the validated
Korean replication"* — so the package has a **validated Korean Fama-French replication** behind it.

The reporter's assessment: *"That is the single most relevant fact in the distribution for the task
I was given, and no surface I was pointed at names it."*

## The cost, and why it is larger than the five minutes it took

Five minutes here, because `dir()` is a habit. Without that habit it would have cost the whole prep:
hand-rolled quantile code, a different interpolation, and portfolio memberships that disagree with
the package's own validated replication **for no visible reason** — a difference that produces
wrong numbers rather than an error.

The same introspection habit is what resolved 017 (`AccountMode`), 018 (the `invested` bound) and
020 (`ListingAccess`). Four of this journey's findings were resolved by enumerating a module, and
the skill never mentions that the module exists.

## What closes it

One line in the skill saying `vqapr.public` exists, and what families of helper live in it —
**sorting, weighting, measurement** — with `vqapr.authoring` named as the subset a component needs.

That is the whole remedy, and it is deliberately small. This is not a request to document 140 names.
It is a request for the one sentence that makes `dir()` an obvious next move instead of a habit some
readers happen to have.

## The behaviour is right

Worth stating plainly, because the severity understates it: the helpers are excellent and the
validated replication is exactly what a user doing this work wants. This file is about discovery
only.
