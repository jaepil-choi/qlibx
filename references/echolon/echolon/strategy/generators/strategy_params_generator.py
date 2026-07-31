"""
Strategy Parameters Generator - Self-Contained Deterministic Code Generation

This utility generates complete strategy_params.py from params_to_optimize.md
using 100% deterministic Python code generation (no LLM inference).

Architecture:
1. Read and parse params_to_optimize.md (JSON structure)
2. Determine parameter ownership using hardcoded rules
3. Generate Python code for each component's ComponentParameterTemplate class
4. Generate framework registration code
5. Generate optuna_search_space function with crossover constraints
6. Write complete strategy_params.py file

Benefits:
- 100% deterministic (same input → same output)
- No duplicate calculation parameters (enforced by ownership rules)
- Automatic crossover constraint detection
- Self-contained (no external parser dependency)
- Easier to debug and maintain than LLM prompts
"""

import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from echolon.config.indicator_config import IndicatorConfig


@dataclass
class ParameterInfo:
    """Information about a parameter"""
    name: str
    param_type: str
    range_or_value: List | any
    default: any
    description: str
    is_calculation: bool  # True = calculation param, False = usage param
    is_fixed: bool  # True = fixed value, False = optimizable
    owner_component: str  # Component that owns this parameter
    shared_with: List[str]  # Components that share this parameter
    owner_param_name: str = None  # Owner's parameter name if different from self.name (cross-name sharing)


class StrategyParamsGenerator:
    """
    Self-contained generator for strategy_params.py

    Parses params_to_optimize.md and generates complete Python code with:
    - Component parameter classes
    - Framework initialization
    - Optuna search space with constraints
    """

    # Component sequence for ownership determination
    # 'sizer' (not 'sizing') to match parameter_architecture.py framework
    COMPONENT_SEQUENCE = ['entry', 'exit', 'risk', 'sizer']

    def __init__(
        self,
        params_file_path: str = None,
        frequency: str = "interday",
        indicator_config: Optional[IndicatorConfig] = None,
        workspace_dir: Optional[Path] = None,
    ):
        """
        Initialize generator.

        Args:
            params_file_path: Path to params_to_optimize.json.
                            If None, uses default location.
            frequency: Trading frequency - "interday" (daily bars) or "intraday" (sub-daily bars).
                      Affects which period caps are used.
            indicator_config: Optional IndicatorConfig with custom period caps.
                              When None, defaults are used.
            workspace_dir: Optional injected workspace directory (used only when
                          ``params_file_path`` is None to locate the default
                          ``current/strategy/params_to_optimize.json``).
        """
        if params_file_path is None:
            if workspace_dir is None:
                from echolon.config.paths_config import PathsConfig
                workspace_dir = PathsConfig.from_env().workspace_dir
            params_file_path = Path(workspace_dir) / 'current' / 'strategy' / 'params_to_optimize.json'

        self.params_file_path = Path(params_file_path)
        self.frequency = frequency
        self.components = self.COMPONENT_SEQUENCE

        # Select period caps based on frequency
        # Interday: periods are in days (186 daily bars)
        # Intraday: periods are in bars (~4000+ bars for 186 days)
        self.indicator_config = indicator_config or IndicatorConfig()
        self.period_caps = (
            self.indicator_config.intraday_caps if frequency == "intraday"
            else self.indicator_config.interday_caps
        )

        # Track auto-corrections for agent reporting
        self.auto_corrections = []

        # Parse parameter structure
        self.raw_structure = self._load_structure()

        # Build cross-name shared parameter mapping from extraction_report
        self.shared_param_mapping = self._build_shared_param_mapping()

        self.parsed_parameters = self._parse_all_parameters()

    def _load_structure(self) -> Dict:
        """Load and parse JSON structure from params_to_optimize.json"""
        with open(self.params_file_path, 'r') as f:
            return json.load(f)

    def _build_shared_param_mapping(self) -> Dict[str, Dict[str, str]]:
        """
        Build a mapping of cross-name shared parameters from extraction_report.shared_parameters.

        Parses entries like:
            {"param": "exit_atr_period → sizer_atr_period", "owner": "exit", "shared_by": ["sizing"]}

        Returns:
            Dict mapping consumer_param_name to {
                'owner_param_name': str,
                'owner_component': str
            }

        Example return:
            {
                'sizer_atr_period': {
                    'owner_param_name': 'exit_atr_period',
                    'owner_component': 'exit'
                }
            }
        """
        mapping = {}
        extraction_report = self.raw_structure.get('extraction_report', {})
        shared_parameters = extraction_report.get('shared_parameters', [])

        component_map = {
            'entry': 'entry',
            'exit': 'exit',
            'risk': 'risk',
            'sizer': 'sizer',
            'sizing': 'sizer'
        }

        for entry in shared_parameters:
            param_str = entry.get('param', '')
            owner = entry.get('owner', '')
            owner = component_map.get(owner, owner)

            # Parse cross-name shared parameter formats:
            # Format 1: "owner_param → consumer_param" (arrow separator)
            # Format 2: "owner_param / consumer_param" (slash separator)
            separator = None
            if '→' in param_str:
                separator = '→'
            elif '/' in param_str:
                separator = '/'

            if separator:
                parts = param_str.split(separator)
                owner_param = parts[0].strip()
                consumer_param = parts[1].strip()
                mapping[consumer_param] = {
                    'owner_param_name': owner_param,
                    'owner_component': owner
                }

        return mapping

    def _extract_shared_components(self, description: str) -> List[str]:
        """
        Extract component sharing info from description.

        Examples:
            "SHARED by Entry, Exit, Risk, Sizing" → ['entry', 'exit', 'risk', 'sizer']
            "SHARED by Exit, Risk, Sizing" → ['exit', 'risk', 'sizer']
            "Normal parameter" → []
        """
        if 'SHARED by' not in description:
            return []

        # Extract the part after "SHARED by"
        shared_part = description.split('SHARED by')[1].strip()

        # Parse component names (case-insensitive)
        components = []
        component_map = {
            'entry': 'entry',
            'exit': 'exit',
            'risk': 'risk',
            'sizer': 'sizer',
            'sizing': 'sizer'  # Alias (params_to_optimize.md uses 'Sizing')
        }

        for word in shared_part.replace(',', ' ').split():
            word_lower = word.lower()
            if word_lower in component_map:
                comp = component_map[word_lower]
                if comp not in components:
                    components.append(comp)

        return components

    def _determine_owner(self, shared_with: List[str]) -> str:
        """
        Determine owner component based on sequence priority.

        Owner = First component in COMPONENT_SEQUENCE that uses the parameter.

        Args:
            shared_with: List of components that use this parameter

        Returns:
            Owner component name
        """
        for component in self.COMPONENT_SEQUENCE:
            if component in shared_with:
                return component

        # Should never reach here if shared_with is valid
        raise ValueError(f"No valid component found in shared_with: {shared_with}")

    def _get_indicator_cap(self, param_name: str) -> int:
        """
        Get the maximum allowed period for an indicator parameter.

        Uses frequency-aware caps (interday vs intraday).

        Args:
            param_name: Parameter name (e.g., 'tema_short_period', 'adx_period')

        Returns:
            Maximum allowed period value
        """
        # Extract indicator name from parameter name
        # Examples: tema_short_period → tema, adx_period → adx, rsi_period → rsi
        param_lower = param_name.lower()

        for indicator, cap in self.period_caps.items():
            if indicator == 'default':
                continue
            # Check if parameter name starts with indicator name
            if param_lower.startswith(f"{indicator}_"):
                return cap

        return self.period_caps['default']

    def _validate_and_clamp_period_cap(self, param: ParameterInfo) -> ParameterInfo:
        """
        Validate and auto-clamp period parameters to respect indicator-specific caps.

        For automated workflow: Instead of raising errors, automatically clamp to max cap.
        Logs corrections and tracks them for agent reporting.

        Args:
            param: ParameterInfo to validate

        Returns:
            ParameterInfo with clamped values (if needed)
        """
        # Only process calculation parameters ending with _period
        if not param.is_calculation or not param.name.endswith('_period'):
            return param

        cap = self._get_indicator_cap(param.name)

        # Determine indicator category for logging
        if cap == 62:
            category = "TEMA/TRIX/ADXR"
        elif cap == 93:
            category = "ADX/DEMA"
        else:
            category = "Standard"

        if param.is_fixed:
            # Clamp fixed period values
            if isinstance(param.default, (int, float)) and param.default > cap:
                old_value = param.default
                param.default = cap
                param.range_or_value = cap

                correction = {
                    'param': param.name,
                    'type': 'fixed_value',
                    'old_value': old_value,
                    'new_value': cap,
                    'cap': cap,
                    'category': category
                }
                self.auto_corrections.append(correction)

                print(f"⚠️  AUTO-CORRECTED: {param.name}")
                print(f"    Fixed value: {old_value} → {cap}")
                print(f"    Reason: {category} indicator cap is {cap}")
                print()
            return param

        # Clamp range values
        if not isinstance(param.range_or_value, list) or len(param.range_or_value) < 2:
            return param

        original_min = param.range_or_value[0]
        original_max = param.range_or_value[1]
        min_value = original_min
        max_value = original_max
        original_default = param.default
        corrections_made = []

        # Clamp max_value to cap
        if max_value > cap:
            max_value = cap
            corrections_made.append(f"max_value: {original_max} → {cap}")

        # Ensure min_value < max_value (with reasonable gap)
        if min_value >= max_value:
            # When both values are equal, keep original as min and set reasonable max
            # Set max_value to reasonable default: min(original_value * 5, cap)
            # But if max_value was already clamped to cap, use that
            if max_value == cap:
                # max was already clamped, so keep it
                # Set min to reasonable value below cap
                new_min = max(10, min(original_min, cap // 3))
                corrections_made.append(f"min_value: {min_value} → {new_min} (must be < max)")
                min_value = new_min
            else:
                # Both values are equal and below cap
                # Keep the equal value as min, extend range to reasonable max
                new_max = min(original_min * 5, cap)
                corrections_made.append(f"max_value: {max_value} → {new_max} (extend range)")
                max_value = new_max

        if corrections_made:
            param.range_or_value = [min_value, max_value]

            # Also clamp default if it's outside the new range
            if param.default < min_value:
                corrections_made.append(f"default: {original_default} → {min_value}")
                param.default = min_value
            elif param.default > max_value:
                corrections_made.append(f"default: {original_default} → {max_value}")
                param.default = max_value

            # Record correction
            correction = {
                'param': param.name,
                'type': 'range',
                'old_range': [original_min, original_max],
                'new_range': [min_value, max_value],
                'old_default': original_default,
                'new_default': param.default,
                'cap': cap,
                'category': category,
                'changes': corrections_made
            }
            self.auto_corrections.append(correction)

            print(f"⚠️  AUTO-CORRECTED: {param.name}")
            print(f"    Original range: [{original_min}, {original_max}], default: {original_default}")
            print(f"    Corrected range: [{min_value}, {max_value}], default: {param.default}")
            print(f"    Reason: {category} indicator cap is {cap}")
            print()

        return param

    def _parse_component_parameters(
        self,
        component_name: str,
        component_data: Dict
    ) -> List[ParameterInfo]:
        """Parse parameters for a single component"""
        parameters = []

        # Build set of explicitly fixed parameter names to avoid duplicates
        # When a param appears in both 'calculation' (with range for reference) and 'fixed'
        # (with explicit value), the 'fixed' section takes precedence
        fixed_param_names = set(component_data.get('fixed', {}).keys())

        # Parse calculation parameters (Tier 1 indicators only)
        for param_name, param_spec in component_data.get('calculation', {}).items():
            # Skip if this param is explicitly declared in 'fixed' section
            # (fixed section will handle it below with the correct FIXED type)
            if param_name in fixed_param_names:
                continue
            # Check for explicit ownership attribute (new JSON format)
            ownership = param_spec.get('ownership', 'owner')
            is_shared = (ownership == 'shared')

            owner_param_name = None
            if is_shared:
                # Check cross-name mapping first
                cross_name_info = self.shared_param_mapping.get(param_name)
                if cross_name_info:
                    owner = cross_name_info['owner_component']
                    owner_param_name = cross_name_info['owner_param_name']
                else:
                    owner = self._find_owner_component(param_name)
                shared_components = [owner, component_name] if owner != component_name else [component_name]
            else:
                # Fall back to parsing "SHARED by ..." from the description text.
                shared_components = self._extract_shared_components(param_spec['description'])
                if shared_components:
                    owner = self._determine_owner(shared_components)
                else:
                    owner = component_name
                    shared_components = [component_name]

            # Detect FIXED calculation params: range [X, X] means min == max → fixed
            param_range = param_spec.get('range')
            is_fixed_calc = False
            if param_range and len(param_range) >= 2 and param_range[0] == param_range[1]:
                is_fixed_calc = True

            param_info = ParameterInfo(
                name=param_name,
                param_type=param_spec['type'],
                range_or_value=param_spec.get('default') if is_fixed_calc else param_range,
                default=param_spec.get('default'),
                description=param_spec['description'],
                is_calculation=True,
                is_fixed=is_fixed_calc,
                owner_component=owner,
                shared_with=shared_components,
                owner_param_name=owner_param_name
            )

            # Validate and auto-clamp period caps
            param_info = self._validate_and_clamp_period_cap(param_info)

            parameters.append(param_info)

        # Parse usage parameters
        for param_name, param_spec in component_data.get('usage', {}).items():
            # Check for explicit ownership attribute (new JSON format)
            ownership = param_spec.get('ownership', 'owner')
            is_shared = (ownership == 'shared')

            owner_param_name = None
            if is_shared:
                # Check cross-name mapping first
                cross_name_info = self.shared_param_mapping.get(param_name)
                if cross_name_info:
                    owner = cross_name_info['owner_component']
                    owner_param_name = cross_name_info['owner_param_name']
                else:
                    owner = self._find_owner_component(param_name)
                shared_components = [owner, component_name] if owner != component_name else [component_name]
            else:
                owner = component_name
                shared_components = [component_name]

            param_info = ParameterInfo(
                name=param_name,
                param_type=param_spec['type'],
                range_or_value=param_spec.get('range'),
                default=param_spec.get('default'),
                description=param_spec['description'],
                is_calculation=False,
                is_fixed=False,
                owner_component=owner,
                shared_with=shared_components,
                owner_param_name=owner_param_name
            )
            parameters.append(param_info)

        # Parse fixed parameters
        for param_name, param_spec in component_data.get('fixed', {}).items():
            # Check for explicit ownership attribute
            ownership = param_spec.get('ownership', 'owner')
            is_shared = (ownership == 'shared')

            # Resolve cross-name mapping for shared parameters
            owner_param_name = None
            if is_shared:
                # Check cross-name mapping first (e.g., sizer_atr_period → exit_atr_period)
                cross_name_info = self.shared_param_mapping.get(param_name)
                if cross_name_info:
                    owner = cross_name_info['owner_component']
                    owner_param_name = cross_name_info['owner_param_name']
                else:
                    owner = self._find_owner_component(param_name)
                shared_components = [owner, component_name] if owner != component_name else [component_name]
            else:
                owner = component_name
                shared_components = [component_name]

            param_info = ParameterInfo(
                name=param_name,
                param_type=param_spec['type'],
                range_or_value=param_spec.get('value'),
                default=param_spec.get('value'),
                description=param_spec['description'],
                is_calculation=False,
                is_fixed=True,
                owner_component=owner,
                shared_with=shared_components,
                owner_param_name=owner_param_name
            )

            # Validate and auto-clamp period caps if this is a fixed period parameter
            if param_name.endswith('_period'):
                param_info = self._validate_and_clamp_period_cap(param_info)

            parameters.append(param_info)

        return parameters

    def _find_owner_component(self, param_name: str) -> str:
        """
        Find the owner component for a shared parameter by checking which
        component has it defined with ownership='owner'.

        Args:
            param_name: Name of the parameter to find owner for

        Returns:
            Component name that owns this parameter
        """
        component_map = {
            'entry_parameters': 'entry',
            'exit_parameters': 'exit',
            'risk_parameters': 'risk',
            'sizing_parameters': 'sizer'
        }

        # Search in component sequence order (Entry → Exit → Risk → Sizer)
        for param_key in ['entry_parameters', 'exit_parameters', 'risk_parameters', 'sizing_parameters']:
            component_name = component_map[param_key]
            component_data = self.raw_structure.get(param_key, {})

            # Check all sections (calculation, usage, fixed)
            for section in ['calculation', 'usage', 'fixed']:
                section_data = component_data.get(section, {})
                if param_name in section_data:
                    param_spec = section_data[param_name]
                    ownership = param_spec.get('ownership', 'owner')
                    if ownership == 'owner':
                        return component_name

        # If not found, return first component in sequence that has it
        for param_key in ['entry_parameters', 'exit_parameters', 'risk_parameters', 'sizing_parameters']:
            component_name = component_map[param_key]
            component_data = self.raw_structure.get(param_key, {})
            for section in ['calculation', 'usage', 'fixed']:
                if param_name in component_data.get(section, {}):
                    return component_name

        # Default to exit (common owner for ATR-based params)
        return 'exit'

    def _parse_all_parameters(self) -> Dict[str, List[ParameterInfo]]:
        """
        Parse all parameters from structure.

        Returns:
            Dict mapping component name to list of ParameterInfo objects
            that component uses (both owned and shared)
        """
        all_params = {
            'entry': [],
            'exit': [],
            'risk': [],
            'sizer': []
        }

        # Parse each component
        # Note: params_to_optimize.json uses 'sizing_parameters' but framework uses 'sizer'
        component_map = {
            'entry_parameters': 'entry',
            'exit_parameters': 'exit',
            'risk_parameters': 'risk',
            'sizing_parameters': 'sizer'  # Map 'sizing_parameters' → 'sizer'
        }

        for param_key, component_name in component_map.items():
            component_data = self.raw_structure.get(param_key, {})
            params = self._parse_component_parameters(component_name, component_data)

            # Include ALL parameters for this component (both owned and shared)
            # The ownership attribute determines whether it's optimized or copied
            for param in params:
                all_params[component_name].append(param)

        return all_params

    def get_component_parameters(self, component: str) -> List[ParameterInfo]:
        """
        Get all parameters used by a component (both owned and shared).

        Args:
            component: Component name ('entry', 'exit', 'risk', 'sizer')

        Returns:
            List of ParameterInfo objects used by this component
        """
        return self.parsed_parameters.get(component, [])

    def _owner_has_optimizable(self, owner_component: str, param_name: str, owner_param_name: str = None) -> bool:
        """
        Check if the owner component has this parameter as optimizable (non-fixed).

        Used to determine if a shared fixed parameter should reference the owner's
        Optuna-suggested value instead of a hardcoded default.

        Args:
            owner_component: The component that owns this parameter
            param_name: The consumer parameter name to check
            owner_param_name: The owner's parameter name if different (cross-name sharing)

        Returns:
            True if owner has this parameter as non-fixed (optimizable)
        """
        # Use owner_param_name for cross-name lookups (e.g., sizer_atr_period → exit_atr_period)
        lookup_name = owner_param_name if owner_param_name else param_name
        for param in self.get_component_parameters(owner_component):
            if param.name == lookup_name and param.owner_component == owner_component:
                return not param.is_fixed
        return False

    def _generate_imports(self) -> str:
        """Generate import statements for the output strategy_params.py.

        Uses an absolute import from echolon so the generated file works
        regardless of where it lands on disk. (The old relative import
        `from ..parameter_architecture` only resolved when the file was inside
        a specific package layout that no longer exists.)
        """
        return '''"""
Strategy Parameters — generated from params_to_optimize.json by
echolon.strategy.generators.strategy_params_generator.

Manual edits are permitted — downstream tooling may patch this file to
fix bugs or adjust ranges. Note that any manual change WILL be overwritten
if the generator is re-run; for a change to persist across regeneration,
also update params_to_optimize.json (or the IndicatorConfig caps that
feed the generator).

To regenerate:
1. Edit your params_to_optimize.json source file.
2. Call echolon.strategy.generators.generate_strategy_params(
       params_file_path=..., output_path=..., frequency=...,
   )
   (or via the echolon-mcp `generate_strategy_params` tool)
3. Inspect the GenerationResult.corrections list for any auto-clamped ranges.
"""

from typing import List, Dict, Any
import optuna
from echolon.strategy.parameter_architecture import (
    ComponentParameterTemplate,
    ParameterSpec,
    ParameterType,
    StrategyParameterFramework,
)
'''

    def _generate_parameter_spec_code(self, param: ParameterInfo, component: str) -> str:
        """Generate ParameterSpec code for a single parameter"""

        # Add sharing info to description
        description = param.description
        if len(param.shared_with) > 1:
            other_components = [c for c in param.shared_with if c != component]
            if other_components:
                description = f"{description} [SHARED with: {', '.join(other_components)}]"

        # Escape quotes in description
        description = description.replace('"', '\\"')

        # Generate ParameterSpec code
        if param.is_fixed:
            return f'''        ParameterSpec(
            name="{param.name}",
            param_type=ParameterType.FIXED,
            default_value={repr(param.default)},
            description="{description}"
        )'''

        # Optimizable parameter
        type_map = {'int': 'INT', 'float': 'FLOAT', 'bool': 'BOOL', 'categorical': 'CATEGORICAL'}
        param_type = type_map.get(param.param_type.lower(), 'FLOAT')

        if param.param_type.lower() in ['int', 'float'] and param.range_or_value is not None:
            min_val, max_val = param.range_or_value[0], param.range_or_value[1]
            return f'''        ParameterSpec(
            name="{param.name}",
            param_type=ParameterType.{param_type},
            default_value={repr(param.default)},
            min_value={repr(min_val)},
            max_value={repr(max_val)},
            description="{description}"
        )'''
        else:
            return f'''        ParameterSpec(
            name="{param.name}",
            param_type=ParameterType.{param_type},
            default_value={repr(param.default)},
            description="{description}"
        )'''

    def _generate_component_class(self, component: str) -> str:
        """Generate ComponentParameterTemplate class for a component"""

        class_name = f"{component.capitalize()}Parameters"
        params = self.get_component_parameters(component)

        # Generate parameter specs
        param_specs = []
        for param in params:
            spec_code = self._generate_parameter_spec_code(param, component)
            param_specs.append(spec_code)

        params_list = ',\n'.join(param_specs)

        return f'''

class {class_name}(ComponentParameterTemplate):
    """Parameter definitions for {component} component"""

    def get_component_name(self) -> str:
        return '{component}'

    def define_parameters(self) -> List[ParameterSpec]:
        return [
{params_list}
        ]
'''

    def _detect_crossover_pairs(self) -> List[tuple]:
        """
        Detect crossover parameter pairs that need ordering constraints.

        Returns:
            List of (short_param, long_param, component, is_period) tuples
            where is_period indicates if these are period parameters (True) or other types (False)

        Detection patterns:
        - Parameters with '_short' and '_long' suffix
        - Parameters with '_fast' and '_slow' suffix
        - Only includes pairs where both params are optimizable (not fixed)
        """
        crossover_pairs = []

        for component in self.components:
            params = self.get_component_parameters(component)
            param_names = {p.name: p for p in params}

            # Check for short/long pairs
            for param_name in param_names.keys():
                if param_name.endswith('_short_period') or param_name.endswith('_short'):
                    # Find corresponding long parameter
                    base_name = param_name.replace('_short_period', '').replace('_short', '')
                    long_candidates = [
                        f"{base_name}_long_period",
                        f"{base_name}_long"
                    ]

                    for long_name in long_candidates:
                        if long_name in param_names:
                            # Check if both are optimizable (not fixed)
                            short_param = param_names[param_name]
                            long_param = param_names[long_name]
                            if not short_param.is_fixed and not long_param.is_fixed:
                                # Check if these are period parameters
                                is_period = param_name.endswith('_period') or param_name.endswith('_short_period')
                                crossover_pairs.append((param_name, long_name, component, is_period))
                            break

            # Check for fast/slow pairs
            for param_name in param_names.keys():
                if param_name.endswith('_fast_period') or param_name.endswith('_fast'):
                    base_name = param_name.replace('_fast_period', '').replace('_fast', '')
                    slow_candidates = [
                        f"{base_name}_slow_period",
                        f"{base_name}_slow"
                    ]

                    for slow_name in slow_candidates:
                        if slow_name in param_names:
                            # Check if both are optimizable (not fixed)
                            fast_param = param_names[param_name]
                            slow_param = param_names[slow_name]
                            if not fast_param.is_fixed and not slow_param.is_fixed:
                                # Check if these are period parameters
                                is_period = param_name.endswith('_period') or param_name.endswith('_fast_period')
                                crossover_pairs.append((param_name, slow_name, component, is_period))
                            break

        return crossover_pairs

    def _generate_optuna_search_space(self) -> str:
        """Generate optuna_search_space function with crossover constraints and shared parameter handling"""

        crossover_pairs = self._detect_crossover_pairs()

        # Track shared parameters and their owners for later reference
        # Include both non-fixed shared params AND fixed shared params with optimizable owner
        shared_params_info = {}  # {(component, param_name): owner_component}
        for component in self.components:
            for param in self.get_component_parameters(component):
                if param.owner_component != component:
                    if not param.is_fixed or self._owner_has_optimizable(param.owner_component, param.name, param.owner_param_name):
                        shared_params_info[(component, param.name)] = param.owner_component

        # Compute dependency-ordered component sequence for optuna_search_space
        # Components that provide shared params must be defined before consumers
        dependency_graph = {c: set() for c in self.components}
        for (consumer_component, _), owner_component in shared_params_info.items():
            if owner_component != consumer_component:
                dependency_graph[consumer_component].add(owner_component)

        # Topological sort: components with no dependencies first
        ordered_components = []
        remaining = set(self.components)
        while remaining:
            # Find components whose dependencies are all resolved
            ready = [c for c in remaining if dependency_graph[c].issubset(set(ordered_components))]
            # Preserve original COMPONENT_SEQUENCE order among equally-ready components
            ready.sort(key=lambda c: self.COMPONENT_SEQUENCE.index(c))
            ordered_components.extend(ready)
            remaining -= set(ready)

        # Start function definition
        code = '''

def optuna_search_space(trial: optuna.Trial) -> Dict[str, Any]:
    """
    Generate parameter search space for Optuna optimization.

    This function is AUTO-GENERATED with crossover constraints to prevent
    identical period values that cause zero-trade scenarios.
    """
    params = {}

    # Component parameters
'''
        # Add ordering comment if different from default
        if ordered_components != list(self.components):
            code += f'    # Order: {" → ".join(c.capitalize() for c in ordered_components)} (respects shared parameter dependencies)\n'

        # Generate suggestions for each component in dependency order
        for component in ordered_components:
            params = self.get_component_parameters(component)
            component_params = {}  # Track for crossover constraints

            code += f'\n    # {component.capitalize()} parameters\n'
            code += f"    {component}_params = {{}}\n"

            for param in params:
                if param.is_fixed:
                    # Check if this is a shared fixed param whose owner has it as optimizable
                    if param.owner_component != component and self._owner_has_optimizable(param.owner_component, param.name, param.owner_param_name):
                        owner = param.owner_component
                        # Use owner_param_name for cross-name references (e.g., sizer_atr_period → exit_atr_period)
                        owner_key = param.owner_param_name if param.owner_param_name else param.name
                        code += f'    # Shared parameter from {owner} (owner optimizes {owner_key})\n'
                        code += f'    {component}_params["{param.name}"] = {owner}_params["{owner_key}"]\n'
                    else:
                        # Truly fixed parameter - hardcode default
                        code += f'    {component}_params["{param.name}"] = {repr(param.default)}\n'
                    continue

                # Check if this is a shared parameter (not owned by this component)
                is_shared = (param.owner_component != component)

                if is_shared:
                    # Copy value from owner component
                    owner = param.owner_component
                    # Use owner_param_name for cross-name references
                    owner_key = param.owner_param_name if param.owner_param_name else param.name
                    code += f'    # Shared parameter from {owner}\n'
                    code += f'    {component}_params["{param.name}"] = {owner}_params["{owner_key}"]\n'
                else:
                    # Owned parameter - use Optuna suggestion
                    # Avoid doubled prefix (e.g., entry_entry_tsf_period)
                    if param.name.startswith(f'{component}_'):
                        param_name_optuna = param.name
                    else:
                        param_name_optuna = f'{component}_{param.name}'

                    if param.param_type.lower() == 'int':
                        if param.range_or_value is None:
                            # No range specified - use default value (non-optimizable)
                            code += f'    {component}_params["{param.name}"] = {repr(param.default)}\n'
                        else:
                            min_val, max_val = param.range_or_value[0], param.range_or_value[1]
                            code += f'    {component}_params["{param.name}"] = trial.suggest_int("{param_name_optuna}", {min_val}, {max_val})\n'
                            component_params[param.name] = (min_val, max_val)

                    elif param.param_type.lower() == 'float':
                        if param.range_or_value is None:
                            # No range specified - use default value (non-optimizable)
                            code += f'    {component}_params["{param.name}"] = {repr(param.default)}\n'
                        else:
                            min_val, max_val = param.range_or_value[0], param.range_or_value[1]
                            code += f'    {component}_params["{param.name}"] = trial.suggest_float("{param_name_optuna}", {min_val}, {max_val})\n'

                    elif param.param_type.lower() == 'bool':
                        code += f'    {component}_params["{param.name}"] = trial.suggest_categorical("{param_name_optuna}", [True, False])\n'

                    elif param.param_type.lower() == 'categorical':
                        choices = param.range_or_value if isinstance(param.range_or_value, list) else [param.default]
                        code += f'    {component}_params["{param.name}"] = trial.suggest_categorical("{param_name_optuna}", {choices})\n'

            # Add crossover constraints for this component
            component_crossovers = [pair for pair in crossover_pairs if pair[2] == component]
            if component_crossovers:
                code += '\n    # Crossover constraints (prevent identical periods causing zero trades)\n'
                for short_param, long_param, _, is_period in component_crossovers:
                    # Use different minimum gaps based on parameter type
                    # Period parameters: require gap of 5 (prevents crossover calculation issues)
                    # Non-period parameters (multipliers, etc.): require gap of 0.1 (just ensure long > short)
                    if is_period:
                        min_gap = 5
                        code += f'    if {component}_params["{long_param}"] <= {component}_params["{short_param}"] or ({component}_params["{long_param}"] - {component}_params["{short_param}"]) < {min_gap}:\n'
                        code += f'        raise optuna.TrialPruned()  # Enforce: {long_param} > {short_param} + {min_gap}\n'
                    else:
                        # For non-period parameters, just ensure long > short (no minimum gap)
                        code += f'    if {component}_params["{long_param}"] <= {component}_params["{short_param}"]:\n'
                        code += f'        raise optuna.TrialPruned()  # Enforce: {long_param} > {short_param}\n'

            code += f'    params["{component}_params"] = {component}_params\n'

        # Add printlog
        code += '\n    # Framework requirement\n'
        code += '    params["entry_params"]["printlog"] = False\n'
        code += '    params["exit_params"]["printlog"] = False\n'
        code += '    params["risk_params"]["printlog"] = False\n'
        code += '    params["sizer_params"]["printlog"] = False\n'

        code += '\n    return params\n'

        return code

    def _generate_framework_init(self) -> str:
        """Generate framework initialization and DEFAULT_PARAMS with shared parameter copying"""

        code = '''

# Initialize framework and register components
framework = StrategyParameterFramework()
framework.register_component(EntryParameters())
framework.register_component(ExitParameters())
framework.register_component(RiskParameters())
framework.register_component(SizerParameters())

# Generate default parameter structure
DEFAULT_PARAMS = framework.compose_default_strategy()
'''

        # Add shared parameter copying for DEFAULT_PARAMS (handles cross-name shared params)
        shared_params_code = []
        for component in self.components:
            for param in self.get_component_parameters(component):
                if param.owner_component != component and not param.is_fixed:
                    owner = param.owner_component
                    # Use owner_param_name for cross-name references
                    owner_key = param.owner_param_name if param.owner_param_name else param.name
                    shared_params_code.append(
                        f"DEFAULT_PARAMS['{component}_params']['{param.name}'] = DEFAULT_PARAMS['{owner}_params']['{owner_key}']"
                    )

        if shared_params_code:
            code += "\n# Add shared parameters: copy from owner components\n"
            for line in shared_params_code:
                code += f"{line}\n"

        return code

    def _generate_shared_params_helper(self) -> str:
        """Generate helper function for shared parameter mapping.

        This function will be used by select_best_trial.py to apply
        optimized values from owner components to shared parameters.
        """
        # Collect shared parameter info with cross-name support
        # {param_name: {'owner': component, 'owner_param': owner_param_name, 'shared_by': [components]}}
        shared_params_mapping = {}

        for component in self.components:
            for param in self.get_component_parameters(component):
                if param.owner_component != component:
                    # Include shared params where owner has optimizable version
                    if not param.is_fixed or self._owner_has_optimizable(param.owner_component, param.name, param.owner_param_name):
                        param_name = param.name
                        owner = param.owner_component
                        owner_param = param.owner_param_name if param.owner_param_name else param_name

                        if param_name not in shared_params_mapping:
                            shared_params_mapping[param_name] = {
                                'owner': owner,
                                'owner_param': owner_param,
                                'shared_by': []
                            }

                        if component not in shared_params_mapping[param_name]['shared_by']:
                            shared_params_mapping[param_name]['shared_by'].append(component)

        # Generate the helper function code
        code = '''

def get_shared_params_mapping() -> Dict[str, Dict[str, Any]]:
    """
    Returns the mapping of shared parameters between components.

    This function is AUTO-GENERATED based on params_to_optimize.json ownership.
    Used by select_best_trial.py to apply optimized values from owner to shared params.

    Returns:
        Dict mapping param_name to {'owner': component_name, 'owner_param': owner_param_name, 'shared_by': [component_names]}
    """
    return '''

        # Format the mapping as Python dict literal
        if shared_params_mapping:
            code += '{\n'
            for param_name, info in shared_params_mapping.items():
                code += f'        "{param_name}": {{"owner": "{info["owner"]}", "owner_param": "{info["owner_param"]}", "shared_by": {info["shared_by"]}}},\n'
            code += '    }\n'
        else:
            code += '{}\n'

        # Add helper function to apply sharing to params dict
        code += '''

def apply_shared_params(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Apply shared parameter values from owner components to all shared components.

    This function is AUTO-GENERATED. It copies optimized parameter values from
    the owner component to all components that share that parameter.

    Handles differently-named shared parameters (e.g., exit_atr_period → sizer_atr_period).

    Args:
        params: Parameter dict with keys like 'component_paramname' (e.g., 'exit_atr_period')

    Returns:
        Updated params dict with shared params filled from owner's values
    """
    shared_mapping = get_shared_params_mapping()

    for param_name, info in shared_mapping.items():
        owner_param = info['owner_param']

        if owner_param in params:
            source_value = params[owner_param]
            params[param_name] = source_value

    return params
'''

        return code

    def generate_complete_file(self) -> str:
        """Generate complete strategy_params.py content"""

        code_parts = []

        # Imports
        code_parts.append(self._generate_imports())

        # Component classes
        for component in self.components:
            code_parts.append(self._generate_component_class(component))

        # Framework initialization
        code_parts.append(self._generate_framework_init())

        # Shared params helper functions
        code_parts.append(self._generate_shared_params_helper())

        # Optuna search space
        code_parts.append(self._generate_optuna_search_space())

        return '\n'.join(code_parts)

    def write_to_file(self, output_path: str) -> None:
        """Generate and write strategy_params.py to file"""
        content = self.generate_complete_file()

        # Ensure parent directory exists. Without this, callers whose
        # workspace cleaners wipe the output dir between runs hit a
        # FileNotFoundError on `open(..., 'w')` that the upstream wrapper
        # mislabels as "Input file not found".
        parent = Path(output_path).parent
        if str(parent):
            parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, 'w') as f:
            f.write(content)

        print(f"✅ Generated: {output_path}")

    def print_correction_summary(self) -> None:
        """Print summary of all auto-corrections for agent visibility"""
        if not self.auto_corrections:
            print("✅ No period cap corrections needed - all parameters within limits")
            return

        print()
        print("="*70)
        print("📋 PERIOD CAP AUTO-CORRECTIONS SUMMARY")
        print("="*70)
        print()
        print(f"Total corrections: {len(self.auto_corrections)}")
        print()
        print("IMPORTANT FOR AGENT:")
        print("  The generated strategy_params.py contains CORRECTED values, not")
        print("  the original values from params_to_optimize.md. This is intentional")
        print("  to prevent NaN data issues and zero-trade scenarios.")
        print()
        print("Details:")
        print()

        for i, correction in enumerate(self.auto_corrections, 1):
            print(f"{i}. Parameter: {correction['param']}")
            print(f"   Category: {correction['category']} (cap = {correction['cap']})")

            if correction['type'] == 'fixed_value':
                print(f"   Type: Fixed value")
                print(f"   Changed: {correction['old_value']} → {correction['new_value']}")
            else:
                print(f"   Type: Range parameter")
                print(f"   Original range: {correction['old_range']}, default: {correction['old_default']}")
                print(f"   Corrected range: {correction['new_range']}, default: {correction['new_default']}")

            print()

        print("="*70)
        print()


@dataclass
class GenerationResult:
    """Structured return value for :func:`generate_strategy_params`.

    Attributes:
        success: True if the output file was written.
        output_path: Absolute path of the output file (written on success,
            target path on failure).
        corrections: Auto-clamp corrections applied during generation
            (period cap violations). Each entry has keys ``param``, ``type``
            ("fixed_value" | "range"), ``old_*`` / ``new_*``, ``cap``,
            ``category``, and (for ranges) ``changes``.
        message: Human-readable summary or error message.
    """

    success: bool
    output_path: str
    corrections: List[Dict[str, Any]] = field(default_factory=list)
    message: str = ""


def generate_strategy_params(
    params_file_path: str,
    output_path: str,
    frequency: str = "interday",
    indicator_config: Optional[IndicatorConfig] = None,
) -> GenerationResult:
    """Generate ``strategy_params.py`` from a ``params_to_optimize.json`` file.

    Runs the deterministic code-generation pipeline (parse → ownership →
    component classes → optuna_search_space → write). Period parameters
    that exceed the frequency-appropriate indicator cap are auto-clamped;
    each correction is logged and returned in the ``corrections`` list.

    Args:
        params_file_path: Absolute path to ``params_to_optimize.json``.
            Required — no default; earlier defaults silently wrote into
            unreachable locations.
        output_path: Absolute path to write ``strategy_params.py``.
            Required — same reason.
        frequency: ``"interday"`` (daily bars, caps: TEMA≤62, ADX≤93, default≤180)
            or ``"intraday"`` (sub-daily bars, caps: TEMA≤500, ADX≤750, default≤1000).
        indicator_config: Optional custom :class:`IndicatorConfig`. When
            None, library defaults are used.

    Returns:
        :class:`GenerationResult` — ``success=False`` with a descriptive
        ``message`` on parse / IO errors (no exception leaks to the caller).
    """
    from dataclasses import asdict as _asdict  # noqa: F401 — used for future serialization hooks

    try:
        generator = StrategyParamsGenerator(
            params_file_path=params_file_path,
            frequency=frequency,
            indicator_config=indicator_config,
        )
        generator.write_to_file(output_path)
        generator.print_correction_summary()
        return GenerationResult(
            success=True,
            output_path=output_path,
            corrections=list(generator.auto_corrections),
            message=f"Successfully generated {output_path}",
        )
    except FileNotFoundError as e:
        # Distinguish input-read vs output-write failures: pre-fix, both
        # surfaced as "Input file not found" with the wrong path attached.
        bad_path = e.filename or ""
        if bad_path and Path(bad_path).resolve() == Path(output_path).resolve():
            label = f"Failed to write output {output_path}"
        elif bad_path and Path(bad_path).resolve() == Path(params_file_path).resolve():
            label = f"Input file not found: {params_file_path}"
        else:
            label = "File not found"
        return GenerationResult(
            success=False,
            output_path=output_path,
            message=f"{label}: {e}",
        )
    except json.JSONDecodeError as e:
        return GenerationResult(
            success=False,
            output_path=output_path,
            message=f"Failed to parse JSON in {params_file_path}: {e}",
        )
    except Exception as e:
        import traceback
        return GenerationResult(
            success=False,
            output_path=output_path,
            message=f"{type(e).__name__}: {e}\n{traceback.format_exc()}",
        )


if __name__ == "__main__":
    # CLI: explicit paths; no more "default writes into the installed package".
    import sys

    if len(sys.argv) != 3:
        print(
            "Usage: python -m echolon.strategy.generators.strategy_params_generator "
            "<params_to_optimize.json> <output_strategy_params.py> [frequency=interday]"
        )
        sys.exit(2)

    params_path = sys.argv[1]
    out_path = sys.argv[2]
    freq = sys.argv[3] if len(sys.argv) > 3 else "interday"

    result = generate_strategy_params(
        params_file_path=params_path,
        output_path=out_path,
        frequency=freq,
    )
    print(result.message)
    sys.exit(0 if result.success else 1)
