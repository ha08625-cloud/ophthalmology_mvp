"""
HuggingFace Client - Model loading and inference wrapper

Responsibilities:
- Load model with 4-bit quantization (QLoRA)
- Generate text completions
- Generate JSON-formatted completions with repair
- Handle CUDA errors
- Optional diagnostics (token counts, latency)

Design principles:
- Dependency injection (no singleton)
- Fail fast on critical errors (CUDA OOM)
- Graceful handling of generation errors
"""

import torch
import json
import time
import logging
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig
)

logger = logging.getLogger(__name__)


class HuggingFaceClient:
    """Wrapper for HuggingFace model inference"""
    
    def __init__(self, model_name, load_in_4bit=True, device="cuda"):
        """
        Initialize model and tokenizer
        
        Args:
            model_name (str): HuggingFace model identifier
            load_in_4bit (bool): Use 4-bit quantization (saves VRAM)
            device (str): Device to use ("cuda" or "cpu")
            
        Raises:
            RuntimeError: If CUDA requested but not available
            Exception: If model loading fails
        """
        self.model_name = model_name
        self.device = device
        
        # Validate CUDA availability
        if device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("CUDA requested but not available. Check nvidia-smi.")
        
        logger.info(f"Loading model: {model_name}")
        logger.info(f"4-bit quantization: {load_in_4bit}")
        logger.info(f"Device: {device}")
        
        # Configure quantization if requested
        quantization_config = None
        if load_in_4bit and device == "cuda":
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
            logger.info("Tokenizer loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load tokenizer: {e}")
            raise
        
        # Load model
        try:
            self.model = AutoModelForCausalLM.from_pretrained(
                model_name,
                quantization_config=quantization_config,
                device_map="auto" if device == "cuda" else None,
                trust_remote_code=True,
                torch_dtype=torch.bfloat16 if device == "cuda" else torch.float32
            )
            logger.info("Model loaded successfully")
            
            # Log memory usage if CUDA
            if device == "cuda":
                allocated = torch.cuda.memory_allocated() / 1e9
                reserved = torch.cuda.memory_reserved() / 1e9
                logger.info(f"GPU memory: {allocated:.2f}GB allocated, {reserved:.2f}GB reserved")
                
        except torch.cuda.OutOfMemoryError:
            logger.error("CUDA Out of Memory during model loading")
            logger.error("Try: 1) Close other GPU applications, 2) Reduce model size, 3) Use CPU")
            raise
        except Exception as e:
            logger.error(f"Failed to load model: {e}")
            raise
        
        self.model.eval()  # Set to evaluation mode
        logger.info("HuggingFace client initialized successfully")
    
    def is_loaded(self):
        """
        Check if model is loaded and ready
        
        Returns:
            bool: True if model and tokenizer are loaded
        """
        return self.model is not None and self.tokenizer is not None
    
    def generate(self, prompt, max_tokens=256, temperature=0.3, return_diagnostics=False):
        """
        Generate text completion from prompt
        
        Args:
            prompt (str): Input prompt
            max_tokens (int): Maximum tokens to generate
            temperature (float): Sampling temperature (0.0 = deterministic)
            return_diagnostics (bool): Include token counts and timing
            
        Returns:
            str: Generated text (if return_diagnostics=False)
            dict: {'text': str, 'diagnostics': {...}} (if return_diagnostics=True)
            
        Raises:
            torch.cuda.OutOfMemoryError: If GPU runs out of memory
        """
        if not self.is_loaded():
            raise RuntimeError("Model not loaded")
        
        start_time = time.time()
        
        # Tokenize input
        inputs = self.tokenizer(prompt, return_tensors="pt")
        if self.device == "cuda":
            inputs = inputs.to("cuda")
        
        prompt_tokens = inputs.input_ids.shape[1]
        
        # Generate
        try:
            with torch.no_grad():
                outputs = self.model.generate(
                    inputs.input_ids,
                    max_new_tokens=max_tokens,
                    temperature=temperature,
                    do_sample=temperature > 0,
                    pad_token_id=self.tokenizer.eos_token_id
                )
        except torch.cuda.OutOfMemoryError:
            logger.error("CUDA OOM during generation")
            logger.error(f"Prompt tokens: {prompt_tokens}, Max new: {max_tokens}")
            raise
        
        # Decode output (skip prompt tokens)
        generated_ids = outputs[0][prompt_tokens:]
        generated_text = self.tokenizer.decode(generated_ids, skip_special_tokens=True)
        
        elapsed_ms = (time.time() - start_time) * 1000
        completion_tokens = len(generated_ids)
        
        if return_diagnostics:
            return {
                "text": generated_text,
                "diagnostics": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens,
                    "latency_ms": elapsed_ms
                }
            }
        
        return generated_text
    
    def generate_json(self, prompt, max_tokens=256, temperature=0.0, return_diagnostics=False):
        """
        Generate JSON-formatted completion with repair attempts
        
        This method is optimized for structured output:
        - Uses temperature=0.0 by default (deterministic)
        - Strips common JSON formatting issues
        - Attempts basic brace balancing
        
        Args:
            prompt (str): Input prompt (should request JSON output)
            max_tokens (int): Maximum tokens to generate
            temperature (float): Sampling temperature (default 0.0 for consistency)
            return_diagnostics (bool): Include token counts and timing
            
        Returns:
            str: JSON string (possibly repaired)
            dict: {'text': str, 'diagnostics': {...}} (if return_diagnostics=True)
            
        Note: This returns a string, not parsed JSON. Caller must json.loads().
        """
        result = self.generate(
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            return_diagnostics=return_diagnostics
        )
        
        # Extract text (handle both string and dict return)
        if return_diagnostics:
            text = result["text"]
            diagnostics = result["diagnostics"]
        else:
            text = result
        
        # Clean and repair JSON
        repaired = self._repair_json(text)
        
        if return_diagnostics:
            return {
                "text": repaired,
                "diagnostics": diagnostics
            }
        
        return repaired
    
    def _repair_json(self, text):
        """
        Attempt to repair common JSON formatting issues
        
        Args:
            text (str): Raw LLM output
            
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
        
        # Find first { and last }
        first_brace = text.find('{')
        last_brace = text.rfind('}')
        
        if first_brace == -1 or last_brace == -1:
            # No braces found - return as-is, will fail JSON parse
            return text
        
        # Extract ONLY content between first { and first }
        # This handles "extra data" after JSON
        open_count = 0
        end_pos = first_brace
        
        for i in range(first_brace, len(text)):
            if text[i] == '{':
                open_count += 1
            elif text[i] == '}':
                open_count -= 1
                if open_count == 0:
                    end_pos = i + 1
                    break

        text = text[first_brace:end_pos]
        return text
    
    def get_model_info(self):
        """
        Get information about loaded model
        
        Returns:
            dict: Model metadata
        """
        info = {
            "model_name": self.model_name,
            "device": self.device,
            "is_loaded": self.is_loaded()
        }
        
        if self.device == "cuda" and torch.cuda.is_available():
            info["gpu_memory_allocated_gb"] = torch.cuda.memory_allocated() / 1e9
            info["gpu_memory_reserved_gb"] = torch.cuda.memory_reserved() / 1e9
        
        return info
