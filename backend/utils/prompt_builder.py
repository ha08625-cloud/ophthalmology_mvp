"""
Prompt Builder - Construct extraction prompts from structured intent

Responsibilities:
- Convert QuestionOutput (from Question Selector) into extraction prompts
- Convert PromptSpec into deterministic prompt text
- Validate semantic completeness (field labels, descriptions)
- Enforce prompt structure and ordering
- Handle extraction modes (PRIMARY, REPLAY, etc.)

NOT responsible for:
- Dialogue phase logic
- Episode disambiguation
- Response parsing
- LLM calls

Design principles:
- Fail-fast validation (no partial builds)
- Prompt construction is medical logic, not language work
- QuestionOutput is the primary input contract from Question Selector
- PromptSpec is an internal compiled intent
- Field IDs for output, labels for semantic meaning

V4 Changes:
- Added create_prompt_spec_from_question_output() as primary factory
- QuestionOutput now contains field_label, field_description, definitions
- Deprecated create_prompt_spec() (dict-based) in favor of QuestionOutput version
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional, List, Dict, Any, Union

# Import QuestionOutput from contracts
# Flat import for server testing
try:
    from backend.contracts import QuestionOutput
except ImportError:
    from contracts import QuestionOutput

logger = logging.getLogger(__name__)


class PromptBuildError(Exception):
    """Raised when prompt cannot be built due to invalid/incomplete spec"""
    pass


class PromptMode(Enum):
    """
    Extraction mode for prompt construction.
    
    Controls how the prompt frames the extraction task.
    Not serialized - internal control signal only.
    """
    PRIMARY = "primary"                    # Normal extraction from patient response
    REPLAY = "replay"                      # Clarification exit replay (future)
    CLARIFICATION_EXIT = "clarification_exit"  # Post-disambiguation extraction (future)


class FieldType(str, Enum):
    """
    Valid field types for extraction.
    
    Canonical set for this system. New types added deliberately.
    """
    CATEGORICAL = "categorical"
    BOOLEAN = "boolean"
    TEXT = "text"


@dataclass(frozen=True)
class EpisodeAnchor:
    """
    Episode context anchor (stub for future use).
    
    Will eventually encode:
    - Which episode extraction is scoped to
    - Resolution status
    - Temporal boundaries
    
    Currently unused but reserves authority in PromptSpec.
    """
    episode_id: Optional[str] = None
    resolution_status: Optional[str] = None


@dataclass(frozen=True)
class FieldSpec:
    """
    Complete specification for a single extractable field.
    
    Compiled from QuestionOutput or ruleset entry. Contains all semantic
    information needed to instruct extraction for this field.
    
    Validation enforced at construction - fail-fast.
    """
    field_id: str          # e.g., "vl_onset_speed" (used as JSON key)
    label: str             # e.g., "visual loss onset speed" (semantic meaning)
    description: str       # e.g., "how quickly visual loss developed"
    field_type: FieldType  # categorical | boolean | text
    valid_values: Optional[List[str]] = None      # Required for categorical
    definitions: Optional[Dict[str, str]] = None  # Optional value definitions
    
    def __post_init__(self):
        """Validate field spec invariants. Fail-fast on any violation."""
        
        # Field ID must be non-empty
        if not self.field_id or not isinstance(self.field_id, str):
            raise PromptBuildError(f"field_id must be non-empty string, got: {self.field_id}")
        
        # Label must be non-empty
        if not self.label or not isinstance(self.label, str):
            raise PromptBuildError(
                f"field_label missing or empty for field '{self.field_id}'"
            )
        
        # Description must be non-empty
        if not self.description or not isinstance(self.description, str):
            raise PromptBuildError(
                f"field_description missing or empty for field '{self.field_id}'"
            )
        
        # Field type must be valid FieldType enum
        if not isinstance(self.field_type, FieldType):
            raise PromptBuildError(
                f"field_type must be FieldType enum for field '{self.field_id}', "
                f"got: {self.field_type}"
            )
        
        # Categorical fields MUST have valid_values
        if self.field_type == FieldType.CATEGORICAL:
            if not self.valid_values or len(self.valid_values) == 0:
                raise PromptBuildError(
                    f"Categorical field '{self.field_id}' missing valid_values"
                )
        
        # If definitions exist, they must cover all valid_values
        if self.definitions and self.valid_values:
            missing_definitions = set(self.valid_values) - set(self.definitions.keys())
            if missing_definitions:
                raise PromptBuildError(
                    f"Field '{self.field_id}' definitions incomplete. "
                    f"Missing definitions for: {missing_definitions}"
                )


@dataclass(frozen=True)
class PromptSpec:
    """
    Complete specification for prompt construction.
    
    Represents compiled intent - what extraction to perform and why.
    Consumed by PromptBuilder to generate deterministic prompt text.
    
    Not a convenience dict - this is a contract object.
    """
    mode: PromptMode                              # Extraction mode
    primary_field: FieldSpec                      # Main field to extract
    question_text: str                            # Question asked to patient
    additional_fields: List[FieldSpec] = None     # Optional metadata window
    episode_anchor: Optional[EpisodeAnchor] = None  # Episode context (future)
    constraints: Optional[Dict[str, Any]] = None    # Future extraction constraints
    
    def __post_init__(self):
        """Validate spec invariants"""
        
        # Question text must be non-empty
        if not self.question_text or not isinstance(self.question_text, str):
            raise PromptBuildError("question_text must be non-empty string")
        
        # Mode must be valid
        if not isinstance(self.mode, PromptMode):
            raise PromptBuildError(f"mode must be PromptMode enum, got: {self.mode}")
        
        # Primary field must be valid FieldSpec
        if not isinstance(self.primary_field, FieldSpec):
            raise PromptBuildError(
                f"primary_field must be FieldSpec, got: {type(self.primary_field)}"
            )
        
        # Additional fields must be list of FieldSpec if provided
        if self.additional_fields is not None:
            if not isinstance(self.additional_fields, list):
                raise PromptBuildError("additional_fields must be list")
            
            for i, field in enumerate(self.additional_fields):
                if not isinstance(field, FieldSpec):
                    raise PromptBuildError(
                        f"additional_fields[{i}] must be FieldSpec, "
                        f"got: {type(field)}"
                    )


class PromptBuilder:
    """
    Build extraction prompts from PromptSpec.
    
    Pure function: PromptSpec + patient_response -> prompt_text
    No state, no side effects, deterministic output.
    """
    
    def build(self, spec: PromptSpec, patient_response: str) -> str:
        """
        Build complete extraction prompt from spec and patient response.
        
        Args:
            spec: Complete prompt specification
            patient_response: Patient's actual response text
            
        Returns:
            Complete prompt text ready for LLM
            
        Raises:
            PromptBuildError: If spec is invalid or incomplete
            TypeError: If inputs wrong type
        """
        if not isinstance(spec, PromptSpec):
            raise TypeError(f"spec must be PromptSpec, got {type(spec).__name__}")
        
        if not isinstance(patient_response, str):
            raise TypeError(
                f"patient_response must be string, got {type(patient_response).__name__}"
            )
        
        # Route to mode-specific builder
        if spec.mode == PromptMode.PRIMARY:
            return self._build_primary_prompt(spec, patient_response)
        elif spec.mode == PromptMode.REPLAY:
            # Future: clarification exit replay
            raise NotImplementedError("REPLAY mode not yet implemented")
        elif spec.mode == PromptMode.CLARIFICATION_EXIT:
            # Future: post-disambiguation extraction
            raise NotImplementedError("CLARIFICATION_EXIT mode not yet implemented")
        else:
            raise PromptBuildError(f"Unknown mode: {spec.mode}")
    
    def _build_primary_prompt(self, spec: PromptSpec, patient_response: str) -> str:
        """
        Build PRIMARY mode extraction prompt.
        
        Format:
        1. System role
        2. Primary field (with ID, label, description, type, values)
        3. Additional fields (if any)
        4. Patient response
        5. Output format + rules
        """
        primary = spec.primary_field
        
        # System role
        prompt = "You are a medical data extractor for ophthalmology consultations.\n\n"
        
        # Primary field section
        prompt += "PRIMARY FIELD\n"
        prompt += f"Field ID: {primary.field_id}\n"
        prompt += f"Meaning: {primary.label}\n"
        prompt += f"Description: {primary.description}\n"
        prompt += f"Type: {primary.field_type.value}\n"
        
        # Add valid values and definitions for categorical
        if primary.field_type == FieldType.CATEGORICAL:
            prompt += "Valid values:\n"
            for value in primary.valid_values:
                if primary.definitions and value in primary.definitions:
                    definition = primary.definitions[value]
                    prompt += f"  - {value} ({definition})\n"
                else:
                    prompt += f"  - {value}\n"
        
        # Additional fields section
        if spec.additional_fields and len(spec.additional_fields) > 0:
            prompt += "\nADDITIONAL CONTEXT - You may also extract these fields if clearly mentioned:\n"
            
            for field in spec.additional_fields:
                prompt += f"  - Field ID: {field.field_id}\n"
                prompt += f"    Meaning: {field.label}\n"
                prompt += f"    Type: {field.field_type.value}\n"
                
                if field.field_type == FieldType.CATEGORICAL:
                    values_str = ", ".join(field.valid_values)
                    prompt += f"    Valid values: {values_str}\n"
                
                prompt += "\n"
        
        # Patient response
        prompt += f"\nPatient response: \"{patient_response}\"\n\n"
        
        # Output format and rules
        prompt += "Extract any relevant fields from the patient's response.\n"
        prompt += f"Return ONLY valid JSON using the Field ID as the key:\n"
        prompt += "{\n"
        prompt += f'  "{primary.field_id}": "value",\n'
        prompt += f'  "other_field_id": "value"\n'
        prompt += "}\n\n"
        
        prompt += "Rules:\n"
        prompt += f"- PRIMARY focus on {primary.field_id}\n"
        prompt += "- You MAY extract additional fields if clearly mentioned\n"
        prompt += "- If the patient response does not clearly contain extractable information for the listed fields, return {}\n"
        prompt += "- Do not guess. Do not infer.\n"
        prompt += "- Use exact Field IDs as JSON keys\n"
        prompt += "- For categorical fields, use exact valid values\n"
        prompt += "- For boolean fields, use true or false (lowercase, no quotes)\n"
        
        return prompt


# =============================================================================
# Factory Functions
# =============================================================================

def create_prompt_spec_from_question_output(
    question: QuestionOutput,
    mode: PromptMode = PromptMode.PRIMARY,
    next_questions: Optional[List[QuestionOutput]] = None,
    episode_anchor: Optional[EpisodeAnchor] = None
) -> PromptSpec:
    """
    Factory function: Convert QuestionOutput(s) into PromptSpec.
    
    This is the PRIMARY factory for creating PromptSpec from Question Selector
    output. QuestionOutput contains all semantic information needed for prompt
    construction (field_label, field_description, definitions).
    
    Args:
        question: Primary QuestionOutput from Question Selector
            Required attributes: id, question, field, field_type
            Required for prompt: field_label, field_description
            Conditional: valid_values (if categorical)
            Optional: definitions
        mode: Extraction mode (default PRIMARY)
        next_questions: Optional list of QuestionOutput for metadata window
        episode_anchor: Optional episode context (future use)
        
    Returns:
        PromptSpec ready for PromptBuilder
        
    Raises:
        PromptBuildError: If question missing required attributes
        TypeError: If inputs have wrong type
        
    Examples:
        >>> from backend.contracts import QuestionOutput
        >>> q = QuestionOutput(
        ...     id='vl_3',
        ...     question='Which eye is affected?',
        ...     field='vl_laterality',
        ...     field_type='categorical',
        ...     valid_values=('left', 'right', 'both'),
        ...     field_label='visual loss laterality',
        ...     field_description='Which eye or eyes are affected'
        ... )
        >>> spec = create_prompt_spec_from_question_output(q)
    """
    # Validate question is QuestionOutput
    if not isinstance(question, QuestionOutput):
        raise TypeError(
            f"question must be QuestionOutput, got {type(question).__name__}"
        )
    
    # Validate required prompt fields are present
    if not question.field_label:
        raise PromptBuildError(
            f"QuestionOutput '{question.id}' missing field_label (required for prompt)"
        )
    
    if not question.field_description:
        raise PromptBuildError(
            f"QuestionOutput '{question.id}' missing field_description (required for prompt)"
        )
    
    # Convert primary question to FieldSpec
    primary_field = _question_output_to_field_spec(question)
    
    # Convert next_questions if provided
    additional_fields = []
    if next_questions:
        if not isinstance(next_questions, list):
            raise TypeError(
                f"next_questions must be list, got {type(next_questions).__name__}"
            )
        
        for i, nq in enumerate(next_questions):
            if not isinstance(nq, QuestionOutput):
                raise TypeError(
                    f"next_questions[{i}] must be QuestionOutput, "
                    f"got {type(nq).__name__}"
                )
            
            # Validate required prompt fields
            if not nq.field_label:
                raise PromptBuildError(
                    f"next_questions[{i}] ('{nq.id}') missing field_label"
                )
            
            if not nq.field_description:
                raise PromptBuildError(
                    f"next_questions[{i}] ('{nq.id}') missing field_description"
                )
            
            additional_fields.append(_question_output_to_field_spec(nq))
    
    # Build and return PromptSpec
    return PromptSpec(
        mode=mode,
        primary_field=primary_field,
        question_text=question.question,
        additional_fields=additional_fields if additional_fields else None,
        episode_anchor=episode_anchor,
        constraints=None  # Stub for future use
    )


def _question_output_to_field_spec(question: QuestionOutput) -> FieldSpec:
    """
    Convert QuestionOutput to FieldSpec.
    
    Internal helper. Handles conversion of:
    - field_type string to FieldType enum
    - definitions tuple-of-tuples to dict
    - valid_values tuple to list
    
    Args:
        question: QuestionOutput with required attributes
        
    Returns:
        Validated FieldSpec
        
    Raises:
        PromptBuildError: If field_type invalid
    """
    field_id = question.field
    field_type_str = question.field_type
    
    # Normalize field_type to FieldType enum
    try:
        field_type = FieldType(field_type_str)
    except ValueError:
        valid_types = [ft.value for ft in FieldType]
        raise PromptBuildError(
            f"Invalid field_type '{field_type_str}' for field '{field_id}'. "
            f"Valid types: {valid_types}"
        )
    
    # Convert valid_values tuple to list (FieldSpec uses list)
    valid_values = None
    if question.valid_values is not None:
        valid_values = list(question.valid_values)
    
    # Convert definitions tuple-of-tuples to dict
    # QuestionOutput stores as: ((key1, val1), (key2, val2), ...)
    # FieldSpec expects: {key1: val1, key2: val2, ...}
    definitions = None
    if question.definitions is not None:
        definitions = dict(question.definitions)
    
    # Build FieldSpec (validation happens in __post_init__)
    return FieldSpec(
        field_id=field_id,
        label=question.field_label,
        description=question.field_description,
        field_type=field_type,
        valid_values=valid_values,
        definitions=definitions
    )


# =============================================================================
# Deprecated: Dict-based factory (for backward compatibility)
# =============================================================================

def create_prompt_spec(
    question: Dict[str, Any],
    mode: PromptMode = PromptMode.PRIMARY,
    next_questions: Optional[List[Dict[str, Any]]] = None,
    episode_anchor: Optional[EpisodeAnchor] = None
) -> PromptSpec:
    """
    DEPRECATED: Use create_prompt_spec_from_question_output() instead.
    
    Factory function: Convert ruleset question dict(s) into PromptSpec.
    
    This function is maintained for backward compatibility during transition.
    New code should use create_prompt_spec_from_question_output() with
    QuestionOutput objects from the Question Selector.
    
    Args:
        question: Primary question dict from ruleset
            Required keys: 'field', 'field_type', 'field_label', 
                          'field_description', 'question'
            Conditional: 'valid_values' (if categorical)
            Optional: 'definitions'
        mode: Extraction mode (default PRIMARY)
        next_questions: Optional list of question dicts for metadata window
        episode_anchor: Optional episode context (future use)
        
    Returns:
        PromptSpec ready for PromptBuilder
        
    Raises:
        PromptBuildError: If any question missing required fields or invalid
    """
    logger.warning(
        "create_prompt_spec() is deprecated. "
        "Use create_prompt_spec_from_question_output() with QuestionOutput objects."
    )
    
    # Validate question is dict
    if not isinstance(question, dict):
        raise PromptBuildError(f"question must be dict, got {type(question).__name__}")
    
    # Check all required keys present
    required_keys = {'field', 'field_type', 'field_label', 'field_description', 'question'}
    missing_keys = required_keys - set(question.keys())
    if missing_keys:
        raise PromptBuildError(
            f"question dict missing required keys: {missing_keys}"
        )
    
    # Convert primary question to FieldSpec
    primary_field = _question_dict_to_field_spec(question)
    
    # Convert next_questions if provided
    additional_fields = []
    if next_questions:
        if not isinstance(next_questions, list):
            raise PromptBuildError(
                f"next_questions must be list, got {type(next_questions).__name__}"
            )
        
        for i, nq in enumerate(next_questions):
            if not isinstance(nq, dict):
                raise PromptBuildError(
                    f"next_questions[{i}] must be dict, got {type(nq).__name__}"
                )
            
            # Validate required keys
            missing = required_keys - set(nq.keys())
            if missing:
                raise PromptBuildError(
                    f"next_questions[{i}] missing required keys: {missing}"
                )
            
            additional_fields.append(_question_dict_to_field_spec(nq))
    
    # Build and return PromptSpec
    return PromptSpec(
        mode=mode,
        primary_field=primary_field,
        question_text=question['question'],
        additional_fields=additional_fields if additional_fields else None,
        episode_anchor=episode_anchor,
        constraints=None  # Stub for future use
    )


def _question_dict_to_field_spec(question: Dict[str, Any]) -> FieldSpec:
    """
    Convert ruleset question dict to FieldSpec.
    
    DEPRECATED: Internal helper for deprecated create_prompt_spec().
    
    Args:
        question: Question dict with required keys
        
    Returns:
        Validated FieldSpec
        
    Raises:
        PromptBuildError: If field_type invalid or missing required data
    """
    field_id = question['field']
    field_type_str = question['field_type']
    
    # Normalize field_type to FieldType enum
    try:
        field_type = FieldType(field_type_str)
    except ValueError:
        valid_types = [ft.value for ft in FieldType]
        raise PromptBuildError(
            f"Invalid field_type '{field_type_str}' for field '{field_id}'. "
            f"Valid types: {valid_types}"
        )
    
    # Build FieldSpec (validation happens in __post_init__)
    return FieldSpec(
        field_id=field_id,
        label=question['field_label'],
        description=question['field_description'],
        field_type=field_type,
        valid_values=question.get('valid_values'),
        definitions=question.get('definitions')
    )
