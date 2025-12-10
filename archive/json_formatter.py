"""
JSON Formatter - Convert consultation state to structured JSON output

Responsibilities:
- Map state fields to schema sections using prefix convention
- Generate _status blocks per section (completeness tracking)
- Add metadata (timestamp, UUID, version, warnings)
- Validate types and convert where possible
- Handle unmapped fields gracefully
- Output pretty-printed JSON file

Design principles:
- Schema is source of truth for structure
- Don't block output on missing fields (warn only)
- Self-documenting completeness via _status blocks
- Version tracking for schema evolution
"""

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class JSONFormatter:
    """Format consultation state as structured JSON conforming to schema"""
    
    def __init__(self, schema_path):
        """
        Initialize formatter with schema
        
        Args:
            schema_path (str): Path to mvp_json_schema.json
            
        Raises:
            FileNotFoundError: If schema file doesn't exist
            json.JSONDecodeError: If schema is malformed
            ValueError: If schema missing required sections
        """
        self.schema_path = Path(schema_path)
        
        if not self.schema_path.exists():
            raise FileNotFoundError(f"Schema not found: {schema_path}")
        
        # Load schema
        with open(self.schema_path, 'r') as f:
            self.schema = json.load(f)
        
        # Extract schema version
        self.schema_version = self.schema.get("schema_version", "unknown")
        
        # Validate schema structure
        if "sections" not in self.schema and not any(
            key for key in self.schema.keys() 
            if key not in ["schema_version", "metadata"]
        ):
            raise ValueError("Schema must contain section definitions")
        
        # Get section definitions (handle both nested and flat schemas)
        if "sections" in self.schema:
            self.section_definitions = self.schema["sections"]
        else:
            # Flat schema - all top-level keys except metadata are sections
            self.section_definitions = {
                k: v for k, v in self.schema.items() 
                if k not in ["schema_version", "metadata"]
            }
        
        # Build field lookup map (which section owns each field)
        self.field_to_section = self._build_field_map()
        
        # Tracking for warnings
        self.warnings = []
        
        logger.info(f"JSON Formatter initialized with schema version {self.schema_version}")
        logger.info(f"Schema contains {len(self.section_definitions)} sections")
        logger.info(f"Total fields mapped: {len(self.field_to_section)}")
    
    def _build_field_map(self):
        """
        Build mapping of field_name -> section_name from schema
        
        Returns:
            dict: {field_name: section_name}
        """
        field_map = {}
        
        for section_name, section_fields in self.section_definitions.items():
            if not isinstance(section_fields, dict):
                continue
                
            for field_name in section_fields.keys():
                if not field_name.startswith('_'):
                    field_map[field_name] = section_name
        
        return field_map
    
    def format(self, state_data, consultation_id=None, output_path=None):
        """
        Format state data as structured JSON
        
        Args:
            state_data (dict): Structured data from state.export_for_json()
            consultation_id (str, optional): UUID for consultation (generated if not provided)
            output_path (str, optional): Path to save JSON file (just returns dict if None)
            
        Returns:
            dict: Formatted JSON structure
            
        Raises:
            TypeError: If state_data is not a dict
        """
        if not isinstance(state_data, dict):
            raise TypeError(f"state_data must be dict, got {type(state_data)}")
        
        # Reset warnings for this formatting run
        self.warnings = []
        
        # Generate consultation ID if not provided
        if consultation_id is None:
            consultation_id = str(uuid.uuid4())
        
        logger.info(f"Formatting consultation {consultation_id}")
        logger.info(f"State contains {len(state_data)} fields")
        
        # Build output structure
        output = {
            "metadata": self._build_metadata(consultation_id, state_data),
        }
        
        # Process each section
        for section_name in self.section_definitions.keys():
            section_output = self._process_section(section_name, state_data)
            output[section_name] = section_output
        
        # Identify unmapped fields
        unmapped = self._find_unmapped_fields(state_data)
        if unmapped:
            output["metadata"]["unmapped_fields"] = unmapped
            self.warnings.append(
                f"Found {len(unmapped)} fields in state that don't match schema"
            )
        
        # Add warnings to metadata
        output["metadata"]["warnings"] = self.warnings
        
        # Save to file if path provided
        if output_path:
            self._save_json(output, output_path)
        
        logger.info(f"Formatting complete. Completeness: {output['metadata']['completeness_score']:.2%}")
        
        return output
    
    def to_dict(self, state_data, consultation_id=None):
        """
        Convert state data to JSON dict (pure function - no file I/O)
        
        This is the recommended API for programmatic use.
        Returns dict only - caller decides whether to save to file.
        
        Args:
            state_data (dict): State data from StateManager.export_for_json()
            consultation_id (str, optional): UUID (auto-generated if None)
            
        Returns:
            dict: Formatted JSON structure
        """
        return self.format(state_data, consultation_id=consultation_id, output_path=None)
    
    def save(self, json_data, output_path):
        """
        Save JSON dict to file (helper method)
        
        Args:
            json_data (dict): JSON structure (from to_dict() or format())
            output_path (str): Path to save file
            
        Returns:
            str: Absolute path to saved file
        """
        return self._save_json(json_data, output_path)
    
    def _build_metadata(self, consultation_id, state_data):
        """
        Build metadata section
        
        Args:
            consultation_id (str): UUID for consultation
            state_data (dict): State data being formatted
            
        Returns:
            dict: Metadata structure
        """
        # Calculate total expected fields
        total_expected = 0
        for section_fields in self.section_definitions.values():
            if isinstance(section_fields, dict):
                total_expected += len([
                    f for f in section_fields.keys() 
                    if not f.startswith('_')
                ])
        
        # Count how many fields we have
        total_present = len([
            f for f in state_data.keys() 
            if not f.startswith('_') and f in self.field_to_section
        ])
        
        # Calculate completeness score
        completeness_score = total_present / total_expected if total_expected > 0 else 0.0
        
        metadata = {
            "schema_version": self.schema_version,
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "consultation_id": consultation_id,
            "completeness_score": round(completeness_score, 3),
            "total_fields_expected": total_expected,
            "total_fields_present": total_present,
        }
        
        return metadata
    
    def _process_section(self, section_name, state_data):
        """
        Process one section with _status block
        
        Args:
            section_name (str): Section identifier (e.g., 'visual_loss')
            state_data (dict): State data
            
        Returns:
            dict: Section with _status and field data
        """
        section_schema = self.section_definitions[section_name]
        
        if not isinstance(section_schema, dict):
            logger.warning(f"Section {section_name} schema is not a dict")
            return {"_status": {"complete": False, "error": "Invalid section schema"}}
        
        section_output = {}
        
        # Track fields for status
        fields_present = []
        missing_required = []
        missing_optional = []
        
        # Process each field in schema
        for field_name, field_spec in section_schema.items():
            # Skip metadata fields
            if field_name.startswith('_'):
                continue
            
            # Check if field exists in state
            if field_name in state_data:
                # Convert type if needed
                try:
                    converted_value = self._convert_type(
                        field_name,
                        state_data[field_name],
                        field_spec
                    )
                    section_output[field_name] = converted_value
                    fields_present.append(field_name)
                except Exception as e:
                    logger.error(f"Error processing field {field_name}: {e}")
                    self.warnings.append(f"Field {field_name}: {str(e)}")
            else:
                # Field missing from state
                required = field_spec.get("required", False)
                
                if required == True:
                    missing_required.append(field_name)
                elif required == "conditional":
                    # For MVP, treat conditional as optional
                    missing_optional.append(field_name)
                else:
                    missing_optional.append(field_name)
        
        # Build status block
        fields_expected = len([
            f for f in section_schema.keys() 
            if not f.startswith('_')
        ])
        
        section_output["_status"] = {
            "complete": len(missing_required) == 0,
            "fields_present": len(fields_present),
            "fields_expected": fields_expected,
            "missing_required": missing_required,
            "missing_optional": missing_optional
        }
        
        # Log if section incomplete
        if missing_required:
            logger.debug(
                f"Section {section_name} incomplete: "
                f"missing {len(missing_required)} required fields"
            )
        
        return section_output
    
    def _convert_type(self, field_name, value, field_spec):
        """
        Convert value to expected type based on schema
        
        Args:
            field_name (str): Field name (for error messages)
            value: Raw value from state
            field_spec (dict): Field specification from schema
            
        Returns:
            Converted value
            
        Note: On conversion failure, logs warning and returns raw value (Option A)
        """
        expected_type = field_spec.get("type")
        
        if expected_type is None:
            # No type specified in schema, return as-is
            return value
        
        # Type conversion logic
        try:
            if expected_type == "boolean":
                if isinstance(value, bool):
                    return value
                elif isinstance(value, str):
                    if value.lower() in ["true", "yes", "1"]:
                        self.warnings.append(
                            f"Field {field_name}: converted string '{value}' to boolean True"
                        )
                        return True
                    elif value.lower() in ["false", "no", "0"]:
                        self.warnings.append(
                            f"Field {field_name}: converted string '{value}' to boolean False"
                        )
                        return False
                    else:
                        self.warnings.append(
                            f"Field {field_name}: cannot convert '{value}' to boolean, keeping as-is"
                        )
                        return value
                else:
                    # Try to cast
                    return bool(value)
            
            elif expected_type == "integer":
                if isinstance(value, int):
                    return value
                elif isinstance(value, str):
                    try:
                        converted = int(value)
                        if str(converted) != value:
                            self.warnings.append(
                                f"Field {field_name}: converted string '{value}' to integer {converted}"
                            )
                        return converted
                    except ValueError:
                        self.warnings.append(
                            f"Field {field_name}: cannot convert '{value}' to integer, keeping as-is"
                        )
                        return value
                else:
                    return int(value)
            
            elif expected_type == "text":
                # Ensure it's a string
                if not isinstance(value, str):
                    self.warnings.append(
                        f"Field {field_name}: converted {type(value).__name__} to string"
                    )
                    return str(value)
                return value
            
            elif expected_type == "categorical":
                # Check against valid values if specified
                valid_values = field_spec.get("valid_values")
                if valid_values and value not in valid_values:
                    self.warnings.append(
                        f"Field {field_name}: value '{value}' not in valid_values {valid_values} (accepted anyway)"
                    )
                return value
            
            else:
                # Unknown type, return as-is
                return value
        
        except Exception as e:
            # Conversion failed, log and return raw value (Option A)
            self.warnings.append(
                f"Field {field_name}: type conversion failed ({e}), keeping raw value"
            )
            return value
    
    def _find_unmapped_fields(self, state_data):
        """
        Find fields in state that don't exist in schema
        
        Args:
            state_data (dict): State data
            
        Returns:
            dict: Unmapped fields and their values
        """
        unmapped = {}
        
        for field_name, value in state_data.items():
            # Skip metadata fields
            if field_name.startswith('_'):
                continue
            
            # Check if field exists in schema
            if field_name not in self.field_to_section:
                unmapped[field_name] = value
                logger.warning(f"Field '{field_name}' not found in schema")
        
        return unmapped
    
    def _save_json(self, data, output_path):
        """
        Save formatted JSON to file (pretty-printed)
        
        Args:
            data (dict): Formatted JSON structure
            output_path (str): Path to save file
        """
        output_file = Path(output_path)
        
        # Create parent directory if needed
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Write pretty-printed JSON
        with open(output_file, 'w') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"JSON saved to {output_file}")
    
    def get_section_completeness(self, state_data):
        """
        Get completeness summary for all sections (useful for debugging)
        
        Args:
            state_data (dict): State data
            
        Returns:
            dict: {section_name: completeness_info}
        """
        summary = {}
        
        for section_name in self.section_definitions.keys():
            section_output = self._process_section(section_name, state_data)
            status = section_output["_status"]
            
            summary[section_name] = {
                "complete": status["complete"],
                "present": status["fields_present"],
                "expected": status["fields_expected"],
                "percentage": round(
                    status["fields_present"] / status["fields_expected"] * 100, 1
                ) if status["fields_expected"] > 0 else 0.0
            }
        
        return summary