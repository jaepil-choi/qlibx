"""Registry of bundled example strategies.

Examples and templates share a single on-disk location:
``echolon/native/templates/`` (package-internal so pip-installed users
get them too). The ``echolon examples`` and ``echolon init`` CLIs both
read from there.

Names exposed to the ``examples`` CLI are the unprefixed canonical names
(``minimal`` / ``momentum_breakout`` / ``rsi_mean_reversion``) — same as
``AVAILABLE_TEMPLATES`` in ``echolon.native.templates``.
"""

from pathlib import Path

from echolon.native.templates import AVAILABLE_TEMPLATES, template_path


# Re-export the templates' names verbatim — examples and templates are now
# the same set, served via two CLI surfaces (``examples copy`` and
# ``init --template``).
AVAILABLE_EXAMPLES = AVAILABLE_TEMPLATES


def example_path(name: str) -> Path:
    """Return the on-disk path for a known example. Raises on unknown."""
    if name not in AVAILABLE_EXAMPLES:
        raise KeyError(f"Unknown example: {name}. Available: {AVAILABLE_EXAMPLES}")
    return template_path(name)
