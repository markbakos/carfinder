from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from carfinder.analysis import ListingAnalysisResult


class ListingAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    listing: dict[str, Any]
    known_vehicle_issues: list[dict[str, Any]] = Field(default_factory=list)
    market_context: dict[str, Any] = Field(default_factory=dict)
    existing_deterministic_signals: list[dict[str, Any]] = Field(default_factory=list)


class LLMProvider(Protocol):
    provider_id: str

    async def analyze_listing(self, request: ListingAnalysisRequest) -> ListingAnalysisResult: ...


class CodexExecProvider:
    provider_id = "codex_exec"

    def __init__(self, command: list[str], timeout_seconds: int, model: str = "") -> None:
        self.command = command
        self.timeout_seconds = timeout_seconds
        self.model = model

    async def analyze_listing(self, request: ListingAnalysisRequest) -> ListingAnalysisResult:
        package_dir = Path(__file__).resolve().parent
        schema = package_dir / "schemas" / "listing_analysis_v1.json"
        prompt_file = package_dir / "prompts" / "listing_analysis_v1.md"
        if not schema.is_file() or not prompt_file.is_file():
            raise RuntimeError("Packaged listing-analysis prompt or schema is missing")

        with tempfile.TemporaryDirectory(prefix="carfinder-llm-") as working_dir:
            result_path = Path(working_dir) / "result.json"
            args = [
                *self.command, "exec", "--ephemeral", "--skip-git-repo-check", "--sandbox", "read-only",
                "--output-schema", str(schema), "--output-last-message", str(result_path),
            ]
            if self.model:
                args.extend(("--model", self.model))
            args.append("-")
            prompt = prompt_file.read_text(encoding="utf-8")
            prompt += "\n\nLISTING_CONTEXT_JSON\n" + request.model_dump_json(exclude_none=True)
            process = await asyncio.create_subprocess_exec(
                *args,
                cwd=working_dir,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(prompt.encode("utf-8")), timeout=self.timeout_seconds
                )
            except TimeoutError:
                process.kill()
                await process.wait()
                raise TimeoutError(f"Codex Exec exceeded {self.timeout_seconds}s")
            if process.returncode != 0:
                detail = stderr.decode("utf-8", errors="replace")[-2000:]
                raise RuntimeError(f"Codex Exec exited with {process.returncode}: {detail}")
            if result_path.is_file():
                response_text = result_path.read_text(encoding="utf-8")
            else:
                response_text = stdout.decode("utf-8", errors="replace")
            if len(response_text) > 1_000_000:
                raise ValueError("LLM response exceeded the 1 MB output limit")
            response = json.loads(response_text)
            return ListingAnalysisResult.model_validate(response)


def get_llm_provider(provider: str, command: list[str], timeout_seconds: int, model: str) -> LLMProvider:
    if provider == "codex_exec":
        if not command:
            raise ValueError("llm.command must contain the Codex executable")
        return CodexExecProvider(command, timeout_seconds, model)
    if provider == "none":
        raise ValueError("LLM provider is disabled")
    raise ValueError(f"LLM provider {provider!r} is not implemented yet")
