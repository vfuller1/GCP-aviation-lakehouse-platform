"""
Multi-agent ADK module — proof-of-concept built alongside the existing
LangGraph single-agent (agent.py) to demonstrate true multi-agent handoff.

Pattern: Sequential handoff (Risk Analyst -> Mitigation Advisor), coordinated
by an ADK SequentialAgent orchestrator. Unlike agent.py's single-agent loop
(one decision-maker choosing between tools), this module has two distinct
agents with different roles, where Worker 2's input is Worker 1's output.
"""
