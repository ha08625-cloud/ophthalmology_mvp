"""
HuggingFace Client - Model loading and inference wrapper

Responsibilities:
- Load model with 4-bit quantization (QLoRA)
- Generate text completions
- Generate JSON-formatted completions with repair
- Handle CUDA errors
- Optional diagnostics (token counts, latency)
- Optional prompt formatting (via PromptFormatter)

Design principles:
- Dependency injection (no singleton)
- Fail fast on critical errors (CUDA OOM)
- Graceful handling of generation errors
- Model-agnostic (no formatting logic here)
"""

import torch
import json
import time
import logging
from typing import Optional, Dict, Any, Union
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig
)

from prompt_formatter import PromptFormatter

logger = logging.getLogger(__name__)

# Constants (Fix #3: Magic strings)
DEVICE_CUDA = "cuda"
DEVICE_CPU = "cpu"
DEVICE_MAP_AUTO = "auto"


class HuggingFaceClient:
    """Wrapper for HuggingFace model inference"""
    
    def __init__(
        self,
        model_name: str,
        load_in_4bit: bool = True,
        device: str = DEVICE_CUDA,
        auto_format: bool = True
    ) -> None:
        """
        Initialize model and tokenizer
        
        Args:
            model_name: HuggingFace model identifier
            load_in_4bit: Use 4-bit quantization (saves VRAM)
            device: Device to use ("cuda" or "cpu")
            auto_format: Auto-detect and apply prompt formatting
            
        Raises:
            RuntimeError: If CUDA requested but not available
            Exception: If model loading fails
        """
        self.model_name = model_name
        self.device = device
        self.auto_format = auto_format
        
        # Will be initialized after tokenizer is loaded
        self.formatter: Optional[PromptFormatter] = None
        
        # Validate CUDA availability
        if device == DEVICE_CUDA and not torch.cuda.is_available():
            raise RuntimeError("CUDA requested but not available. Check nvidia-smi.")
        
        logger.info(f"Loading model: {model_name}")
        logger.info(f"4-bit quantization: {load_in_4bit}")
        logger.info(f"Device: {device}")
        logger.info(f"Auto-format: {auto_format}")
        
        # Configure quantization if requested
        quantization_config = None
        if load_in_4bit and device == DEVICE_CUDA:
            quantization_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=torch.bfloat16,
                bnb_4bit_use_double_quant=True
            )
            logger.info("Using NF4 quantization with bfloat16 compute")
        
        # Load tokenizer
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(model_name)
            
            # Fix #4: Ensure pad_token is set
            if self.tokenizer.pad_token is None:
                if self.tokenizer.eos_token is not None:
                    self.tokenizer.pad_token = self.tokenizer.eos_token
                    logger.info("Set pad_token to eos_token")
                else:
                    # Last resort - add a new token
                    self.tokenizer.add_special_tokens({'pad_token': '[PAD]'})
                    logger.warning("Added new [PAD] token as pad_token")
            
            logger.info("Tokenizer loaded successfully")
            
        except Exception as e:
            logger.error(f"Failed to load tokenizer: {e}")
            raise
        
        # Initialize prompt formatter if requested
        if auto_format:
            self.formatter = PromptFormatter(model_name, self.tokenizer)
            logger.info(f"Prompt formatter initialized: {self.formatter.get_info()}")
        
        # Load model
        try:
            self.model = AutoModelForCausalLM.from_pretrained(
                model_name,
                quantization_config=quantization_config,
                device_map=DEVICE_MAP_AUTO if device == DEVICE_CUDA else None,
                trust_remote_code=True,
                torch_dtype=torch.bfloat16 if device == DEVICE_CUDA else torch.float32
            )
            logger.info("Model loaded successfully")
            
            # Log memory usage if CUDA
            if device == DEVICE_CUDA:
                self._log_cuda_memory("after model load")
                
        except torch.cuda.OutOfMemoryError:
            logger.error("CUDA Out of Memory during model loading")
            logger.error("Try: 1) Close other GPU applications, 2) Reduce model size, 3) Use CPU")
            raise
        except Exception as e:
            logger.error(f"Failed to load model: {e}")
            raise
        
        self.model.eval()  # Set to evaluation mode
        logger.info("HuggingFace client initialized successfully")
    
    def _log_cuda_memory(self, stage: str) -> None:
        """
        Log CUDA memory usage (Fix #6: Memory logging utility)
        
        Args:
            stage: Description of when this is called (e.g., "after model load")
        """
        if self.device == DEVICE_CUDA and torch.cuda.is_available():
            allocated = torch.cuda.memory_allocated() / 1e9
            reserved = torch.cuda.memory_reserved() / 1e9
            max_allocated = torch.cuda.max_memory_allocated() / 1e9
            logger.info(
                f"GPU memory {stage}: "
                f"{allocated:.2f}GB allocated, "
                f"{reserved:.2f}GB reserved, "
                f"{max_allocated:.2f}GB peak"
            )
    
    def is_loaded(self) -> bool:
        """
        Check if model is loaded and ready
        
        Returns:
            bool: True if model and tokenizer are loaded
        """
        return self.model is not None and self.tokenizer is not None
    
    def generate(
        self,
        prompt: str,
        max_tokens: int = 256,
        temperature: float = 0.3,
        return_diagnostics: bool = False,
        apply_formatting: bool = True
    ) -> Union[str, Dict[str, Any]]:
        """
        Generate text completion from prompt
        
        Args:
            prompt: Input prompt (plain text)
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature (0.0 = deterministic)
            return_diagnostics: Include token counts and timing
            apply_formatting: Apply prompt formatting if auto_format is enabled
            
        Returns:
            str: Generated text (if return_diagnostics=False)
            dict: {'text': str, 'diagnostics': {...}} (if return_diagnostics=True)
            
        Raises:
            RuntimeError: If model not loaded
            torch.cuda.OutOfMemoryError: If GPU runs out of memory
        """
        if not self.is_loaded():
            raise RuntimeError("Model not loaded")
        
        start_time = time.time()
        
        # Apply formatting if enabled (Fix #1: Model-agnostic design)
        if apply_formatting and self.formatter:
            original_prompt = prompt
            prompt = self.formatter.format_instruction(prompt)
            logger.debug(f"Applied formatting: {len(original_prompt)} → {len(prompt)} chars")
        
        # Tokenize input
        inputs = self.tokenizer(prompt, return_tensors="pt")
        if self.device == DEVICE_CUDA:
            inputs = inputs.to(DEVICE_CUDA)
        
        prompt_tokens = inputs.input_ids.shape[1]
        
        # Log memory before generation
        if self.device == DEVICE_CUDA:
            self._log_cuda_memory("before generation")
        
        # Generate
        try:
            with torch.no_grad():
                outputs = self.model.generate(
                    inputs.input_ids,
                    max_new_tokens=max_tokens,
                    temperature=temperature,
                    do_sample=temperature > 0,
                    pad_token_id=self.tokenizer.pad_token_id  # Fix #4: Use pad_token_id
                )
        except torch.cuda.OutOfMemoryError:
            logger.error("CUDA OOM during generation")
            logger.error(f"Prompt tokens: {prompt_tokens}, Max new: {max_tokens}")
            raise
        
        # Log memory after generation
        if self.device == DEVICE_CUDA:
            self._log_cuda_memory("after generation")
        
        # Decode output (skip prompt tokens)
        generated_ids = outputs[0][prompt_tokens:]
        generated_text = self.tokenizer.decode(generated_ids, skip_special_tokens=True)
        
        elapsed_ms = (time.time() - start_time) * 1000
        
        # Fix #8: Proper token counting (exclude pad tokens)
        completion_tokens = len([
            t for t in generated_ids 
            if t != self.tokenizer.pad_token_id
        ])
        
        if return_diagnostics:
            return {
                "text": generated_text,
                "diagnostics": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens,
                    "latency_ms": elapsed_ms,
                    "formatting_applied": apply_formatting and self.formatter is not None
                }
            }
        
        return generated_text
    
    def generate_json(
        self,
        prompt: str,
        max_tokens: int = 256,
        temperature: float = 0.0,
        return_diagnostics: bool = False,
        apply_formatting: bool = True
    ) -> Union[str, Dict[str, Any]]:
        """
        Generate JSON-formatted completion with repair attempts
        
        This method is optimized for structured output:
        - Uses temperature=0.0 by default (deterministic)
        - Strips common JSON formatting issues
        - Attempts basic brace balancing
        
        Args:
            prompt: Input prompt (should request JSON output)
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature (default 0.0 for consistency)
            return_diagnostics: Include token counts and timing
            apply_formatting: Apply prompt formatting if auto_format is enabled
            
        Returns:
            str: JSON string (possibly repaired)
            dict: {'text': str, 'diagnostics': {...}} (if return_diagnostics=True)
            
        Note: This returns a string, not parsed JSON. Caller must json.loads().
        """
        result = self.generate(
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            return_diagnostics=return_diagnostics,
            apply_formatting=apply_formatting
        )
        
        # Extract text (handle both string and dict return)
        if return_diagnostics:
            text = result["text"]
            diagnostics = result["diagnostics"]
        else:
            text = result
        
        # Clean and repair JSON (Fix #5: More conservative repair)
        repaired = self._repair_json(text)
        
        if return_diagnostics:
            diagnostics["json_repair_applied"] = repaired != text
            return {
                "text": repaired,
                "diagnostics": diagnostics
            }
        
        return repaired
    
    def _repair_json(self, text: str) -> str:
        """
        Attempt to repair common JSON formatting issues
        
        Fix #5: More conservative - only handles dict output (not arrays)
        Note: This is basic repair. For production, consider jsonrepair library.
        
        Args:
            text: Raw LLM output
            
        Returns:
            str: Cleaned JSON string
        """
        # Strip markdown code blocks
        text = text.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        
        text = text.strip()
        
        # Only handle dict output (not arrays)
        # Find first { and last }
        first_brace = text.find('{')
        last_brace = text.rfind('}')
        
        if first_brace == -1 or last_brace == -1:
            # No braces found - return as-is, will fail JSON parse
            logger.warning("No braces found in JSON repair")
            return text
        
        # Extract content between braces
        text = text[first_brace:last_brace + 1]
        
        # Basic brace balancing (naive - doesn't handle strings with braces)
        # TODO: Use proper JSON repair library for production
        open_count = text.count('{')
        close_count = text.count('}')
        
        if open_count > close_count:
            # Add missing closing braces
            missing = open_count - close_count
            text += '}' * missing
            logger.debug(f"Added {missing} closing braces")
            
        elif close_count > open_count:
            # Remove extra closing braces from end
            diff = close_count - open_count
            for _ in range(diff):
                last_close = text.rfind('}')
                if last_close != -1:
                    text = text[:last_close] + text[last_close + 1:]
            logger.debug(f"Removed {diff} extra closing braces")
        
        return text
    
    def get_model_info(self) -> Dict[str, Any]:
        """
        Get information about loaded model
        
        Returns:
            dict: Model metadata
        """
        info = {
            "model_name": self.model_name,
            "device": self.device,
            "is_loaded": self.is_loaded(),
            "auto_format": self.auto_format
        }
        
        if self.formatter:
            info["formatter"] = self.formatter.get_info()
        
        if self.device == DEVICE_CUDA and torch.cuda.is_available():
            info["gpu_memory_allocated_gb"] = torch.cuda.memory_allocated() / 1e9
            info["gpu_memory_reserved_gb"] = torch.cuda.memory_reserved() / 1e9
            info["gpu_memory_max_allocated_gb"] = torch.cuda.max_memory_allocated() / 1e9
        
        return info