"""Run from the repo root after installation: python docs/adapter_example.py."""
from pathlib import Path
from agent_retry_rodeo.engine import load_scenario, run, RecoveryAgent

# Replace RecoveryAgent with an object implementing name and run(call, goal).
# Do not inspect the simulator or fault schedule from inside your agent.
scenario = load_scenario(Path("scenarios/01-lost-ack.yaml"))
result = run(scenario, RecoveryAgent(), seed=42)
print(result["agent"], result["success"], result["assertions"])
