"""
Utility helpers for ophthalmology consultation system

Simple utility functions for ID and filename generation.
"""

import uuid
from datetime import datetime


def generate_consultation_id(short=True):
    """
    Generate unique consultation identifier
    
    Args:
        short (bool): If True, return 8-char hex. If False, return full UUID.
        
    Returns:
        str: Consultation ID
        
    Examples:
        >>> generate_consultation_id()
        'a3f7e2b9'
        
        >>> generate_consultation_id(short=False)
        'a3f7e2b9c1d2e3f4a5b6c7d8e9f0a1b2'
    """
    full_id = uuid.uuid4().hex
    return full_id[:8] if short else full_id


def generate_consultation_filename(prefix="consultation", extension="json"):
    """
    Generate timestamped filename with unique ID
    
    Format: {prefix}_{YYYYMMDD_HHMMSS}_{short_uuid}.{extension}
    
    Args:
        prefix (str): Filename prefix
        extension (str): File extension (without dot)
        
    Returns:
        str: Generated filename
        
    Examples:
        >>> generate_consultation_filename()
        'consultation_20251126_153045_a3f7e2b9.json'
        
        >>> generate_consultation_filename(prefix="summary", extension="txt")
        'summary_20251126_153045_b4c8d1e2.txt'
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    short_id = generate_consultation_id(short=True)
    return f"{prefix}_{timestamp}_{short_id}.{extension}"