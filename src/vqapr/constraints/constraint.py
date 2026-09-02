"""The Constraint extension contract -- one class, defined where an author reads it.

**This module used to define a second `Constraint` and a second `ConstraintBounds`**, parallel to
the ones in `vqapr.authoring` and incompatible with them: `project(window, instruments)` against
`project(call)`, `validate_intended(intent, bounds)` against `validate(decision, bounds)`,
`lower`/`upper` against `lower_weights`/`upper_weights`. Three extension points were each defined
twice and the loader accepted the authoring spelling for exactly one of them, so an author who
generalised from the Strategy scaffold to a Constraint was refused by the package that had just
emitted the import they copied (`docs/issues/036`; R5 and R6 of the post-Step-07 review).

There is now one definition and it lives in `vqapr.authoring`, because that is the module an
author is told to import. This file re-exports it so that every internal path -- `evaluation.py`,
`extension/loading.py`, `testing/conformance`, `flow/simulation.py` -- keeps naming the layer it
belongs to while naming the same object. `vqapr.public.Constraint is vqapr.authoring.Constraint`
is now true, and a test asserts it.
"""

from __future__ import annotations

from vqapr.authoring import Constraint, ConstraintBounds, ConstraintCall, EconomicAccountView

__all__ = ("Constraint", "ConstraintBounds", "ConstraintCall", "EconomicAccountView")
