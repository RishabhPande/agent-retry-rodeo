"""Trusted local adapter template. No network or API keys."""
from agent_retry_rodeo.engine import RecoveryAgent

class MyAgent(RecoveryAgent):
    name = "My local recovery agent"
    kind = "scripted example, not an LLM"

def create_agent():
    # Return a fresh instance per scenario so state does not leak across cases.
    return MyAgent()
