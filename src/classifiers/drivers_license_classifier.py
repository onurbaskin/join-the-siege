import logging
import re
from typing import Dict, List

from src.classifiers._base_document_classifier import BaseDocumentClassifier
from src.models import DocumentValidation

logger = logging.getLogger(__name__)


class DriversLicenseClassifier(BaseDocumentClassifier):
    def __init__(self):
        super().__init__()
        self.type_indicators = [
            "DRIVER LICENSE",
            "DRIVER'S LICENSE",
            "OPERATOR LICENSE",
            "COMMERCIAL DRIVER LICENSE",
            "IDENTIFICATION CARD",
            "DEPARTMENT OF MOTOR VEHICLES",
            "DMV",
        ]

        self.required_fields = {
            "license_number": [
                r"DL\s*#?\s*[A-Z0-9]+",
                r"DRIVER\'?S?\s*LIC(?:ENSE|)\s*#?\s*[A-Z0-9]+",
            ],
            "name": [r"NAME[\s:]+([A-Z\s,]+)", r"([A-Z]+,\s+[A-Z\s]+)"],
            "dob": [
                r"DOB[\s:]+\d{2}[-/]\d{2}[-/]\d{4}",
                r"DATE\s+OF\s+BIRTH[\s:]+\d{2}[-/]\d{2}[-/]\d{4}",
            ],
            "expiration": [
                r"EXP(?:IRES?)?[\s:]+\d{2}[-/]\d{2}[-/]\d{4}",
                r"EXPIRATION[\s:]+\d{2}[-/]\d{2}[-/]\d{4}",
            ],
            "address": [
                r"ADD?RESS[\s:]+.*?(?=\n|\r|$)",
                r"\d+\s+[A-Z0-9\s,]+(?:STREET|ST|AVENUE|AVE|ROAD|RD|DRIVE|DR)",
            ],
        }

        self.specific_patterns = [
            r"CLASS\s*[A-Z]",
            r"REST\w*:\s*[A-Z]",
            r"ENDORSEMENTS?",
            r"SEX\s*[MF]",
            r"HGT\s*\d",
            r"EYES?\s*[A-Z]{3}",
            r"HAIR\s*[A-Z]{3}",
        ]

    @property
    def document_type(self) -> str:
        return "drivers_license"

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
        if extra_validation["photo_area_score"] > 0:
            confidence *= 1.2  # Boost confidence if photo area detected
        if extra_validation["security_features_score"] > 0:
            confidence *= 1.1  # Boost confidence if security features found

        confidence = min(confidence, 1.0)  # Cap at 1.0

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
            "photo_area_score": 0.0,
            "security_features_score": 0.0,
            "layout_score": 0.0,
            "details": {},
        }

        # Check photo area
        photo_area = await self._detect_photo_area(text_blocks)
        validation_result["photo_area_score"] = 1.0 if photo_area else 0.0

        # Check security features
        security_features = await self._detect_security_features(text_blocks)
        validation_result["security_features_score"] = security_features

        # Check layout
        layout_score = await self._validate_license_layout(text_blocks)
        validation_result["layout_score"] = layout_score

        validation_result["is_valid"] = (
            validation_result["photo_area_score"] > 0
            and validation_result["security_features_score"] > 0.5
            and validation_result["layout_score"] > 0.7
        )

        return validation_result

    async def _detect_photo_area(self, text_blocks: List[Dict]) -> bool:
        covered_areas = []
        for box, _, _ in text_blocks:
            x1, y1 = box[0]
            x2, y2 = box[2]
            covered_areas.append((x1, y1, x2, y2))

        # Check for empty region of appropriate size
        for x in range(0, 1000, 50):
            for y in range(0, 1000, 50):
                if not any(
                    x1 < x < x2 and y1 < y < y2
                    for x1, y1, x2, y2 in covered_areas
                ):
                    return True
        return False

    async def _detect_security_features(
        self, text_blocks: List[Dict]
    ) -> float:
        security_features_found = 0
        total_features = 6  # Number of features we're checking for

        security_keywords = [
            "HOLOGRAM",
            "VOID IF COPIED",
            "SECURITY FEATURE",
            "NOT VALID WITHOUT",
            "CERTIFIED",
            "OFFICIAL",
        ]

        text_content = " ".join(text for _, text, _ in text_blocks)
        for keyword in security_keywords:
            if keyword in text_content.upper():
                security_features_found += 1

        return security_features_found / total_features

    async def _validate_license_layout(self, text_blocks: List[Dict]) -> float:
        try:
            layout_features = []
            for box, text, conf in text_blocks:
                x1, y1 = box[0]
                x2, y2 = box[2]
                layout_features.append(
                    {
                        "x": (x1 + x2) / 2,
                        "y": (y1 + y2) / 2,
                        "width": x2 - x1,
                        "height": y2 - y1,
                        "text": text,
                        "conf": conf,
                    }
                )

            score = 0
            total_checks = 4  # Number of layout checks

            # Check photo position (top-left)
            if any(
                0.1 < f["x"] < 0.3 and 0.1 < f["y"] < 0.4 and f["width"] > 100
                for f in layout_features
            ):
                score += 1

            # Check name position (top-right of photo)
            if any(
                0.4 < f["x"] < 0.9 and 0.1 < f["y"] < 0.3
                for f in layout_features
                if any(
                    n in f["text"].upper() for n in ["NAME", "LAST", "FIRST"]
                )
            ):
                score += 1

            # Check address position (middle-right)
            if any(
                0.4 < f["x"] < 0.9 and 0.3 < f["y"] < 0.6
                for f in layout_features
                if "ADDRESS" in f["text"].upper()
            ):
                score += 1

            # Check license number position (usually bottom)
            if any(
                0.1 < f["x"] < 0.9 and 0.6 < f["y"] < 0.9
                for f in layout_features
                if any(n in f["text"].upper() for n in ["LICENSE", "DL"])
            ):
                score += 1

            return score / total_checks

        except Exception as e:
            logger.error(f"Error validating license layout: {str(e)}")
            return 0.0
