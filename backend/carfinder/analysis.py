from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from carfinder.db.models import ListingSnapshot
from carfinder.privacy import redact_contact_details

PROMPT_VERSION = "listing_analysis_v1"
KNOWLEDGE_VERSION = "0"


class AnalysisFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str
    summary: str
    evidence: str
    confidence: float = Field(ge=0, le=1)


class AnalysisConcern(AnalysisFinding):
    severity: Literal["low", "medium", "high"]


class MissingInformation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    importance: Literal["low", "medium", "high"]
    reason: str


class SellerQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    priority: Literal["low", "medium", "high"]
    question: str


class ExtractedClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_type: str
    value: str | bool | int | None
    evidence: str
    confidence: float = Field(ge=0, le=1)


class RiskSignal(AnalysisFinding):
    severity: Literal["low", "medium", "high"]


class ListingAnalysisResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    positive_claims: list[AnalysisFinding]
    concerns: list[AnalysisConcern]
    missing_information: list[MissingInformation]
    questions_to_ask: list[SellerQuestion]
    extracted_claims: list[ExtractedClaim]
    risk_signals: list[RiskSignal]


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold())
    value = "".join(char for char in value if not unicodedata.combining(char))
    return value.replace("đ", "dj")


def semantic_content(snapshot: ListingSnapshot) -> dict[str, Any]:
    """Exclude asking price so a price-only edit does not invalidate semantic analysis."""
    return {
        "title": redact_contact_details(snapshot.title or ""),
        "description": redact_contact_details(" ".join(snapshot.description.split())),
        "vehicle": {
            "make": snapshot.make, "model": snapshot.model, "generation": snapshot.generation,
            "year": snapshot.year, "fuel": snapshot.fuel, "mileage_km": snapshot.mileage_km,
            "engine_cc": snapshot.engine_cc, "power_kw": snapshot.power_kw,
            "transmission": snapshot.transmission, "drive": snapshot.drive,
            "body_type": snapshot.body_type,
        },
        "features": sorted(set(snapshot.features_json or [])),
        "condition": snapshot.condition_json or {},
    }


def semantic_hash(snapshot: ListingSnapshot) -> str:
    canonical = json.dumps(semantic_content(snapshot), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def llm_cache_key(snapshot: ListingSnapshot, provider: str, model: str) -> str:
    payload = {
        "content": semantic_content(snapshot), "knowledge_version": KNOWLEDGE_VERSION,
        "prompt_version": PROMPT_VERSION, "provider": provider, "model": model,
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def deterministic_analysis(snapshot: ListingSnapshot) -> ListingAnalysisResult:
    description = snapshot.description or ""
    normalized = _normalize(description)
    findings: list[tuple[str, bool, str, str]] = []

    def add_claim(claim_type: str, value: bool, needles: tuple[str, ...], *, negation_sensitive: bool = True) -> None:
        for needle in needles:
            position = normalized.find(needle)
            if position < 0:
                continue
            left, right = max(0, position - 35), min(len(normalized), position + len(needle) + 35)
            nearby = normalized[left:right]
            negated = negation_sensitive and bool(re.search(r"\b(?:nije|nisu|ne|nema|nikako)\b", nearby))
            matched_value = not negated if value else negated
            start = max(0, position - 45)
            end = min(len(description), position + len(needle) + 45)
            evidence = " ".join(description[start:end].split()).strip(" ,.;:-")
            findings.append((claim_type, matched_value, evidence or description[:220], needle))
            return

    add_claim("first_owner", True, ("prvi vlasnik", "prva vlasnica"))
    add_claim("mileage_original", True, ("originalna kilometraza", "garantovana kilometraza"))
    add_claim("accident_free", True, ("nikad udaran", "bez udesa", "bez havarije", "nije udaran"), negation_sensitive=False)
    add_claim("major_service_completed", True, ("veliki servis", "glavni servis"))
    add_claim("service_book_available", True, ("servisna knjiga",))
    add_claim("bought_new_locally", True, ("kupljen nov u srbiji", "kupljena nova u srbiji"))

    positives: list[AnalysisFinding] = []
    concerns: list[AnalysisConcern] = []
    missing: list[MissingInformation] = []
    questions: list[SellerQuestion] = []
    claims: list[ExtractedClaim] = []
    risks: list[RiskSignal] = []
    for claim_type, value, evidence, _needle in findings:
        claims.append(ExtractedClaim(claim_type=claim_type, value=value, evidence=evidence, confidence=0.95))
        if value:
            positive = AnalysisFinding(
                category="maintenance" if claim_type in {"major_service_completed", "service_book_available"} else "ownership_history",
                summary=f"Seller claims {claim_type.replace('_', ' ')}.", evidence=evidence, confidence=0.95,
            )
            positives.append(positive)
            concern = AnalysisConcern(
                category="verification", severity="medium" if claim_type != "first_owner" else "low",
                summary=f"The {claim_type.replace('_', ' ')} statement is not independently verified.",
                evidence=evidence, confidence=0.95,
            )
            concerns.append(concern)
            risks.append(RiskSignal(
                category="unverified_seller_claim", severity=concern.severity,
                summary=concern.summary, evidence=evidence, confidence=0.95,
            ))
        elif claim_type == "major_service_completed":
            concerns.append(AnalysisConcern(
                category="maintenance", severity="medium", summary="The description says the major service has not been completed.",
                evidence=evidence, confidence=0.9,
            ))
        if claim_type == "major_service_completed" and value and not re.search(r"\b(?:servis|servisu)\b.{0,60}\b(?:\d{4}|\d{5,6}\s*km|racun|faktura)\b", _normalize(evidence)):
            missing.append(MissingInformation(
                field="major_service_details", importance="high", reason="A major service is claimed, but the date, mileage, or invoice is not stated.",
            ))
            questions.append(SellerQuestion(
                priority="high", question="At what date and mileage was the major service done, and can you share the invoice?",
            ))
        elif claim_type == "mileage_original" and value:
            missing.append(MissingInformation(
                field="mileage_evidence", importance="high", reason="Original mileage is a seller claim; no supporting service records are included.",
            ))
            questions.append(SellerQuestion(priority="high", question="Can you provide service records or invoices that support the stated mileage?"))

    if not re.search(r"\bvin\b|\bbroj sasije\b", normalized):
        missing.append(MissingInformation(
            field="vin", importance="high", reason="The listing text does not include a VIN or chassis number for history checks.",
        ))
        questions.append(SellerQuestion(priority="high", question="Can you provide the VIN so the vehicle history and specifications can be checked?"))
    if not any(claim.claim_type == "service_book_available" for claim in claims) and "servisna istorija" not in normalized:
        missing.append(MissingInformation(
            field="service_history", importance="medium", reason="The listing does not describe available maintenance records.",
        ))
        questions.append(SellerQuestion(priority="medium", question="Is there a service book or any maintenance invoices?"))

    return ListingAnalysisResult(
        positive_claims=positives, concerns=concerns, missing_information=missing,
        questions_to_ask=questions, extracted_claims=claims, risk_signals=risks,
    )
