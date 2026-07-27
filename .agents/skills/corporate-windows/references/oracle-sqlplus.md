# Oracle and SQLPlus safety

Every database connection or query requires query-specific user approval, including ping queries.

Before execution:

1. Show the exact final SQL or the complete query content of the SQL file.
2. Explain briefly why the query is bounded and safe, or why it could burden the server.
3. Wait for explicit approval for that exact SQL.
4. Record the approved SQL and its purpose in the active experiment or task evidence.

Prefer Oracle dictionary and statistics metadata before scanning large application tables. Treat
statistics as approximate or stale and label their source.

If table access is necessary, start with required columns, explicit date or identifier filters,
and a small row limit. Avoid unbounded counts, aggregates, row-wise functions, joins, sorts,
grouping, or window operations on large tables.

On `ORA-00028`, `ORA-00604`, `ORA-20000`, IP blocking, or session termination, stop all further
database access and report the last SQL and failure. Approval for one query never authorizes another.
