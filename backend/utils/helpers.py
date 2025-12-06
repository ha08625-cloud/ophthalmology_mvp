"""
Utility helpers for ophthalmology consultation system
"""

import uuid
from datetime import datetime
from dataclasses import dataclass
from typing import List, Optional


def generate_consultation_id(short=True):
    """
    Generate unique consultation identifier
    
    Args:
        short (bool): If True, return 8-char hex. If False, return full UUID.
        
    Returns:
        str: Consultation ID
    """
    full_id = uuid.uuid4().hex
    return full_id[:8] if short else full_id


def generate_consultation_filename(prefix="consultation", extension="json"):
    """
    Generate timestamped filename with unique ID
    
    Format: {prefix}_{YYYYMMDD_HHMMSS}_{short_uuid}.{extension}
    Example: consultation_20251126_153045_a3f7e2b9.json
    
    Args:
        prefix (str): Filename prefix
        extension (str): File extension (without dot)
        
    Returns:
        str: Generated filename
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    short_id = generate_consultation_id(short=True)
    return f"{prefix}_{timestamp}_{short_id}.{extension}"


@dataclass
class ValidationResult:
    """
    Result of consultation data validation
    
    Attributes:
        is_complete (bool): True if all required fields present
        missing_required (List[str]): Field IDs of missing required fields
        warnings (List[str]): Non-critical validation warnings
        completeness_score (float): 0.0-1.0 ratio of present/expected fields
    """
    is_complete: bool
    missing_required: List[str]
    warnings: Optional[List[str]] = None
    completeness_score: float = 0.0
    
    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []
    
    def to_dict(self):
        """Convert to dict for serialization"""
        return {
            'is_complete': self.is_complete,
            'missing_required': self.missing_required,
            'warnings': self.warnings,
            'completeness_score': self.completeness_score
        }


class ConsultationValidator:
    """
    Validates consultation data completeness
    
    Simple implementation for MVP - just checks for required fields.
    V2: Can add complex validation rules, cross-field checks, etc.
    """
    
    def __init__(self, schema):
        """
        Initialize validator with schema
        
        Args:
            schema (dict): JSON schema defining required/optional fields
        """
        self.schema = schema
        self._required_fields = self._extract_required_fields()
    
    def _extract_required_fields(self):
        """
        Extract list of required field names from schema
        
        Returns:
            List[str]: Required field names
        """
        required = []
        
        for section_name, section_schema in self.schema.items():
            if section_name in ['metadata', 'schema_version']:
                continue
            
            if not isinstance(section_schema, dict):
                continue
            
            for field_name, field_def in section_schema.items():
                if field_name.startswith('_'):
                    continue
                
                if isinstance(field_def, dict):
                    if field_def.get('required') == True:
                        required.append(field_name)
        
        return required
    
    def validate(self, state_data):
        """
        Validate consultation data
        
        Args:
            state_data (dict): State data from StateManager
            
        Returns:
            ValidationResult: Validation results
        """
        missing_required = []
        warnings = []
        
        # Check for missing required fields
        for field_name in self._required_fields:
            if field_name not in state_data or state_data[field_name] is None:
                missing_required.append(field_name)
        
        # Calculate completeness
        total_expected = len(self._required_fields)
        total_present = total_expected - len(missing_required)
        completeness_score = total_present / total_expected if total_expected > 0 else 0.0
        
        # Determine if complete
        is_complete = len(missing_required) == 0
        
        # Generate warnings
        if not is_complete:
            warnings.append(
                f"{len(missing_required)} required fields missing: "
                f"{', '.join(missing_required[:5])}{'...' if len(missing_required) > 5 else ''}"
            )
        
        return ValidationResult(
            is_complete=is_complete,
            missing_required=missing_required,
            warnings=warnings,
            completeness_score=completeness_score
        )