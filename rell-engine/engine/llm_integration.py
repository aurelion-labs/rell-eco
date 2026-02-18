"""
llm_integration.py - Modular LLM Provider System for Rell Audit Engine

Rell supports three LLM modes. Switch between them at runtime via --llm flag
or programmatically by passing provider= to RellLLMProvider.

PROVIDERS:
    none     Fully deterministic. No external calls. Default. (recommended for regulated data)
    openai   Cloud. Requires OPENAI_API_KEY. Fast, high quality.
    claude   Cloud. Requires ANTHROPIC_API_KEY. Strong reasoning.
    ollama   Local. Requires Ollama running on localhost. Zero external calls. Free.

USAGE (CLI):
    python run_audit.py                         # deterministic, no LLM
    python run_audit.py --llm openai            # OpenAI GPT-4o
    python run_audit.py --llm openai --model gpt-4o-mini
    python run_audit.py --llm claude            # Claude Sonnet
    python run_audit.py --llm ollama            # local Ollama (default model: llama3)
    python run_audit.py --llm ollama --model mistral

USAGE (Python):
    from llm_integration import RellLLMProvider, build_provider

    # Deterministic (no LLM)
    provider = RellLLMProvider()
    text = provider.assess(prompt)

    # OpenAI
    provider = RellLLMProvider(provider="openai")
    text = provider.assess(prompt)

    # Ollama (local, zero external calls)
    provider = RellLLMProvider(provider="ollama", model="mistral")
    text = provider.assess(prompt)

    # Switch provider at runtime without reinstantiating
    provider.switch("ollama")
    text = provider.assess(prompt)

    # Build from CLI args or environment variables
    provider = build_provider(provider="ollama")

SECURITY NOTE:
    When --llm openai or --llm claude is active, Rell sends audit finding
    summaries to external APIs. For regulated data (HIPAA, GDPR, etc.) use
    --llm ollama (fully local) or omit --llm entirely (deterministic mode).
    See DEPLOYMENT_SECURITY.md for full guidance.

OLLAMA SETUP:
    1. Install Ollama: https://ollama.com
    2. Pull a model: ollama pull llama3
    3. Ollama runs automatically on localhost:11434
    4. Run Rell: python run_audit.py --llm ollama
    Supported models: llama3, mistral, neural-chat, phi3, gemma2, codellama
    Switch model:     python run_audit.py --llm ollama --model mistral

ENVIRONMENT VARIABLES (set in .env):
    RELL_LLM_PROVIDER=ollama          # default provider when --llm not specified
    RELL_LLM_MODEL=mistral            # override default model
    OPENAI_API_KEY=sk-...
    ANTHROPIC_API_KEY=sk-ant-...
    OLLAMA_BASE_URL=http://localhost:11434   # override if Ollama runs on different host
"""

import os
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Default models per provider
# ---------------------------------------------------------------------------
_DEFAULT_MODELS = {
    "openai": "gpt-4o",
    "claude": "claude-3-5-sonnet-20241022",
    "ollama": "llama3",
}

_OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

_AUDIT_SYSTEM_PROMPT = """You are Rell — an autonomous audit agent. Scholarly, precise, direct.
You analyze workflow and data integrity findings and produce clear, structured assessments.
You do not embellish. You name what you find. You state severity plainly.
You never fabricate findings. If something is unclear, you say so.
Your output is used by compliance officers and data analysts — be accurate above all else."""


# ---------------------------------------------------------------------------
# RellLLMProvider — unified modular interface
# ---------------------------------------------------------------------------

class RellLLMProvider:
    """
    Unified LLM provider for Rell's audit assessment engine.

    All providers expose the same interface: assess(prompt) -> str
    Switch between providers at runtime with .switch(provider).

    Providers:
        none    — deterministic, no external calls (default, safe for regulated data)
        openai  — OpenAI GPT-4o (or any OpenAI-compatible model)
        claude  — Anthropic Claude
        ollama  — Local model via Ollama (zero external calls, free)
    """

    def __init__(
        self,
        provider: str = "none",
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        self.provider = provider.lower()
        self.model = model or _DEFAULT_MODELS.get(self.provider)
        self.api_key = api_key
        self.base_url = base_url
        self._client = None

        if self.provider != "none":
            self._init_client()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def assess(self, prompt: str) -> str:
        """
        Generate an audit assessment for the given prompt.
        Falls back to deterministic mode on any provider error.
        """
        if self.provider == "none":
            return self._deterministic_response(prompt)
        elif self.provider == "openai":
            return self._openai_assess(prompt)
        elif self.provider == "claude":
            return self._claude_assess(prompt)
        elif self.provider == "ollama":
            return self._ollama_assess(prompt)
        return self._deterministic_response(prompt)

    def switch(self, provider: str, model: Optional[str] = None) -> None:
        """
        Switch to a different LLM provider at runtime.

        Example:
            provider = RellLLMProvider(provider="openai")
            provider.switch("ollama")   # now fully local, no external calls
            provider.switch("none")     # back to deterministic
        """
        self.provider = provider.lower()
        self.model = model or _DEFAULT_MODELS.get(self.provider)
        self._client = None
        if self.provider != "none":
            self._init_client()

    def is_local(self) -> bool:
        """Returns True if no external API calls will be made."""
        return self.provider in ("none", "ollama")

    def describe(self) -> str:
        """Human-readable description of the active provider."""
        if self.provider == "none":
            return "deterministic (no LLM — fully local, no external calls)"
        if self.provider == "ollama":
            return f"ollama/{self.model} (local — no external calls)"
        return f"{self.provider}/{self.model} (cloud — finding summaries sent externally)"

    # ------------------------------------------------------------------
    # Client initialization
    # ------------------------------------------------------------------

    def _init_client(self) -> None:
        if self.provider == "openai":
            try:
                from openai import OpenAI
                key = self.api_key or os.getenv("OPENAI_API_KEY")
                if not key:
                    raise ValueError(
                        "OPENAI_API_KEY not set. Add it to .env or set env var."
                    )
                self._client = OpenAI(api_key=key)
            except ImportError:
                raise ImportError("Run: pip install openai")

        elif self.provider == "claude":
            try:
                from anthropic import Anthropic
                key = self.api_key or os.getenv("ANTHROPIC_API_KEY")
                if not key:
                    raise ValueError(
                        "ANTHROPIC_API_KEY not set. Add it to .env or set env var."
                    )
                self._client = Anthropic(api_key=key)
            except ImportError:
                raise ImportError("Run: pip install anthropic")

        elif self.provider == "ollama":
            try:
                import requests
                resp = requests.get(f"{_OLLAMA_BASE_URL}/api/tags", timeout=3)
                if resp.status_code != 200:
                    raise ConnectionError(f"Ollama returned status {resp.status_code}")
                self._client = {"base_url": _OLLAMA_BASE_URL, "model": self.model}
            except Exception as e:
                raise ConnectionError(
                    f"Cannot reach Ollama at {_OLLAMA_BASE_URL}.\n"
                    f"  Install: https://ollama.com\n"
                    f"  Pull model: ollama pull {self.model}\n"
                    f"  Error: {e}"
                )

    # ------------------------------------------------------------------
    # Provider implementations
    # ------------------------------------------------------------------

    def _openai_assess(self, prompt: str) -> str:
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": _AUDIT_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=600,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            return f"[OpenAI error — falling back to deterministic]\n{e}\n\n{self._deterministic_response(prompt)}"

    def _claude_assess(self, prompt: str) -> str:
        try:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=600,
                system=_AUDIT_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text.strip()
        except Exception as e:
            return f"[Claude error — falling back to deterministic]\n{e}\n\n{self._deterministic_response(prompt)}"

    def _ollama_assess(self, prompt: str) -> str:
        try:
            import requests as req
            full_prompt = f"{_AUDIT_SYSTEM_PROMPT}\n\n{prompt}"
            response = req.post(
                f"{self._client['base_url']}/api/generate",
                json={
                    "model": self._client["model"],
                    "prompt": full_prompt,
                    "stream": False,
                    "options": {"temperature": 0.3},
                },
                timeout=120,
            )
            return response.json().get("response", "").strip()
        except Exception as e:
            return f"[Ollama error — falling back to deterministic]\n{e}\n\n{self._deterministic_response(prompt)}"

    def _deterministic_response(self, prompt: str) -> str:
        lines = [l.strip() for l in prompt.strip().splitlines() if l.strip()]
        summary_line = lines[0] if lines else "Audit cycle complete."
        return (
            f"{summary_line}\n\n"
            "Assessment generated in deterministic mode — no LLM, no external calls. "
            "All findings are rule-based. "
            "Use --llm ollama for locally-enhanced assessments (free, fully local) or "
            "--llm openai for cloud-enhanced assessments."
        )


# ---------------------------------------------------------------------------
# Convenience factory — builds from CLI args or environment
# ---------------------------------------------------------------------------

def build_provider(
    provider: Optional[str] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
) -> RellLLMProvider:
    """
    Build a RellLLMProvider from CLI args or environment variables.

    Priority for provider:  explicit arg > RELL_LLM_PROVIDER env var > "none"
    Priority for model:     explicit arg > RELL_LLM_MODEL env var > provider default

    .env example:
        RELL_LLM_PROVIDER=ollama
        RELL_LLM_MODEL=mistral
    """
    resolved_provider = provider or os.getenv("RELL_LLM_PROVIDER", "none")
    resolved_model    = model    or os.getenv("RELL_LLM_MODEL")
    return RellLLMProvider(
        provider=resolved_provider,
        model=resolved_model,
        api_key=api_key,
    )


# ---------------------------------------------------------------------------
# Legacy alias — keeps backward compatibility with any existing references
# ---------------------------------------------------------------------------

class RellResponder(RellLLMProvider):
    """Legacy alias for RellLLMProvider. Use RellLLMProvider in new code."""
    def get_rell_response(self, system_prompt: str, context: str, user_message: str) -> str:
        prompt = f"{system_prompt}\n\nContext:\n{context}\n\nUser:\n{user_message}"
        return self.assess(prompt)

