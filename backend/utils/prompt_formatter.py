"""
Prompt Formatter - Model-specific prompt formatting

Responsibilities:
- Detect model family from model name
- Apply model-specific instruction formatting
- Use tokenizer chat template if available
- Fallback to manual formatting for known families

Design principles:
- Tokenizer template priority (most robust)
- Manual fallback for known families
- Generic passthrough for unknown models
- Stateless formatting (no side effects)
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class PromptFormatter:
    """Format prompts for specific model families"""
    
    # Known model families and their manual formatting
    MANUAL_FORMATS = {
        "mistral": lambda prompt: f"[INST] {prompt} [/INST]",
        "mixtral": lambda prompt: f"[INST] {prompt} [/INST]",
        "llama": lambda prompt: f"[INST] {prompt} [/INST]",
        "llama-2": lambda prompt: f"[INST] {prompt} [/INST]",
        "llama-3": lambda prompt: f"<|begin_of_text|><|start_header_id|>user<|end_header_id|>\n\n{prompt}<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n",
        "zephyr": lambda prompt: f"<|user|>\n{prompt}\n<|assistant|>\n",
        "phi": lambda prompt: f"<|user|>\n{prompt}<|end|>\n<|assistant|>\n",
    }
    
    def __init__(self, model_name: str, tokenizer=None):
        """
        Initialize formatter
        
        Args:
            model_name: HuggingFace model identifier
            tokenizer: Optional tokenizer with chat_template attribute
        """
        self.model_name = model_name
        self.tokenizer = tokenizer
        self.model_family = self._detect_model_family(model_name)
        
        # Check if tokenizer has chat template
        self.has_chat_template = (
            tokenizer is not None and 
            hasattr(tokenizer, 'chat_template') and 
            tokenizer.chat_template is not None
        )
        
        if self.has_chat_template:
            logger.info(f"Using tokenizer chat template for {model_name}")
        elif self.model_family in self.MANUAL_FORMATS:
            logger.info(f"Using manual formatting for {self.model_family} family")
        else:
            logger.warning(
                f"No chat template or known format for {model_name}. "
                f"Using generic (no formatting)"
            )
    
    def _detect_model_family(self, model_name: str) -> str:
        """
        Detect model family from model name
        
        Args:
            model_name: Full model identifier
            
        Returns:
            str: Model family identifier
        """
        name_lower = model_name.lower()
        
        # Check for specific families (order matters - most specific first)
        if "llama-3" in name_lower or "llama3" in name_lower:
            return "llama-3"
        elif "llama-2" in name_lower or "llama2" in name_lower:
            return "llama-2"
        elif "llama" in name_lower:
            return "llama"
        elif "mixtral" in name_lower:
            return "mixtral"
        elif "mistral" in name_lower:
            return "mistral"
        elif "zephyr" in name_lower:
            return "zephyr"
        elif "phi" in name_lower:
            return "phi"
        else:
            return "generic"
    
    def format_instruction(self, prompt: str) -> str:
        """
        Format prompt with model-specific instruction tags
        
        Priority:
        1. Tokenizer chat template (if available)
        2. Manual formatting for known family
        3. Generic passthrough (no formatting)
        
        Args:
            prompt: Plain text prompt
            
        Returns:
            str: Formatted prompt ready for model
            
        Examples:
            >>> formatter = PromptFormatter("mistralai/Mistral-7B-Instruct-v0.2")
            >>> formatter.format_instruction("What is 2+2?")
            '[INST] What is 2+2? [/INST]'
        """
        # Priority 1: Use tokenizer chat template
        if self.has_chat_template:
            try:
                # Format as single-turn conversation
                messages = [{"role": "user", "content": prompt}]
                formatted = self.tokenizer.apply_chat_template(
                    messages,
                    tokenize=False,
                    add_generation_prompt=True
                )
                logger.debug(f"Applied tokenizer chat template")
                return formatted
                
            except Exception as e:
                logger.warning(
                    f"Tokenizer chat template failed: {e}. "
                    f"Falling back to manual formatting"
                )
                # Fall through to manual formatting
        
        # Priority 2: Manual formatting for known family
        if self.model_family in self.MANUAL_FORMATS:
            formatted = self.MANUAL_FORMATS[self.model_family](prompt)
            logger.debug(f"Applied manual {self.model_family} formatting")
            return formatted
        
        # Priority 3: Generic passthrough (no formatting)
        logger.debug("No formatting applied (generic model)")
        return prompt
    
    def get_info(self) -> dict:
        """
        Get formatter information
        
        Returns:
            dict: Formatter metadata
        """
        return {
            "model_name": self.model_name,
            "model_family": self.model_family,
            "has_chat_template": self.has_chat_template,
            "formatting_method": (
                "tokenizer_template" if self.has_chat_template 
                else "manual" if self.model_family in self.MANUAL_FORMATS
                else "none"
            )
        }