import logging
import re
from typing import Dict, List

from src.classifiers._base_document_classifier import BaseDocumentClassifier
from src.models import DocumentValidation

logger = logging.getLogger(__name__)


class BankStatementClassifier(BaseDocumentClassifier):
    def __init__(self):
        super().__init__()
        self.type_indicators = [
            "BANK STATEMENT",
            "ACCOUNT STATEMENT",
            "MONTHLY STATEMENT",
            "ACCOUNT SUMMARY",
            "ACCOUNT ACTIVITY",
            "TRANSACTION HISTORY",
        ]

        self.required_fields = {
            "bank_name": [
                r"(BANK\s+OF\s+[A-Z]+|[A-Z]+\s+BANK|CHASE|WELLS\s+FARGO|CITIBANK)",
                r"([A-Z]+\s+)?BANK(?:ING)?\s+STATEMENT",
            ],
            "account_number": [
                r"ACCOUNT\s*(?:#|NUMBER|NO)[\s:]*[X*\d]+",
                r"ACCT\s*(?:#|NUMBER|NO)[\s:]*[X*\d]+",
            ],
            "statement_period": [
                r"STATEMENT\s+PERIOD[\s:]+.*?(?=\n|\r|$)",
                r"STATEMENT\s+DATE[\s:]+.*?(?=\n|\r|$)",
            ],
            "balance": [
                r"(?:ENDING|CLOSING)\s+BALANCE[\s:]+[$][\d,.]+",
                r"BALANCE[\s:]+[$][\d,.]+",
            ],
            "transactions": [
                r"\d{2}[-/]\d{2}\s+(?:\$[\d,.]+\s+){2}",
                r"(?:DEPOSIT|WITHDRAWAL|DEBIT|CREDIT)\s+\$[\d,.]+",
            ],
        }

        self.specific_patterns = [
            r"DEPOSIT\s+SUMMARY",
            r"WITHDRAWAL\s+SUMMARY",
            r"BEGINNING\s+BALANCE",
            r"ENDING\s+BALANCE",
            r"APR\s*\d",
            r"INTEREST\s+RATE",
            r"AVAILABLE\s+BALANCE",
        ]

    @property
    def document_type(self) -> str:
        return "bank_statement"

    async def validate_document(
        self, text: str, text_blocks: List[Dict]
    ) -> DocumentValidation:
        detected_fields = {}
        missing_fields = set()

        # Check for required fields
        for field, patterns in self.required_fields.items():
            field_found = False
            for pattern in patterns:
                matches = re.finditer(pattern, text, re.IGNORECASE)
                for match in matches:
                    field_found = True
                    value = (
                        match.group(1) if match.groups() else match.group(0)
                    )
                    detected_fields[field] = value.strip()
                    break
                if field_found:
                    break

            if not field_found:
                missing_fields.add(field)

        # Calculate base confidence
        total_fields = len(self.required_fields)
        found_fields = total_fields - len(missing_fields)
        confidence = found_fields / total_fields

        # Check additional features
        extra_validation = await self.check_specific_features(text_blocks)

        # Adjust confidence based on extra validation
        if extra_validation["table_structure_score"] > 0.8:
            confidence *= 1.2
        if extra_validation["transaction_format_score"] > 0.8:
            confidence *= 1.1

        confidence = min(confidence, 1.0)

        return DocumentValidation(
            is_valid=confidence > 0.8 and extra_validation["is_valid"],
            confidence=confidence,
            detected_fields=detected_fields,
            missing_fields=missing_fields,
            metadata={
                "extra_validation": extra_validation,
                "text_blocks_count": len(text_blocks),
            },
        )

    async def check_specific_features(self, text_blocks: List[Dict]) -> Dict:
        validation_result = {
            "is_valid": True,
            "table_structure_score": 0.0,
            "transaction_format_score": 0.0,
            "details": {},
        }

        # Check table structure
        table_score = await self._detect_table_structure(text_blocks)
        validation_result["table_structure_score"] = table_score

        # Check transaction format
        transaction_score = await self._validate_transaction_format(
            text_blocks
        )
        validation_result["transaction_format_score"] = transaction_score

        validation_result["is_valid"] = (
            validation_result["table_structure_score"] > 0.7
            and validation_result["transaction_format_score"] > 0.7
        )

        return validation_result

    async def _detect_table_structure(self, text_blocks: List[Dict]) -> float:
        try:
            rows = {}
            for box, text, _ in text_blocks:
                y_coord = (box[0][1] + box[2][1]) / 2
                if y_coord not in rows:
                    rows[y_coord] = []
                rows[y_coord].append((box[0][0], text))

            if len(rows) < 3:
                return 0.0

            sorted_rows = [rows[y] for y in sorted(rows.keys())]
            x_coords = [item[0] for item in sorted_rows[0]]

            aligned_rows = 0
            for row in sorted_rows[1:]:
                row_x_coords = [item[0] for item in row]
                if all(
                    any(abs(x1 - x2) < 20 for x2 in row_x_coords)
                    for x1 in x_coords
                ):
                    aligned_rows += 1

            return aligned_rows / len(sorted_rows)

        except Exception as e:
            logger.error(f"Error detecting table structure: {str(e)}")
            return 0.0

    async def _validate_transaction_format(
        self, text_blocks: List[Dict]
    ) -> float:
        try:
            transaction_pattern = re.compile(
                r"\d{1,2}[-/]\d{1,2}(?:[-/]\d{2,4})?\s+"  # Date
                r"(?:[\w\s]+)\s+"  # Description
                r"\$?\d+(?:,\d{3})*(?:\.\d{2})?"  # Amount
            )

            valid_transactions = 0
            potential_transactions = 0

            for _, text, _ in text_blocks:
                if any(
                    word in text.upper()
                    for word in [
                        "DEPOSIT",
                        "WITHDRAWAL",
                        "DEBIT",
                        "CREDIT",
                        "TRANSACTION",
                    ]
                ):
                    potential_transactions += 1
                    if transaction_pattern.match(text):
                        valid_transactions += 1

            return valid_transactions / max(potential_transactions, 1)

        except Exception as e:
            logger.error(f"Error validating transaction format: {str(e)}")
            return 0.0
