import logging
import re
from typing import Dict, List

from src.classifiers._base_document_classifier import BaseDocumentClassifier
from src.models import DocumentValidation

logger = logging.getLogger(__name__)


class InvoiceClassifier(BaseDocumentClassifier):
    def __init__(self):
        super().__init__()
        self.type_indicators = [
            "INVOICE",
            "TAX INVOICE",
            "BILL OF SALE",
            "PURCHASE INVOICE",
            "BILLING STATEMENT",
            "PAYMENT DUE",
        ]

        self.required_fields = {
            "invoice_number": [
                r"INVOICE\s*(?:#|NUMBER|NO)[\s:]*\d+",
                r"INV\s*(?:#|NUMBER|NO)[\s:]*\d+",
            ],
            "date": [
                r"(?:INVOICE\s+)?DATE[\s:]+\d{2}[-/]\d{2}[-/]\d{4}",
                r"DATED?[\s:]+\d{2}[-/]\d{2}[-/]\d{4}",
            ],
            "amount": [
                r"TOTAL[\s:]+\$[\d,.]+",
                r"AMOUNT\s+DUE[\s:]+\$[\d,.]+",
            ],
            "vendor": [
                r"FROM[\s:]+([A-Z\s]+)(?=\n|\r|$)",
                r"VENDOR[\s:]+([A-Z\s]+)(?=\n|\r|$)",
            ],
            "items": [
                r"\d+\s+[A-Z0-9\s]+\$[\d,.]+",
                r"DESCRIPTION.*?(?:AMOUNT|PRICE|TOTAL)",
            ],
        }

        self.specific_patterns = [
            r"SUBTOTAL",
            r"SHIPPING\s+(?:COST|FEE)",
            r"TAX\s+RATE",
            r"PO\s*(?:NUMBER|#)",
            r"ITEM\s+DESCRIPTION",
            r"PAYMENT\s+TERMS",
            r"DUE\s+DATE",
        ]

    @property
    def document_type(self) -> str:
        return "invoice"

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
        if extra_validation["structure_score"] > 0.8:
            confidence *= 1.2
        if extra_validation["calculation_score"] > 0.8:
            confidence *= 1.1
        if extra_validation["line_items_score"] > 0.8:
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
            "structure_score": 0.0,
            "calculation_score": 0.0,
            "line_items_score": 0.0,
            "details": {},
        }

        # Check invoice structure
        structure_score = await self._validate_invoice_structure(text_blocks)
        validation_result["structure_score"] = structure_score

        # Check calculations
        calculation_score = await self._validate_calculations(text_blocks)
        validation_result["calculation_score"] = calculation_score

        # Check line items
        line_items_score = await self._validate_line_items(text_blocks)
        validation_result["line_items_score"] = line_items_score

        validation_result["is_valid"] = (
            validation_result["structure_score"] > 0.7
            and validation_result["calculation_score"] > 0.7
            and validation_result["line_items_score"] > 0.6
        )

        return validation_result

    async def _validate_invoice_structure(
        self, text_blocks: List[Dict]
    ) -> float:
        try:
            required_sections = {
                "header": False,  # Company info, invoice number, date
                "billing": False,  # Billing/shipping info
                "items": False,  # Line items
                "totals": False,  # Subtotal, tax, total
                "payment": False,  # Payment terms, due date
            }

            for _, text, _ in text_blocks:
                text_upper = text.upper()

                # Check header section
                if any(
                    word in text_upper
                    for word in ["INVOICE", "BILL", "DATE", "NO."]
                ):
                    required_sections["header"] = True

                # Check billing section
                if any(
                    word in text_upper
                    for word in ["BILL TO", "SHIP TO", "ADDRESS"]
                ):
                    required_sections["billing"] = True

                # Check items section
                if any(
                    word in text_upper
                    for word in ["DESCRIPTION", "QUANTITY", "PRICE", "ITEM"]
                ):
                    required_sections["items"] = True

                # Check totals section
                if any(
                    word in text_upper for word in ["SUBTOTAL", "TAX", "TOTAL"]
                ):
                    required_sections["totals"] = True

                # Check payment section
                if any(
                    word in text_upper
                    for word in ["PAYMENT TERMS", "DUE DATE"]
                ):
                    required_sections["payment"] = True

            sections_found = sum(
                1 for section in required_sections.values() if section
            )
            return sections_found / len(required_sections)

        except Exception as e:
            logger.error(f"Error validating invoice structure: {str(e)}")
            return 0.0

    async def _validate_calculations(self, text_blocks: List[Dict]) -> float:
        try:
            amounts = []
            subtotal = 0
            total = 0
            tax = 0

            for _, text, _ in text_blocks:
                text_upper = text.upper()

                # Extract amounts
                amount_matches = re.finditer(r"\$?([\d,]+\.?\d*)", text)
                for match in amount_matches:
                    amount = float(match.group(1).replace(",", ""))
                    amounts.append(amount)

                # Look for specific totals
                if "SUBTOTAL" in text_upper:
                    subtotal_match = re.search(r"\$?([\d,]+\.?\d*)", text)
                    if subtotal_match:
                        subtotal = float(
                            subtotal_match.group(1).replace(",", "")
                        )

                elif "TOTAL" in text_upper and "SUB" not in text_upper:
                    total_match = re.search(r"\$?([\d,]+\.?\d*)", text)
                    if total_match:
                        total = float(total_match.group(1).replace(",", ""))

                elif "TAX" in text_upper:
                    tax_match = re.search(r"\$?([\d,]+\.?\d*)", text)
                    if tax_match:
                        tax = float(tax_match.group(1).replace(",", ""))

            # Check if calculations add up
            if total > 0 and subtotal > 0:
                expected_total = subtotal + tax
                if abs(expected_total - total) <= 0.01:  # Account for rounding
                    return 1.0
                else:
                    return 0.5  # Numbers present but don't add up exactly

            return 0.0  # Couldn't find necessary numbers

        except Exception as e:
            logger.error(f"Error validating calculations: {str(e)}")
            return 0.0

    async def _validate_line_items(self, text_blocks: List[Dict]) -> float:
        try:
            # Expected format: Quantity + Description + Unit Price + Amount
            line_item_pattern = re.compile(
                r"(?:\d+)\s+"  # Quantity
                r"(?:[\w\s-]+)\s+"  # Description
                r"\$?\d+(?:,\d{3})*(?:\.\d{2})?\s+"  # Unit Price
                r"\$?\d+(?:,\d{3})*(?:\.\d{2})?"  # Amount
            )

            valid_items = 0
            potential_items = 0

            for _, text, _ in text_blocks:
                # Check if this block might be a line item
                if re.search(r"\$?\d+(?:,\d{3})*(?:\.\d{2})?", text):
                    potential_items += 1
                    if line_item_pattern.match(text):
                        valid_items += 1

            if potential_items == 0:
                return 0.0

            return valid_items / potential_items

        except Exception as e:
            logger.error(f"Error validating line items: {str(e)}")
            return 0.0

    async def _check_amount_format(self, text_blocks: List[Dict]) -> bool:
        """Additional helper to validate amount formats"""
        amount_pattern = re.compile(r"\$?\d{1,3}(?:,\d{3})*\.\d{2}")

        valid_amounts = 0
        for _, text, _ in text_blocks:
            if amount_pattern.search(text):
                valid_amounts += 1

        return valid_amounts >= 2  # At least two properly formatted amounts
