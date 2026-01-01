"""
Summary Generator V2 - Multi-episode clinical narrative generation

Responsibilities:
- Generate per-episode summaries using LLM
- Format shared data as simple lists (no LLM)
- Deterministic assembly of complete summary
- Token usage tracking and warnings

Design principles:
- Chunked generation (per episode) to manage token limits
- Deterministic assembly (no LLM hallucination risk)
- Simple shared data formatting (lists, no generative text)
- Per-episode negative findings
"""

import logging
from typing import Dict, Any, List, Optional
from backend.utils.hf_client_v2 import HuggingFaceClient

logger = logging.getLogger(__name__)


class SummaryGeneratorV2:
    """Generate clinical summaries from multi-episode consultations"""
    
    # Negative finding groups for readable summaries (from V1)
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
    
    def __init__(self, hf_client):
        """
        Initialize Summary Generator V2
        
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
        
        logger.info("Summary Generator V2 initialized")
    
    # ==================== PUBLIC API ====================
    
    def generate(self, consultation_data: dict, temperature: float = 0.1) -> str:
        """
        Generate complete consultation summary from multi-episode data
        
        Pure function: same inputs always produce same output (at temperature=0)
        
        Args:
            consultation_data: Output from state.export_for_summary()
                Expected structure:
                {
                    'episodes': [list of episode dicts],
                    'shared_data': {shared data dict},
                    'dialogue_history': {episode_id: [turns]}
                }
            temperature: LLM temperature (0.0-1.0, default 0.1)
        
        Returns:
            str: Generated clinical summary text
            
        Raises:
            TypeError: If inputs are invalid types
            
        Example:
            >>> generator = SummaryGeneratorV2(hf_client)
            >>> summary_data = state.export_for_summary()
            >>> summary_text = generator.generate(summary_data)
        """
        # Validate inputs
        if not isinstance(consultation_data, dict):
            raise TypeError("consultation_data must be dict")
        
        if 'episodes' not in consultation_data:
            raise ValueError("consultation_data missing 'episodes' key")
        
        if 'shared_data' not in consultation_data:
            raise ValueError("consultation_data missing 'shared_data' key")
        
        if 'dialogue_history' not in consultation_data:
            raise ValueError("consultation_data missing 'dialogue_history' key")
        
        episodes = consultation_data['episodes']
        shared_data = consultation_data['shared_data']
        dialogue_history = consultation_data['dialogue_history']
        
        logger.info(f"Generating summary for {len(episodes)} episode(s)")
        
        # Track token usage
        total_tokens = 0
        
        # Generate episode summaries
        episode_summaries = []
        for i, episode in enumerate(episodes, 1):
            episode_id = episode.get('episode_id', i)
            episode_turns = dialogue_history.get(episode_id, [])
            
            logger.info(f"Generating summary for episode {episode_id}")
            
            # Estimate tokens before generation
            estimated_tokens = self._estimate_episode_tokens(episode, episode_turns)
            total_tokens += estimated_tokens
            
            if estimated_tokens > 4000:
                logger.warning(
                    f"Episode {episode_id} dialogue is large (~{estimated_tokens} tokens). "
                    f"Summary generation may be slow."
                )
            
            # Generate episode summary
            episode_summary = self._generate_episode_summary(
                episode_data=episode,
                dialogue_turns=episode_turns,
                episode_number=i,
                temperature=temperature
            )
            
            episode_summaries.append(episode_summary)
        
        # Check total token usage
        if total_tokens > 25000:
            logger.warning(
                f"Total consultation is very large (~{total_tokens} tokens). "
                f"Approaching 32k context limit."
            )
        
        # Format shared data (deterministic, no LLM)
        shared_data_text = self._format_shared_data(shared_data)
        
        # Assemble final summary (deterministic)
        complete_summary = self._assemble_summary(episode_summaries, shared_data_text)
        
        logger.info(f"Summary generated successfully ({len(complete_summary)} characters)")
        
        return complete_summary
    
    def save_summary(self, summary_text: str, output_path: str) -> None:
        """
        Save summary to text file
        
        This is a helper method - the core generate() method just returns text.
        Caller can use this if they want to save to file.
        
        Args:
            summary_text: Summary text to save
            output_path: Path to save file
        """
        from pathlib import Path
        
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_file, 'w') as f:
            f.write(summary_text)
        
        logger.info(f"Summary saved to {output_file}")
    
    def generate_and_save(self, consultation_data: dict, output_path: str, 
                         temperature: float = 0.1) -> str:
        """
        Generate summary and save to file (combined operation)
        
        This method owns the complete persistence lifecycle for DialogueManager.
        
        Args:
            consultation_data: Output from state.export_for_summary()
            output_path: Path to save file
            temperature: LLM temperature
            
        Returns:
            str: Absolute path to saved file
            
        Raises:
            TypeError: If inputs invalid
            OSError: If file cannot be written
        """
        # Generate
        summary_text = self.generate(consultation_data, temperature)
        
        # Save
        self.save_summary(summary_text, output_path)
        
        # Return absolute path
        from pathlib import Path
        return str(Path(output_path).absolute())
    
    # ==================== EPISODE GENERATION ====================
    
    def _generate_episode_summary(
        self, 
        episode_data: dict, 
        dialogue_turns: List[dict],
        episode_number: int,
        temperature: float
    ) -> str:
        """
        Generate summary for single episode using LLM
        
        Args:
            episode_data: Episode dict from episodes array
            dialogue_turns: Dialogue history for this episode
            episode_number: Which episode (1, 2, 3...)
            temperature: LLM temperature
            
        Returns:
            str: Episode narrative
        """
        # Build prompt
        prompt = self._build_episode_prompt(
            episode_data=episode_data,
            dialogue_turns=dialogue_turns,
            episode_number=episode_number
        )
        
        logger.debug(f"Episode {episode_number} prompt length: {len(prompt)} characters")
        
        # Generate summary
        try:
            summary_text = self.hf_client.generate(
                prompt=prompt,
                max_tokens=800,  # ~300-500 words target
                temperature=temperature
            )
            
            # Clean up output
            summary_text = self._clean_summary(summary_text)
            
            logger.info(f"Episode {episode_number} summary generated ({len(summary_text)} characters)")
            
            return summary_text
            
        except Exception as e:
            logger.error(f"Episode {episode_number} summary generation failed: {e}")
            raise
    
    def _build_episode_prompt(
        self,
        episode_data: dict,
        dialogue_turns: List[dict],
        episode_number: int
    ) -> str:
        """
        Build prompt for episode summary generation
        
        Similar to V1 prompt but:
        - Adds episode number context
        - Includes "In this episode" framing
        - Per-episode negative findings
        - Shorter target length (300-500 words)
        
        Args:
            episode_data: Episode fields
            dialogue_turns: Dialogue for this episode
            episode_number: Which episode
            
        Returns:
            str: Complete prompt for LLM
        """
        # Format dialogue history
        dialogue_text = self._format_dialogue_for_prompt(dialogue_turns)
        
        # Format structured data
        data_text = self._format_episode_data_for_prompt(episode_data)
        
        # Build complete prompt
        prompt = f"""You are writing a clinical summary for episode {episode_number} of a consultation.

STYLE GUIDELINES:
- Write in second person: "In this episode, you report..." or "You describe..."
- Use past tense for history
- Use clinical phrasing: "3-month history of..." not "3 months ago"
- Vary naturally: "you describe", "you report", "you note"
- Target length: 300-500 words
- Be thorough but concise

NEGATIVE FINDINGS:
Group related negatives together for readability.

Visual disturbances group: hallucinations, colour vision problems, flashing lights, zigzags, double vision, dizziness, abnormal eye movements

Eye appearance group: redness, discharge, bulging (proptosis), drooping eyelids (ptosis), pupillary changes, rashes

Eye sensations group: eye pain, dry sensation, gritty sensation

Examples:
- "In this episode, you report no visual disturbances: no hallucinations, colour vision problems, flashing lights, zigzags, double vision, dizziness, or abnormal eye movements."
- "In this episode, you report no changes to eye appearance: no redness, discharge, bulging, drooping eyelids, pupillary changes, or rashes."
- If one positive: "In this episode, you report a rash around the eyes, but no redness, discharge, bulging, drooping eyelids, or pupillary changes."

FRAMING:
Start the narrative with "In this episode" to clearly indicate this is one of potentially multiple episodes.

QUOTES:
When quoting the patient, use their EXACT words from the dialogue.
Do not paraphrase within quotation marks.
Only quote when it adds clinical value (vivid descriptions, functional impact).

DATA SOURCES:
PRIMARY SOURCE: The dialogue history below (what the patient actually said)
REFERENCE: The structured data below (extracted facts for verification)

If dialogue and structured data conflict, prioritize the dialogue.

===== DIALOGUE HISTORY FOR EPISODE {episode_number} =====
{dialogue_text}

===== EXTRACTED DATA FOR EPISODE {episode_number} =====
{data_text}

===== END OF INPUT =====

Generate the clinical summary for this episode now, starting with "In this episode":
"""
        
        return prompt
    
    # ==================== SHARED DATA FORMATTING ====================
    
    def _format_shared_data(self, shared_data: dict) -> str:
        """
        Format shared data as simple lists (no LLM)
        
        Returns formatted strings for:
        - Past medical history
        - Medications
        - Family history
        - Allergies
        - Social history
        
        Args:
            shared_data: Shared data dict from consultation
            
        Returns:
            str: Formatted shared data text
        """
        sections = []
        
        # Past Medical History
        pmh = shared_data.get('past_medical_history', [])
        pmh_text = self._format_pmh(pmh)
        sections.append(pmh_text)
        
        # Medications
        meds = shared_data.get('medications', [])
        meds_text = self._format_medications(meds)
        sections.append(meds_text)
        
        # Family History
        fh = shared_data.get('family_history', [])
        fh_text = self._format_family_history(fh)
        sections.append(fh_text)
        
        # Allergies
        allergies = shared_data.get('allergies', [])
        allergies_text = self._format_allergies(allergies)
        sections.append(allergies_text)
        
        # Social History
        social_history = shared_data.get('social_history', {})
        social_text = self._format_social_history(social_history)
        sections.append(social_text)
        
        # Join with triple newlines
        return "\n\n\n".join(sections)
    
    def _format_pmh(self, pmh_array: List[dict]) -> str:
        """
        Format past medical history list
        
        Args:
            pmh_array: List of PMH items
            
        Returns:
            str: Formatted PMH section
        """
        lines = ["Past Medical History"]
        
        if not pmh_array:
            lines.append("None reported")
        else:
            for i, item in enumerate(pmh_array, 1):
                condition = item.get('condition', 'Unknown condition')
                diagnosed = item.get('diagnosed_when', '')
                status = item.get('current_status', '')
                
                # Build item string
                item_str = f"{i}. {condition}"
                
                if diagnosed:
                    item_str += f" (diagnosed: {diagnosed}"
                    if status:
                        item_str += f", status: {status})"
                    else:
                        item_str += ")"
                elif status:
                    item_str += f" (status: {status})"
                
                lines.append(item_str)
        
        return "\n".join(lines)
    
    def _format_medications(self, meds_array: List[dict]) -> str:
        """
        Format medications list
        
        Args:
            meds_array: List of medication items
            
        Returns:
            str: Formatted medications section
        """
        lines = ["Medications"]
        
        if not meds_array:
            lines.append("None reported")
        else:
            for i, item in enumerate(meds_array, 1):
                med_name = item.get('medication_name', 'Unknown medication')
                dose = item.get('dose', '')
                frequency = item.get('frequency', '')
                indication = item.get('indication', '')
                
                # Build item string
                item_str = f"{i}. {med_name}"
                
                if dose:
                    item_str += f" - {dose}"
                if frequency:
                    item_str += f" - {frequency}"
                if indication:
                    item_str += f" - {indication}"
                
                lines.append(item_str)
        
        return "\n".join(lines)
    
    def _format_family_history(self, fh_array: List[dict]) -> str:
        """
        Format family history list
        
        Args:
            fh_array: List of family history items
            
        Returns:
            str: Formatted family history section
        """
        lines = ["Family History"]
        
        if not fh_array:
            lines.append("None reported")
        else:
            for i, item in enumerate(fh_array, 1):
                condition = item.get('condition', 'Unknown condition')
                relationship = item.get('relationship', 'Unknown relation')
                
                item_str = f"{i}. {condition} - {relationship}"
                lines.append(item_str)
        
        return "\n".join(lines)
    
    def _format_allergies(self, allergies_array: List[dict]) -> str:
        """
        Format allergies list
        
        Args:
            allergies_array: List of allergy items
            
        Returns:
            str: Formatted allergies section
        """
        lines = ["Allergies"]
        
        if not allergies_array:
            lines.append("None reported")
        else:
            for i, item in enumerate(allergies_array, 1):
                allergen = item.get('allergen', 'Unknown allergen')
                reaction = item.get('reaction', '')
                
                item_str = f"{i}. {allergen}"
                if reaction:
                    item_str += f" - {reaction}"
                
                lines.append(item_str)
        
        return "\n".join(lines)
    
    def _format_social_history(self, social_history_obj: dict) -> str:
        """
        Format social history from nested object
        
        Args:
            social_history_obj: Social history nested dict
            
        Returns:
            str: Formatted social history section
        """
        lines = ["Social History"]
        
        # Smoking
        smoking = social_history_obj.get('smoking', {})
        smoking_status = smoking.get('status')
        pack_years = smoking.get('pack_years')
        
        if smoking_status == 'never':
            lines.append("Smoking: Never smoked")
        elif smoking_status == 'current':
            if pack_years:
                lines.append(f"Smoking: Current smoker ({pack_years} pack-years)")
            else:
                lines.append("Smoking: Current smoker")
        elif smoking_status == 'former':
            if pack_years:
                lines.append(f"Smoking: Former smoker ({pack_years} pack-years)")
            else:
                lines.append("Smoking: Former smoker")
        elif smoking_status:
            lines.append(f"Smoking: {smoking_status}")
        
        # Alcohol
        alcohol = social_history_obj.get('alcohol', {})
        units_per_week = alcohol.get('units_per_week')
        alcohol_type = alcohol.get('type')
        
        if units_per_week == 0:
            lines.append("Alcohol: Never drinks alcohol")
        elif units_per_week:
            if alcohol_type:
                lines.append(f"Alcohol: {units_per_week} units per week ({alcohol_type})")
            else:
                lines.append(f"Alcohol: {units_per_week} units per week")
        
        # Illicit drugs
        drugs = social_history_obj.get('illicit_drugs', {})
        drug_status = drugs.get('status')
        drug_type = drugs.get('type')
        drug_frequency = drugs.get('frequency')
        
        if drug_status == 'never':
            lines.append("Illicit drugs: Never used illicit drugs")
        elif drug_status == 'current':
            if drug_type and drug_frequency:
                lines.append(f"Illicit drugs: Current use ({drug_type}, {drug_frequency})")
            elif drug_type:
                lines.append(f"Illicit drugs: Current use ({drug_type})")
            else:
                lines.append("Illicit drugs: Current use")
        elif drug_status == 'former':
            if drug_type:
                lines.append(f"Illicit drugs: Former use ({drug_type})")
            else:
                lines.append("Illicit drugs: Former use")
        elif drug_status:
            lines.append(f"Illicit drugs: {drug_status}")
        
        # Occupation
        occupation = social_history_obj.get('occupation', {})
        current_occupation = occupation.get('current')
        past_occupation = occupation.get('past')
        
        if current_occupation:
            lines.append(f"Occupation: {current_occupation}")
        if past_occupation:
            lines.append(f"Past occupation: {past_occupation}")
        
        # If no social history data at all
        if len(lines) == 1:  # Only header
            lines.append("None reported")
        
        return "\n".join(lines)
    
    # ==================== ASSEMBLY ====================
    
    def _assemble_summary(
        self,
        episode_summaries: List[str],
        shared_data_text: str
    ) -> str:
        """
        Deterministic assembly of all sections
        
        No LLM - just string concatenation with proper separators.
        
        Args:
            episode_summaries: List of episode narrative strings
            shared_data_text: Formatted shared data string
            
        Returns:
            str: Complete assembled summary
        """
        sections = []
        
        # Add episode narratives with double newline separators
        for episode_summary in episode_summaries:
            sections.append(episode_summary)
        
        # Add shared data with triple newline separator
        sections.append(shared_data_text)
        
        # Join with double newlines between episodes
        # Triple newlines before shared data
        if len(episode_summaries) > 0:
            # Episodes first
            episodes_text = "\n\n".join(episode_summaries)
            # Then shared data with triple newline separator
            complete_summary = episodes_text + "\n\n\n" + shared_data_text
        else:
            # No episodes (shouldn't happen, but handle gracefully)
            complete_summary = shared_data_text
        
        return complete_summary
    
    # ==================== UTILITIES ====================
    
    def _estimate_episode_tokens(self, episode_data: dict, dialogue_turns: List[dict]) -> int:
        """
        Rough token count estimate for an episode
        
        Uses simple heuristic: characters / 4
        
        Args:
            episode_data: Episode fields
            dialogue_turns: Dialogue history
            
        Returns:
            int: Estimated token count
        """
        # Estimate dialogue tokens
        dialogue_text = self._format_dialogue_for_prompt(dialogue_turns)
        dialogue_tokens = len(dialogue_text) // 4
        
        # Estimate data tokens
        data_text = str(episode_data)
        data_tokens = len(data_text) // 4
        
        # Prompt template adds ~300 tokens
        total_estimate = dialogue_tokens + data_tokens + 300
        
        return total_estimate
    
    def _format_dialogue_for_prompt(self, dialogue_turns: List[dict]) -> str:
        """
        Format dialogue history for prompt inclusion
        
        Args:
            dialogue_turns: List of dialogue turn dicts
            
        Returns:
            str: Formatted dialogue text
        """
        if not dialogue_turns:
            return "[No dialogue recorded]"
        
        formatted = []
        for turn in dialogue_turns:
            turn_id = turn.get('turn_id', '?')
            question = turn.get('question', '[No question]')
            response = turn.get('response', '[No response]')
            
            formatted.append(f"Turn {turn_id}:")
            formatted.append(f"  Question: {question}")
            formatted.append(f"  Patient: {response}")
            formatted.append("")  # Blank line
        
        return "\n".join(formatted)
    
    def _format_episode_data_for_prompt(self, episode_data: dict) -> str:
        """
        Format episode structured data for prompt inclusion
        
        Args:
            episode_data: Episode fields dict
            
        Returns:
            str: Formatted data text
        """
        if not episode_data:
            return "[No structured data available]"
        
        # Skip operational fields
        skip_fields = {
            'episode_id', 'timestamp_started', 'timestamp_last_updated',
            'questions_answered', 'follow_up_blocks_activated', 
            'follow_up_blocks_completed'
        }
        
        formatted = []
        for field_name, value in episode_data.items():
            if field_name in skip_fields:
                continue
            if field_name.startswith('_'):
                continue
            
            formatted.append(f"  {field_name}: {value}")
        
        return "\n".join(formatted) if formatted else "[No clinical data]"
    
    def _clean_summary(self, summary_text: str) -> str:
        """
        Clean up generated summary text
        
        Removes markdown code blocks, extra whitespace, etc.
        
        Args:
            summary_text: Raw LLM output
            
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