from dataclasses import dataclass
from typing import Dict, Set


@dataclass
class DocumentValidation:
    is_valid: bool
    confidence: float
    detected_fields: Dict[str, str]
    missing_fields: Set[str]
    metadata: Dict
