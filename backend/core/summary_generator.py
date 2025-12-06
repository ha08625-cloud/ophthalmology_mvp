"""
Summary Generator - Generate clinical narratives from consultation dialogue

Responsibilities:
- Convert dialogue history into structured clinical summary
- Write in second person (patient-directed format)
- Group negative findings logically
- Follow schema section order
- Include relevant quotes from patient
- Note missing/incomplete data transparently

Design principles:
- Pure function (deterministic given same input)
- Stateless (doesn't mutate inputs)
- Replaceable (interface unchanged if implementation evolves)
"""

import logging
from backend.utils.hf_client import HuggingFaceClient

logger = logging.getLogger(__name__)


class SummaryGenerator:
    """Generate clinical summaries from consultation dialogue"""
    
    # Negative finding groups for readable summaries
    NEGATIVE_GROUPS = {
        "visual_disturbances": [
            "hallucinations", "colour vision problems", "flashing lights",
            "zigzags", "double vision", "dizziness", "abnormal eye movements"
        ],
        "eye_appearance": [
            "redness", "discharge", "bulging", "drooping eyelids",
            "pupillary changes", "rashes"
        ],
        "eye_sensations": [
            "eye pain", "dry sensation", "gritty sensation"
        ]
    }
    
    # Section names in order (matching schema structure)
    SECTION_ORDER = [
        "presenting_complaint",
        "vision_loss",
        "visual_disturbances",
        "headache",
        "eye_pain_and_changes",
        "healthcare_contacts",
        "other_symptoms",
        "functional_impact"
    ]
    
    # Section display names
    SECTION_TITLES = {
        "presenting_complaint": "PRESENTING COMPLAINT",
        "vision_loss": "VISION LOSS HISTORY",
        "visual_disturbances": "VISUAL DISTURBANCES",
        "headache": "HEADACHE",
        "eye_pain_and_changes": "EYE PAIN AND CHANGES",
        "healthcare_contacts": "HEALTHCARE CONTACTS",
        "other_symptoms": "OTHER SYMPTOMS",
        "functional_impact": "FUNCTIONAL IMPACT"
    }
    
    def __init__(self, hf_client):
        """
        Initialize Summary Generator
        
        Args:
            hf_client (HuggingFaceClient): Initialized model client
            
        Raises:
            TypeError: If hf_client is not HuggingFaceClient instance
        """
        if not isinstance(hf_client, HuggingFaceClient):
            raise TypeError("hf_client must be HuggingFaceClient instance")
        
        if not hf_client.is_loaded():
            raise RuntimeError("HuggingFace client model not loaded")
        
        self.hf_client = hf_client
        self.generation_mode = "single"  # Future: "sectional"
        
        logger.info("Summary Generator initialized")
    
    def generate(self, dialogue_history, structured_data, 
                 temperature=0.1, target_length="medium"):
        """
        Generate clinical summary from consultation data
        
        Pure function: same inputs always produce same output (at temperature=0)
        
        Args:
            dialogue_history (list): List of dialogue turn dicts
                Format: [{'question': str, 'response': str, 'extracted': dict}, ...]
            structured_data (dict): Extracted/validated field values
            temperature (float): LLM temperature (0.0-1.0, default 0.1)
            target_length (str): "concise" (200-300), "medium" (500-800), 
                                 "detailed" (1000+)
        
        Returns:
            str: Generated clinical summary text
            
        Raises:
            TypeError: If inputs are invalid types
        """
        # Validate inputs
        if not isinstance(dialogue_history, list):
            raise TypeError("dialogue_history must be list")
        if not isinstance(structured_data, dict):
            raise TypeError("structured_data must be dict")
        
        logger.info(f"Generating summary from {len(dialogue_history)} dialogue turns")
        logger.info(f"Structured data contains {len(structured_data)} fields")
        
        # Build prompt
        prompt = self._build_prompt(
            dialogue_history, 
            structured_data, 
            target_length
        )
        
        logger.debug(f"Prompt length: {len(prompt)} characters")
        
        # Generate summary
        try:
            summary_text = self.hf_client.generate(
                prompt=prompt,
                max_tokens=1500,
                temperature=temperature
            )
            
            logger.info("Summary generated successfully")
            
            # Clean up output
            summary_text = self._clean_summary(summary_text)
            
            logger.info(f"Final summary length: {len(summary_text)} characters")
            
            return summary_text
            
        except Exception as e:
            logger.error(f"Summary generation failed: {e}")
            raise
    
    def _build_prompt(self, dialogue_history, structured_data, target_length):
        """
        Build comprehensive summary generation prompt
        
        Args:
            dialogue_history (list): Dialogue turns
            structured_data (dict): Extracted fields
            target_length (str): Target length category
            
        Returns:
            str: Complete prompt for LLM
        """
        # Map target length to word count guidance
        length_guidance = {
            "concise": "200-300 words",
            "medium": "500-800 words",
            "detailed": "1000+ words"
        }
        word_count = length_guidance.get(target_length, "500-800 words")
        
        # Format dialogue history
        dialogue_text = self._format_dialogue(dialogue_history)
        
        # Format structured data
        data_text = self._format_structured_data(structured_data)
        
        # Build complete prompt
        prompt = f"""You are writing a clinical summary for a patient to review and validate.

STYLE GUIDELINES:
- Write in second person: "You report..." not "The patient reports..."
- Use clinical phrasing: "3-month history of..." not "3 months ago"
- Use "you describe", "you report", or "you note" (vary naturally)
- Target length: {word_count}
- Be thorough but concise
- Write in past tense for history

NEGATIVE FINDINGS:
Group related negatives together for readability.

Visual disturbances group: hallucinations, colour vision problems, flashing lights, zigzags, double vision, dizziness, abnormal eye movements

Eye appearance group: redness, discharge, bulging (proptosis), drooping eyelids (ptosis), pupillary changes, rashes

Eye sensations group: eye pain, dry sensation, gritty sensation

Examples:
- "You report no visual disturbances: no hallucinations, colour vision problems, flashing lights, zigzags, double vision, dizziness, or abnormal eye movements."
- "You report no changes to eye appearance: no redness, discharge, bulging, drooping eyelids, pupillary changes, or rashes."
- If one positive: "You report a rash around the eyes, but no redness, discharge, bulging, drooping eyelids, or pupillary changes."

SECTIONS (write in this exact order):
1. OVERVIEW (2-3 sentence summary of main issues)
2. PRESENTING COMPLAINT
3. VISION LOSS HISTORY
4. VISUAL DISTURBANCES
5. HEADACHE
6. EYE PAIN AND CHANGES
7. HEALTHCARE CONTACTS
8. OTHER SYMPTOMS
9. FUNCTIONAL IMPACT

For sections with no data, write: "[Information not captured during consultation]"

QUOTES:
When quoting the patient, use their EXACT words from the dialogue.
Do not paraphrase within quotation marks.
Only quote when it adds clinical value (vivid descriptions, functional impact).

DATA SOURCES:
PRIMARY SOURCE: The dialogue history below (what the patient actually said)
REFERENCE: The structured data below (extracted facts for verification)

If dialogue and structured data conflict, prioritize the dialogue.

===== DIALOGUE HISTORY =====
{dialogue_text}

===== STRUCTURED DATA (for reference) =====
{data_text}

===== END OF INPUT =====

Generate the clinical summary now, following the structure and guidelines above:
"""
        
        return prompt
    
    def _format_dialogue(self, dialogue_history):
        """
        Format dialogue history for prompt
        
        Args:
            dialogue_history (list): Dialogue turns
            
        Returns:
            str: Formatted dialogue text
        """
        if not dialogue_history:
            return "[No dialogue recorded]"
        
        formatted = []
        for i, turn in enumerate(dialogue_history, 1):
            question = turn.get('question', '[No question]')
            response = turn.get('response', '[No response]')
            
            formatted.append(f"Turn {i}:")
            formatted.append(f"  Question: {question}")
            formatted.append(f"  Patient: {response}")
            formatted.append("")  # Blank line
        
        return "\n".join(formatted)
    
    def _format_structured_data(self, structured_data):
        """
        Format structured data for prompt
        
        Args:
            structured_data (dict): Extracted fields
            
        Returns:
            str: Formatted data text
        """
        if not structured_data:
            return "[No structured data available]"
        
        # Group by section (using field prefixes)
        sections = {}
        for field_name, value in structured_data.items():
            if field_name.startswith('_'):
                continue
            
            # Determine section from prefix
            if field_name.startswith('vl_'):
                section = "Vision Loss"
            elif field_name.startswith('h_'):
                section = "Headache"
            elif field_name.startswith('ep_') or field_name.startswith('ac_'):
                section = "Eye Pain/Changes"
            elif field_name.startswith('cp_') or field_name.startswith('vp_') or field_name.startswith('dp_'):
                section = "Visual Disturbances"
            elif field_name.startswith('hc_'):
                section = "Healthcare Contacts"
            elif 'presenting_complaint' in field_name or 'previous_instances' in field_name:
                section = "Presenting Complaint"
            else:
                section = "Other"
            
            if section not in sections:
                sections[section] = []
            
            sections[section].append(f"  {field_name}: {value}")
        
        # Format output
        formatted = []
        for section_name in sorted(sections.keys()):
            formatted.append(f"{section_name}:")
            formatted.extend(sections[section_name])
            formatted.append("")
        
        return "\n".join(formatted)
    
    def _clean_summary(self, summary_text):
        """
        Clean up generated summary text
        
        Args:
            summary_text (str): Raw LLM output
            
        Returns:
            str: Cleaned summary
        """
        # Strip markdown code blocks if present
        text = summary_text.strip()
        
        if text.startswith("```"):
            # Remove opening markdown
            lines = text.split('\n')
            if lines[0].startswith("```"):
                lines = lines[1:]
            # Remove closing markdown
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            text = '\n'.join(lines)
        
        # Remove extra blank lines (more than 2 consecutive)
        while '\n\n\n' in text:
            text = text.replace('\n\n\n', '\n\n')
        
        # Strip leading/trailing whitespace
        text = text.strip()
        
        return text
    
    def save_summary(self, summary_text, output_path):
        """
        Save summary to text file
        
        This is a helper method - the core generate() method just returns text.
        Caller can use this if they want to save to file.
        
        Args:
            summary_text (str): Summary text to save
            output_path (str): Path to save file
        """
        from pathlib import Path
        
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_file, 'w') as f:
            f.write(summary_text)
        
        logger.info(f"Summary saved to {output_file}")