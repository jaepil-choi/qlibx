"""What a finished run's record answers about how the strategy did -- computed once, from the rows.

Three modules. `document` is the shape of the answer: one pydantic document per strategy
(`StrategyReport`) and one per run (`RunReport`), JSON-ready through `as_record()`.
`measure` turns the four tables every run records (`vqapr.account`, `vqapr.fill`, `vqapr.weight`,
`vqapr.monitoring`) into those sections, as pure functions of rows. `record` is the door: it
opens a record on disk through `vqapr.flow.record` and hands the rows to `measure`.

PRD UC-REPORT-001 fixes the boundary: the package provides the values and a machine-readable
renderer; it ships no visualisation. A figure is a renderer a user composes over the same values,
which is why every series here is a list of instants beside a list of values and nothing is
summarised away that a chart would need.
"""
