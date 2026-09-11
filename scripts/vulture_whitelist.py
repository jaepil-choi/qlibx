"""Names vulture reports as unused that are not.

Vulture reads names, not call graphs, so three shapes always misfire: a method the
interpreter or a framework calls by protocol, a class a registry resolves from a string,
and a dataclass field that is written at construction and read only by serialization.
Everything below is one of those three, with the caller named. Anything vulture reports
that is NOT in this file is a real finding and belongs in a deletion decision, not here.

Callers are named by symbol rather than by line number on purpose. The first version of
this file cited lines, and record 124's deletion moved or removed every one of them within
a day; a whitelist whose comments rot is worse than one that makes the reader grep.

Run:  uv run vulture
"""

# --- Protocol and framework call sites ------------------------------------------------
# Python itself calls this on a failed module attribute lookup.
__getattr__  # src/vqapr/__init__.py

# argparse calls its own `_print_message`; `_Parser` overrides it to write UTF-8 bytes so
# `--help` survives a cp949 console. Record 047.
_._print_message  # src/vqapr/cli/main.py


# --- Resolved from a string, invisible to a name-based pass ---------------------------
# `src/vqapr/agent/sample/materialize.py` writes the literal "SampleExchange" into the
# declaration it materializes, and the loader resolves the class from that string
# (record 172 moved the sample into the package).
SampleExchange  # src/vqapr/agent/sample/exchange.py


# --- Frozen dataclass fields: written at construction, read by serialization ----------
# src/vqapr/run/engine/failure.py, class FailureObservation
exception_type
arguments

# src/vqapr/run/engine/evidence.py, class AccountCommitEvidence
planning_nav
planning_cash_target
planning_budget
intended_targets
requested_orders
account_version_before
account_version_committed

# src/vqapr/run/engine/evidence.py, class MarkEvidence
limitations

# src/vqapr/run/engine/context.py, class DueExecutionResult; built in `_execute_due`.
post_account_result


# --- pytest injects these by name, so no call site exists to find ---------------------
# Collection-time marker list applied to a whole module.
pytestmark

# `@pytest.fixture` definitions are covered by `ignore_decorators` in pyproject, but a test
# requesting one names it as a parameter, and that parameter has no reader in the body.
bound_every_source  # tests/run/test_hot_path_costs.py

# --- pydantic fields the model reads and drops, or a test model reads only by key ------
# `WorkspaceDocument` admits the four sections records 144 and 148 retired so a 0.3.0 document
# opens; nothing reads their value, by design. (`agendas` shares its name with a live module
# and so never shows up.)
_.valuation_configs  # src/vqapr/workspace_document.py
_.monitoring_policies  # src/vqapr/workspace_document.py
_.strategy_configs  # src/vqapr/workspace_document.py
# The run record's identity field: set by `freeze_run_record`, read back BY KEY from the dumped
# `run.json` in `_write_run_json`, where a second run under the same id is compared against it.
_.declared_digest  # src/vqapr/record/schema.py
# The same test's closed-set enum: pydantic matches a payload's string against the MEMBERS,
# and the test asserts the refusal lists them (`"strategy_callback, valuation"`), so both
# are load-bearing and neither is ever named in code.
STRATEGY_CALLBACK  # tests/test_a_validation_error_is_a_refusal.py, class Role
VALUATION  # tests/test_a_validation_error_is_a_refusal.py, class Role
# The adapter test's throwaway model: pydantic reads its fields from a payload by key.
_.when  # tests/test_a_validation_error_is_a_refusal.py
