"""
Component Output Type Definitions

This module defines the required output formats for each strategy component
to ensure compatibility with the strategy logger interface.

Components must instantiate these Pydantic BaseModel classes which provide:
- Automatic validation at creation time (catches errors immediately)
- Type coercion and constraint enforcement
- Self-documenting field requirements
- Prevention of typos and missing fields

DESIGN PRINCIPLE:
- BaseModel definitions contain ONLY universal coordination fields (stable across strategies)
- Strategy-specific diagnostic fields (indicators, regimes, etc.) are allowed via extra='allow'
- This enables strategy evolution without modifying BaseModel definitions
"""

from typing import Dict, List, Union, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
import json
import os
import math

# Import OrderIntent for strategy coordination
from echolon.strategy.interfaces import OrderIntent
from echolon.errors import raise_error


# Valid signal enum values shared by EntrySignalOutput and ExitSignalOutput.
# Kept module-level so both schemas reference the same set (VAL-002).
VALID_SIGNALS = {"LONG", "SHORT", "HOLD"}


class EntrySignalOutput(BaseModel):
    """
    Required output format for entry_rule component.

    UNIVERSAL FIELDS (Required):
    - signal: Must be 'LONG', 'SHORT', or 'HOLD'
    - strength: Must be between 0.0 and 1.0 (inclusive)
    - type: Non-empty string (e.g., 'entry_long', 'entry_short', 'hold')
    - entry_reason: Non-empty human-readable reason for the signal
    - intent: OrderIntent for strategy coordination (ENTRY_LONG, ENTRY_SHORT, or None for HOLD)

    OPTIONAL CONTEXT FIELDS:
    - regime: Optional paradigm-specific context label. TRS strategies populate
      with a regime label (trending_up / ranging / volatile / trending_down).
      TSMOM and other paradigms typically leave this None.

    STRATEGY-SPECIFIC FIELDS (Optional via extra='allow'):
    Components can add diagnostic fields like indicator values, etc.

    Example (TRS strategy populating regime):
        >>> output = EntrySignalOutput(
        ...     signal='LONG',
        ...     strength=0.85,
        ...     type='entry_long',
        ...     entry_reason='TEMA crossover + trending regime',
        ...     intent=OrderIntent.ENTRY_LONG,
        ...     regime='trending_up',
        ...     # Strategy-specific extras (allowed!)
        ...     tema_short=4580.2
        ... )

    Example (TSMOM strategy omitting regime):
        >>> output = EntrySignalOutput(
        ...     signal='LONG',
        ...     strength=0.92,
        ...     type='entry_long',
        ...     entry_reason='momentum signal positive',
        ...     intent=OrderIntent.ENTRY_LONG,
        ...     # regime omitted — TSMOM is regime-blind
        ... )
    """
    signal: Literal['LONG', 'SHORT', 'HOLD'] = Field(
        ...,
        description="Entry signal direction"
    )
    strength: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Signal strength (0.0-1.0)"
    )
    type: str = Field(
        ...,
        min_length=1,
        description="Signal type (e.g., 'entry_long', 'entry_short', 'hold')"
    )
    entry_reason: str = Field(
        ...,
        min_length=1,
        description="Human-readable reason for the signal"
    )
    intent: Optional[OrderIntent] = Field(
        default=None,
        description="Order intent for strategy execution (ENTRY_LONG, ENTRY_SHORT, or None for HOLD)"
    )
    regime: Optional[str] = Field(
        default=None,
        description=(
            "Optional paradigm-specific context label at signal time. TRS "
            "strategies populate with a regime label (trending_up / ranging / "
            "volatile / trending_down) or session phase (intraday). TSMOM and "
            "other paradigms typically leave this None. Free-form string — "
            "echolon does not enumerate values."
        )
    )

    @field_validator("signal", mode="before")
    @classmethod
    def _validate_signal_enum(cls, v):
        """Raise VAL-002 on unknown signal values before Pydantic's Literal check.

        Running ``mode='before'`` means this hook fires first; Pydantic's own
        Literal-validator never sees invalid values, so the LLM author gets a
        catalog-coded error instead of a generic ``pydantic.ValidationError``.
        """
        if v not in VALID_SIGNALS:
            raise_error(
                "VAL-002",
                file="EntrySignalOutput",
                method="<signal field>",
                got=repr(v),
            )
        return v

    @model_validator(mode="before")
    @classmethod
    def _check_required_fields(cls, values):
        """Raise VAL-001 listing any missing required fields.

        Runs before Pydantic's own per-field validation so LLM authors get a
        catalog-coded error enumerating all missing fields at once, rather than
        Pydantic's generic one-error-per-field output.
        """
        if not isinstance(values, dict):
            return values
        required = {
            name for name, f in cls.model_fields.items()
            if f.is_required()
        }
        missing = [f for f in required if f not in values]
        if missing:
            raise_error(
                "VAL-001",
                file=cls.__name__,
                method="__init__",
                missing=", ".join(sorted(missing)),
            )
        return values

    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)


class ExitSignalOutput(BaseModel):
    """
    Required output format for exit_rule component.

    UNIVERSAL FIELDS (Required):
    - should_exit: Boolean indicating if exit should occur
    - exit_reason: Non-empty human-readable reason for exit decision
    - position_size: Must be >= 0
    - bars_since_entry: Must be >= 0
    - intent: OrderIntent for strategy coordination (EXIT_LONG, EXIT_SHORT, or None if no exit)

    STRATEGY-SPECIFIC FIELDS (Optional via extra='allow'):
    Components can add diagnostic fields like stop_price, atr_distance, etc.

    Example:
        >>> output = ExitSignalOutput(
        ...     should_exit=True,
        ...     exit_reason='Trailing stop hit at 3900.5',
        ...     position_size=10.0,
        ...     bars_since_entry=15,
        ...     intent=OrderIntent.EXIT_LONG,
        ...     # Strategy-specific extras (allowed!)
        ...     stop_price=3900.5,
        ...     atr_distance=2.5
        ... )
    """
    should_exit: bool = Field(
        ...,
        description="Whether to exit position"
    )
    exit_reason: str = Field(
        ...,
        min_length=1,
        description="Human-readable reason for exit decision"
    )
    position_size: float = Field(
        ...,
        ge=0.0,
        description="Current position size (must be non-negative)"
    )
    bars_since_entry: int = Field(
        ...,
        ge=0,
        description="Number of bars since entry (must be non-negative)"
    )
    intent: Optional[OrderIntent] = Field(
        default=None,
        description="Order intent for strategy execution (EXIT_LONG, EXIT_SHORT, or None if no exit)"
    )
    signal: Optional[Literal['LONG', 'SHORT', 'HOLD']] = Field(
        default=None,
        description=(
            "Optional signal direction that produced this exit decision. "
            "Must be 'LONG', 'SHORT', or 'HOLD' when provided."
        )
    )

    @field_validator("signal", mode="before")
    @classmethod
    def _validate_signal_enum(cls, v):
        """Raise VAL-002 on unknown signal values before Pydantic's Literal check.

        Mirror of the ``EntrySignalOutput`` validator so both schemas produce a
        catalog-coded error when an LLM author returns lowercase ``'long'``.
        """
        if v is None:
            return v
        if v not in VALID_SIGNALS:
            raise_error(
                "VAL-002",
                file="ExitSignalOutput",
                method="<signal field>",
                got=repr(v),
            )
        return v

    @model_validator(mode="before")
    @classmethod
    def _check_required_fields(cls, values):
        """Raise VAL-001 listing any missing required fields.

        Mirror of the ``EntrySignalOutput`` validator so both schemas deliver
        catalog-coded missing-field errors to LLM authors.
        """
        if not isinstance(values, dict):
            return values
        required = {
            name for name, f in cls.model_fields.items()
            if f.is_required()
        }
        missing = [f for f in required if f not in values]
        if missing:
            raise_error(
                "VAL-001",
                file=cls.__name__,
                method="__init__",
                missing=", ".join(sorted(missing)),
            )
        return values

    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)


class SizerOutput(BaseModel):
    """
    Required output format for position_sizer component.

    UNIVERSAL FIELDS (Required):
    - calculated_size: Must be non-negative integer (whole contracts)
    - signal_direction: Must be 'LONG', 'SHORT', or 'HOLD'
    - sizing_reason: Non-empty human-readable reason for sizing decision
    - raw_size: Raw calculated size before floor/validation (float, for analysis)

    STRATEGY-SPECIFIC FIELDS (Optional via extra='allow'):
    Components can add diagnostic fields like volatility_factor, equity_curve_factor, etc.

    Example:
        >>> output = SizerOutput(
        ...     calculated_size=10,
        ...     signal_direction='LONG',
        ...     sizing_reason='Size: 10 contracts (raw: 10.8)',
        ...     raw_size=10.8,
        ...     # Strategy-specific extras (allowed!)
        ...     volatility_factor=0.85,
        ...     equity_curve_factor=1.2
        ... )
    """
    calculated_size: int = Field(
        ...,
        ge=0,
        description="Calculated position size in whole contracts (must be non-negative integer)"
    )
    signal_direction: Literal['LONG', 'SHORT', 'HOLD'] = Field(
        ...,
        description="Direction of position"
    )
    sizing_reason: str = Field(
        ...,
        min_length=1,
        description="Human-readable reason for sizing decision"
    )
    raw_size: float = Field(
        ...,
        ge=0.0,
        description="Raw calculated position size before floor/validation (for analysis and debugging)"
    )

    model_config = ConfigDict(extra="allow")  # Allow strategy-specific diagnostic fields


class RiskOutput(BaseModel):
    """
    Required output format for risk_manager component.

    UNIVERSAL FIELDS (Required):
    - trading_allowed: Boolean indicating if trading is allowed
    - risk_reason: Non-empty human-readable reason for risk decision

    STRATEGY-SPECIFIC FIELDS (Optional via extra='allow'):
    Components can add diagnostic fields like drawdown_pct, consecutive_losses, etc.

    Example:
        >>> output = RiskOutput(
        ...     trading_allowed=False,
        ...     risk_reason='Daily loss limit exceeded (-5.2%)',
        ...     # Strategy-specific extras (allowed!)
        ...     drawdown_pct=-5.2,
        ...     consecutive_losses=3
        ... )
    """
    trading_allowed: bool = Field(
        ...,
        description="Whether trading is allowed"
    )
    risk_reason: str = Field(
        ...,
        min_length=1,
        description="Human-readable reason for risk decision"
    )

    model_config = ConfigDict(extra="allow")  # Allow strategy-specific diagnostic fields


# ============================================================================
# Position Size Type Validation
# ============================================================================

def validate_position_size(size: Union[int, float], component_name: str = "position_sizer") -> int:
    """
    Validate and convert position size to non-negative integer.

    Position sizing components MUST return non-negative integers representing
    the number of contracts to trade. This function enforces that contract.

    Parameters
    ----------
    size : Union[int, float]
        Position size value to validate (can be int or float)
    component_name : str
        Name of component for error messages (default: "position_sizer")

    Returns
    -------
    int
        Validated non-negative integer position size

    Raises
    ------
    TypeError
        If size is not numeric (int or float)
    ValueError
        If size is negative, NaN, or infinite

    Examples
    --------
    >>> validate_position_size(10)
    10
    >>> validate_position_size(10.7)  # Floors to integer
    10
    >>> validate_position_size(0)
    0
    >>> validate_position_size(-5)  # Raises ValueError
    ValueError: position_sizer returned negative size: -5
    >>> validate_position_size(float('nan'))  # Raises ValueError
    ValueError: position_sizer returned invalid size (NaN)
    """
    # Type validation
    if not isinstance(size, (int, float)):
        raise TypeError(
            f"{component_name} must return numeric type (int or float), "
            f"got {type(size).__name__}: {size}"
        )

    # Check for NaN
    if math.isnan(size):
        raise ValueError(f"{component_name} returned invalid size (NaN)")

    # Check for infinity
    if math.isinf(size):
        raise ValueError(f"{component_name} returned invalid size (infinite): {size}")

    # Check for negative
    if size < 0:
        raise ValueError(f"{component_name} returned negative size: {size}")

    # Convert to integer (floor)
    validated_size = int(math.floor(size))

    # Final sanity check
    if validated_size < 0:
        raise ValueError(
            f"{component_name} size became negative after conversion: {size} -> {validated_size}"
        )

    return validated_size


from echolon.indicators.schema import IndicatorList


def validate_indicator_list_json(file_path: str) -> tuple[bool, str, IndicatorList]:
    """
    Validate strategy_indicator_list.json file format using Pydantic.

    Args:
        file_path: Path to strategy_indicator_list.json file

    Returns:
        Tuple of (is_valid, error_message, parsed_model)
        - is_valid: True if valid, False otherwise
        - error_message: Empty string if valid, detailed error message if invalid
        - parsed_model: IndicatorList instance if valid, None if invalid

    Example:
        >>> is_valid, error, model = validate_indicator_list_json("strategy_indicator_list.json")
        >>> if not is_valid:
        >>>     print(f"Validation failed: {error}")
        >>> else:
        >>>     print(f"Valid! Found {len(model.root)} indicators")
    """
    # Check file exists
    if not os.path.exists(file_path):
        return False, f"File not found: {file_path}", None

    # Load JSON
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Validate with Pydantic
    validated_model = IndicatorList(**data)
    return True, "", validated_model


__all__ = [
    'EntrySignalOutput',
    'ExitSignalOutput',
    'SizerOutput',
    'RiskOutput',
    'validate_position_size',
    'IndicatorList',
    'validate_indicator_list_json',
]
