from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from carfinder.analysis import ListingAnalysisResult, deterministic_analysis, llm_cache_key
from carfinder.analysis_service import analyze_snapshot
from carfinder.config import Settings
from carfinder.db.engine import create_database_engine
from carfinder.db.migrations import upgrade_database
from carfinder.db.models import Listing, ListingAnalysis, ListingClaim, ListingSnapshot, LlmCache, ScrapeRun
from carfinder.llm import CodexExecProvider, ListingAnalysisRequest


def _analysis_result() -> dict:
    return {
        "positive_claims": [], "concerns": [], "missing_information": [],
        "questions_to_ask": [], "extracted_claims": [], "risk_signals": [],
    }


def test_deterministic_analysis_keeps_seller_statements_as_unverified_claims() -> None:
    snapshot = ListingSnapshot(
        listing_id=1, content_hash="a" * 64,
        title="Volkswagen Golf", description="Prvi vlasnik. Nikad udaran. Veliki servis urađen 2023. godine.",
        price_amount=4300, price_currency="EUR", make="Volkswagen", model="Golf", year=2008,
    )
    result = deterministic_analysis(snapshot)
    claims = {claim.claim_type: claim.value for claim in result.extracted_claims}
    assert claims["first_owner"] is True
    assert claims["accident_free"] is True
    assert claims["major_service_completed"] is True
    assert all("Seller claims" in item.summary for item in result.positive_claims)
    assert any(item.field == "vin" for item in result.missing_information)
    assert any("VIN" in item.question for item in result.questions_to_ask)
    assert not hasattr(result, "quality_score")


def test_semantic_cache_key_ignores_price_but_tracks_description() -> None:
    first = ListingSnapshot(
        listing_id=1, content_hash="a" * 64, title="Golf", description="Service book available.",
        price_amount=4300, price_currency="EUR", make="Volkswagen", year=2008,
    )
    price_only = ListingSnapshot(
        listing_id=1, content_hash="b" * 64, title="Golf", description="Service book available.",
        price_amount=3900, price_currency="EUR", make="Volkswagen", year=2008,
    )
    changed = ListingSnapshot(
        listing_id=1, content_hash="c" * 64, title="Golf", description="Service book not available.",
        price_amount=3900, price_currency="EUR", make="Volkswagen", year=2008,
    )
    assert llm_cache_key(first, "codex_exec", "") == llm_cache_key(price_only, "codex_exec", "")
    assert llm_cache_key(first, "codex_exec", "") != llm_cache_key(changed, "codex_exec", "")


def test_analysis_cache_reuses_semantic_output_for_price_only_changes(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CARFINDER_HOME", str(tmp_path / "runtime"))
    settings = Settings.model_validate({"llm": {
        "enabled": True, "provider": "codex_exec", "model": "test-model",
        "command": ["codex"], "timeout_seconds": 10,
    }})
    engine = create_database_engine(settings.database_path)
    upgrade_database(settings.database_path)
    calls = 0

    class FakeLLM:
        async def analyze_listing(self, _request: ListingAnalysisRequest) -> ListingAnalysisResult:
            nonlocal calls
            calls += 1
            assert "@" not in _request.listing["description"]
            assert "064/1234567" not in _request.listing["description"]
            return ListingAnalysisResult.model_validate(_analysis_result())

    import carfinder.analysis_service as service
    monkeypatch.setattr(service, "get_llm_provider", lambda *_args: FakeLLM())
    try:
        with Session(engine) as session:
            run = ScrapeRun(trigger="test")
            listing = Listing(provider="polovniautomobili", external_id="cache-1", url="https://example.test/1")
            session.add_all((run, listing))
            session.flush()
            first = ListingSnapshot(
                listing_id=listing.id, content_hash="a" * 64, title="Golf",
                description="Prvi vlasnik. Servisna knjiga. Kontakt: mail@example.test, 064/1234567.", price_amount=4300,
                price_currency="EUR", make="Volkswagen", year=2008,
            )
            session.add(first)
            session.flush()
            asyncio.run(analyze_snapshot(session, run, listing, first, settings))
            second = ListingSnapshot(
                listing_id=listing.id, content_hash="b" * 64, title="Golf",
                description="Prvi vlasnik. Servisna knjiga. Kontakt: mail@example.test, 064/1234567.", price_amount=3900,
                price_currency="EUR", make="Volkswagen", year=2008,
            )
            session.add(second)
            session.flush()
            asyncio.run(analyze_snapshot(session, run, listing, second, settings))
            assert calls == 1 and run.llm_calls == 1 and run.llm_cache_hits == 1
            third = ListingSnapshot(
                listing_id=listing.id, content_hash="c" * 64, title="Golf",
                description="Servisna istorija je dostupna.", price_amount=3900,
                price_currency="EUR", make="Volkswagen", year=2008,
            )
            session.add(third)
            session.flush()
            asyncio.run(analyze_snapshot(session, run, listing, third, settings))
            assert calls == 2 and run.llm_calls == 2
            session.commit()
            assert session.scalar(select(func.count()).select_from(LlmCache)) == 2
            assert session.scalar(select(func.count()).select_from(ListingAnalysis)) == 3
            assert session.scalar(select(func.count()).select_from(ListingClaim)) == 4
            claims = session.scalars(select(ListingClaim)).all()
            assert all(claim.verification_status == "claimed" for claim in claims)
            assert all(claim.source_type == "seller_description" for claim in claims)
    finally:
        engine.dispose()


def test_llm_failure_keeps_deterministic_analysis(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CARFINDER_HOME", str(tmp_path / "runtime"))
    settings = Settings.model_validate({"llm": {
        "enabled": True, "provider": "codex_exec", "model": "test-model",
        "command": ["codex"], "timeout_seconds": 10,
    }})
    engine = create_database_engine(settings.database_path)
    upgrade_database(settings.database_path)

    class FailedLLM:
        async def analyze_listing(self, _request: ListingAnalysisRequest) -> ListingAnalysisResult:
            raise RuntimeError("synthetic model failure")

    import carfinder.analysis_service as service
    monkeypatch.setattr(service, "get_llm_provider", lambda *_args: FailedLLM())
    try:
        with Session(engine) as session:
            run = ScrapeRun(trigger="test")
            listing = Listing(provider="polovniautomobili", external_id="fail-1", url="https://example.test/1")
            session.add_all((run, listing))
            session.flush()
            snapshot = ListingSnapshot(
                listing_id=listing.id, content_hash="a" * 64, title="Golf",
                description="Prvi vlasnik.", price_amount=4300, price_currency="EUR",
            )
            session.add(snapshot)
            session.flush()
            analysis = asyncio.run(analyze_snapshot(session, run, listing, snapshot, settings))
            assert analysis.status == "partial"
            assert analysis.result_json["extracted_claims"][0]["claim_type"] == "first_owner"
            assert run.warning_count == 1 and run.error_count == 0
            session.commit()
    finally:
        engine.dispose()


def test_codex_exec_uses_read_only_schema_constrained_subprocess_and_validates_result(tmp_path: Path) -> None:
    script = tmp_path / "fake_codex.py"
    output = _analysis_result()
    script.write_text(
        "import json, pathlib, sys\n"
        "args = sys.argv[1:]\n"
        "assert args[0] == 'exec' and '--ephemeral' in args\n"
        "assert args[args.index('--sandbox') + 1] == 'read-only'\n"
        "schema = pathlib.Path(args[args.index('--output-schema') + 1])\n"
        "assert schema.is_file()\n"
        "path = pathlib.Path(args[args.index('--output-last-message') + 1])\n"
        "raw = sys.stdin.read().split('LISTING_CONTEXT_JSON\\n', 1)[1]\n"
        "assert json.loads(raw)['listing']['vehicle']['make'] == 'Volkswagen'\n"
        f"path.write_text({json.dumps(json.dumps(output))}, encoding='utf-8')\n",
        encoding="utf-8",
    )
    request = ListingAnalysisRequest(listing={"vehicle": {"make": "Volkswagen"}})
    provider = CodexExecProvider([sys.executable, str(script)], timeout_seconds=5)
    result = asyncio.run(provider.analyze_listing(request))
    assert result == ListingAnalysisResult.model_validate(output)

    schema = json.loads(Path("backend/carfinder/schemas/listing_analysis_v1.json").read_text())
    assert schema["additionalProperties"] is False
    with pytest.raises(Exception):
        ListingAnalysisResult.model_validate({**output, "quality_score": 99})
