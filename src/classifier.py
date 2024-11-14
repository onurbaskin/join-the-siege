import logging
import os
import tempfile
from pathlib import Path
from typing import Dict, List, Tuple

import easyocr
import numpy as np
from pdf2image import convert_from_path
from PIL import Image
from transformers import AutoTokenizer, LayoutLMv3Processor
from werkzeug.datastructures import FileStorage

from src.classifiers._base_document_classifier import BaseDocumentClassifier
from src.classifiers.bank_statement_classifier import BankStatementClassifier
from src.classifiers.drivers_license_classifier import DriversLicenseClassifier
from src.classifiers.invoice_classifier import InvoiceClassifier

logger = logging.getLogger(__name__)


class DocumentClassifierFactory:
    """Factory class for creating and managing document classifiers"""

    def __init__(self):
        self.classifiers: Dict[str, BaseDocumentClassifier] = {}
        self.ocr_reader = easyocr.Reader(["en"])
        self.tokenizer = AutoTokenizer.from_pretrained("bert-base-uncased")
        self.layout_processor = LayoutLMv3Processor.from_pretrained(
            "microsoft/layoutlmv3-base"
        )

    async def _extract_text(self, file: FileStorage) -> Tuple[str, List[Dict]]:
        """Extract text and layout information from document"""
        try:
            # Save uploaded file temporarily
            temp_file_path = await self._save_uploaded_file(file)

            try:
                # Convert file to image if needed
                if temp_file_path.lower().endswith(".pdf"):
                    images = convert_from_path(temp_file_path)
                    image = images[0]  # Process first page
                else:
                    image = Image.open(temp_file_path)

                # Get detailed text with positions using easyOCR
                results = self.ocr_reader.readtext(np.array(image))

                # Combine all text for classification
                full_text = " ".join(text for _, text, _ in results)

                return full_text, results

            finally:
                # Clean up temporary file
                if os.path.exists(temp_file_path):
                    os.remove(temp_file_path)

        except Exception as e:
            logger.error(f"Error extracting text: {str(e)}")
            raise

    async def _save_uploaded_file(self, file: FileStorage) -> str:
        """Save uploaded file to temporary location"""
        # Create temp file with correct extension
        suffix = Path(file.filename).suffix
        with tempfile.NamedTemporaryFile(
            delete=False, suffix=suffix
        ) as temp_file:
            file.save(temp_file.name)
            return temp_file.name

    def register_classifier(self, classifier: BaseDocumentClassifier):
        """Register a new document classifier"""
        self.classifiers[classifier.document_type] = classifier

    async def classify_document(self, file: FileStorage) -> Dict:
        """Classify and validate a document"""
        try:
            # Extract text from document
            text, text_blocks = await self._extract_text(file)

            # Calculate scores for each classifier
            scores = {}
            for doc_type, classifier in self.classifiers.items():
                scores[doc_type] = await classifier.calculate_score(text)

            # Get the highest scoring classifier
            if not scores:
                return self._unknown_response()

            best_type = max(scores.items(), key=lambda x: x[1])

            if best_type[1] == 0:
                return self._unknown_response()

            # Validate with the best matching classifier
            classifier = self.classifiers[best_type[0]]
            validation = await classifier.validate_document(text, text_blocks)

            return {
                "file_class": classifier.document_type,
                "confidence": float(validation.confidence),
                "is_valid": validation.is_valid,
                "detected_fields": validation.detected_fields,
                "missing_fields": list(validation.missing_fields),
                "metadata": validation.metadata,
            }

        except Exception as e:
            logger.error(f"Error in document classification: {str(e)}")
            return self._error_response(str(e))

    def _unknown_response(self) -> Dict:
        return {
            "file_class": "unknown",
            "confidence": 0.0,
            "is_valid": False,
            "error": "Unknown document type",
        }

    def _error_response(self, error: str) -> Dict:
        return {
            "file_class": "unknown",
            "confidence": 0.0,
            "is_valid": False,
            "error": error,
        }


# classifier.py (main entry point)
async def classify_file(file: FileStorage) -> str:
    # Create and configure the factory
    factory = DocumentClassifierFactory()

    # Register all classifiers
    factory.register_classifier(DriversLicenseClassifier())
    factory.register_classifier(BankStatementClassifier())
    factory.register_classifier(InvoiceClassifier())

    # Classify the document
    result = await factory.classify_document(file)
    return result["file_class"]
