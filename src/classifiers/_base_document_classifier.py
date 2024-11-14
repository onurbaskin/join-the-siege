import re
from abc import ABC, abstractmethod
from typing import Dict, List

from src.models import DocumentValidation


class BaseDocumentClassifier(ABC):
    """Abstract base class for document classifiers"""

    def __init__(self):
        self.type_indicators: List[str] = []
        self.required_fields: Dict[str, List[str]] = {}
        self.specific_patterns: List[str] = []

    @abstractmethod
    async def validate_document(
        self, text: str, text_blocks: List[Dict]
    ) -> DocumentValidation:
        """Validate the document according to type-specific rules"""
        pass

    @abstractmethod
    async def check_specific_features(self, text_blocks: List[Dict]) -> Dict:
        """Check for type-specific features"""
        pass

    @property
    @abstractmethod
    def document_type(self) -> str:
        """Return the type of document this classifier handles"""
        pass

    async def calculate_score(self, text: str) -> float:
        """Calculate how likely the text matches this document type"""
        score = 0.0
        text_upper = text.upper()

        # Check type indicators
        for indicator in self.type_indicators:
            if indicator.upper() in text_upper:
                score += 1.0

        # Check required fields
        for patterns in self.required_fields.values():
            for pattern in patterns:
                if re.search(pattern, text, re.IGNORECASE):
                    score += 0.5

        # Check specific patterns
        for pattern in self.specific_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                score += 0.5

        return score
