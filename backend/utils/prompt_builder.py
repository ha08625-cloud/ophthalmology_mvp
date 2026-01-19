"""
Prompt Builder - Construct extraction prompts from structured intent

Responsibilities:
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
- PromptSpec is a compiled intent, not raw storage
- Field IDs for output, labels for semantic meaning
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional, List, Dict, Any

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
    
    Compiled from ruleset entry. Contains all semantic information
    needed to instruct extraction for this field.
    
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
    
    Pure function: PromptSpec + patient_response → prompt_text
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
        
        # Build prompt based on mode
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


def create_prompt_spec(
    question: Dict[str, Any],
    mode: PromptMode = PromptMode.PRIMARY,
    next_questions: Optional[List[Dict[str, Any]]] = None,
    episode_anchor: Optional[EpisodeAnchor] = None
) -> PromptSpec:
    """
    Factory function: Convert ruleset question dict(s) into PromptSpec.
    
    This is the compilation step from storage format to semantic intent.
    Validates all required fields are present and complete.
    
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
        
    Examples:
        >>> spec = create_prompt_spec(
        ...     question={
        ...         'field': 'vl_onset_speed',
        ...         'field_type': 'categorical',
        ...         'field_label': 'visual loss onset speed',
        ...         'field_description': 'how quickly visual loss developed',
        ...         'question': 'How quickly did it develop?',
        ...         'valid_values': ['acute', 'subacute', 'chronic'],
        ...         'definitions': {
        ...             'acute': 'seconds to minutes',
        ...             'subacute': 'hours to days',
        ...             'chronic': 'weeks or longer'
        ...         }
        ...     },
        ...     mode=PromptMode.PRIMARY
        ... )
    """
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
    primary_field = _question_to_field_spec(question)
    
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
            
            additional_fields.append(_question_to_field_spec(nq))
    
    # Build and return PromptSpec
    return PromptSpec(
        mode=mode,
        primary_field=primary_field,
        question_text=question['question'],
        additional_fields=additional_fields if additional_fields else None,
        episode_anchor=episode_anchor,
        constraints=None  # Stub for future use
    )


def _question_to_field_spec(question: Dict[str, Any]) -> FieldSpec:
    """
    Convert ruleset question dict to FieldSpec.
    
    Internal helper. Validates and normalizes field type.
    
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