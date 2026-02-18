"""
llm_integration.py - Guide and utilities for integrating with LLMs

This file shows you how to hook up real LLM calls to make Rell truly autonomous.

Choose one:
1. OpenAI (GPT-4, GPT-3.5)
2. Azure OpenAI
3. Anthropic Claude
4. Local models (Ollama with Llama 3, Mistral, etc.)

START HERE: Uncomment the section for your chosen provider.
"""

# ============================================================================
# OPTION 1: OpenAI (GPT-4)
# ============================================================================

"""
Install: pip install openai

Usage:
    from llm_integration import RellResponder
    responder = RellResponder(provider="openai", api_key="sk-...")
    response = responder.get_rell_response(user_message, world_state, memories)
"""

def openai_example():
    from openai import OpenAI
    
    client = OpenAI(api_key="your-api-key-here")
    
    def get_rell_response(system_prompt: str, context: str, user_message: str) -> str:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "system", "content": context},
                {"role": "user", "content": user_message}
            ],
            temperature=0.8,  # Creative, but not random
            max_tokens=500
        )
        return response.choices[0].message.content
    
    return get_rell_response


# ============================================================================
# OPTION 2: Anthropic Claude
# ============================================================================

"""
Install: pip install anthropic

Usage:
    from llm_integration import RellResponder
    responder = RellResponder(provider="claude", api_key="sk-ant-...")
    response = responder.get_rell_response(user_message, world_state, memories)
"""

def claude_example():
    from anthropic import Anthropic
    
    client = Anthropic(api_key="your-api-key-here")
    
    def get_rell_response(system_prompt: str, context: str, user_message: str) -> str:
        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=500,
            system=f"{system_prompt}\n\n{context}",
            messages=[
                {"role": "user", "content": user_message}
            ]
        )
        return response.content[0].text
    
    return get_rell_response


# ============================================================================
# OPTION 3: Local Model with Ollama
# ============================================================================

"""
Install Ollama: https://ollama.ai
Pull model: ollama pull llama2 (or mistral, neural-chat, etc.)
Start server: ollama serve

Usage:
    from llm_integration import RellResponder
    responder = RellResponder(provider="ollama", model="llama2")
    response = responder.get_rell_response(user_message, world_state, memories)
"""

def ollama_example():
    import requests
    import json
    
    ollama_url = "http://localhost:11434/api/generate"
    
    def get_rell_response(system_prompt: str, context: str, user_message: str) -> str:
        full_prompt = f"{system_prompt}\n\n{context}\n\nUser: {user_message}\n\nRell:"
        
        response = requests.post(ollama_url, json={
            "model": "llama2",
            "prompt": full_prompt,
            "stream": False,
            "temperature": 0.8
        })
        
        result = response.json()
        return result.get("response", "").strip()
    
    return get_rell_response


# ============================================================================
# OPTION 4: LangChain Integration (Multi-Provider)
# ============================================================================

"""
Install: pip install langchain langchain-openai langchain-anthropic

This is the most flexible. LangChain abstracts away provider differences.
"""

def langchain_example():
    """Show how to use LangChain for flexible LLM integration."""
    
    from langchain.callbacks.streaming_stdout import StreamingStdOutCallbackHandler
    
    # For OpenAI:
    from langchain_openai import ChatOpenAI
    llm = ChatOpenAI(model="gpt-4", temperature=0.8)
    
    # For Claude:
    # from langchain_anthropic import ChatAnthropic
    # llm = ChatAnthropic(model="claude-3-sonnet-20240229", temperature=0.8)
    
    # For Ollama:
    # from langchain_community.llms import Ollama
    # llm = Ollama(model="llama2")
    
    from langchain_core.messages import SystemMessage, HumanMessage
    
    def get_rell_response(system_prompt: str, context: str, user_message: str) -> str:
        messages = [
            SystemMessage(content=system_prompt),
            SystemMessage(content=context),
            HumanMessage(content=user_message)
        ]
        
        response = llm.invoke(messages)
        return response.content
    
    return get_rell_response


# ============================================================================
# INTEGRATION WITH talk_to_rell.py
# ============================================================================

"""
To use this in talk_to_rell.py, replace the _generate_rell_response method:

OLD:
    def _generate_rell_response(self, user_message: str, 
                               system_prompt: str, context: str) -> str:
        # Placeholder responses...

NEW:
    def _generate_rell_response(self, user_message: str, 
                               system_prompt: str, context: str) -> str:
        responder = RellResponder(provider="openai", api_key=os.getenv("OPENAI_API_KEY"))
        return responder.get_rell_response(system_prompt, context, user_message)

Then set your API key:
    export OPENAI_API_KEY="sk-..."  (Linux/Mac)
    set OPENAI_API_KEY=sk-...       (Windows)
"""


# ============================================================================
# UNIFIED RESPONDER CLASS
# ============================================================================

class RellResponder:
    """Unified interface for any LLM provider."""
    
    def __init__(self, provider: str = "openai", **kwargs):
        self.provider = provider
        
        if provider == "openai":
            self.client = self._init_openai(kwargs)
        elif provider == "claude":
            self.client = self._init_claude(kwargs)
        elif provider == "ollama":
            self.client = self._init_ollama(kwargs)
        else:
            raise ValueError(f"Unknown provider: {provider}")
    
    def _init_openai(self, kwargs):
        from openai import OpenAI
        return OpenAI(api_key=kwargs.get("api_key"))
    
    def _init_claude(self, kwargs):
        from anthropic import Anthropic
        return Anthropic(api_key=kwargs.get("api_key"))
    
    def _init_ollama(self, kwargs):
        return {"model": kwargs.get("model", "llama2")}
    
    def get_rell_response(self, system_prompt: str, context: str, user_message: str) -> str:
        """Get Rell's response using the configured LLM."""
        
        if self.provider == "openai":
            return self._openai_response(system_prompt, context, user_message)
        elif self.provider == "claude":
            return self._claude_response(system_prompt, context, user_message)
        elif self.provider == "ollama":
            return self._ollama_response(system_prompt, context, user_message)
    
    def _openai_response(self, system_prompt: str, context: str, user_message: str) -> str:
        response = self.client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "system", "content": context},
                {"role": "user", "content": user_message}
            ],
            temperature=0.8,
            max_tokens=500
        )
        return response.choices[0].message.content
    
    def _claude_response(self, system_prompt: str, context: str, user_message: str) -> str:
        response = self.client.messages.create(
            model="claude-3-sonnet-20240229",
            max_tokens=500,
            system=f"{system_prompt}\n\n{context}",
            messages=[
                {"role": "user", "content": user_message}
            ]
        )
        return response.content[0].text
    
    def _ollama_response(self, system_prompt: str, context: str, user_message: str) -> str:
        import requests
        
        full_prompt = f"{system_prompt}\n\n{context}\n\nUser: {user_message}\n\nRell:"
        
        response = requests.post("http://localhost:11434/api/generate", json={
            "model": self.client["model"],
            "prompt": full_prompt,
            "stream": False,
            "temperature": 0.8
        })
        
        return response.json().get("response", "").strip()


# ============================================================================
# ENVIRONMENT SETUP
# ============================================================================

"""
1. Create a .env file in stonecrest_world_engine/:

    # For OpenAI
    OPENAI_API_KEY=sk-...
    
    # For Claude
    ANTHROPIC_API_KEY=sk-ant-...
    
    # For Ollama (usually no key needed)
    OLLAMA_MODEL=llama2

2. Load it in your code:

    from dotenv import load_dotenv
    import os
    
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
"""


if __name__ == "__main__":
    print("""
    ╔════════════════════════════════════════════════════════════════╗
    ║  Stonecrest World Engine - LLM Integration Guide              ║
    ╚════════════════════════════════════════════════════════════════╝
    
    QUICK START:
    
    1. Choose your LLM provider (OpenAI, Claude, Ollama, etc.)
    2. Install the SDK (pip install openai, anthropic, etc.)
    3. Set your API key (environment variable or .env file)
    4. Update talk_to_rell.py to use RellResponder
    5. Run: python talk_to_rell.py .
    
    ────────────────────────────────────────────────────────────────
    
    RECOMMENDED STARTING SETUP:
    
    Provider: OpenAI GPT-4
    Install: pip install openai
    Cost: ~$0.03 per conversation
    Quality: Excellent for character roleplay
    
    OR
    
    Provider: Ollama (Local, Free)
    Install: https://ollama.ai, then ollama pull llama2
    Cost: Free (your CPU/GPU)
    Quality: Good, very fast locally
    
    ────────────────────────────────────────────────────────────────
    
    For more details, read the comments in llm_integration.py
    """)
