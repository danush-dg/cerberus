from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from cerberus.nodes.approve_node import approve_node
from cerberus.nodes.enrich_node import enrich_node
from cerberus.nodes.reason_node import reason_node
from cerberus.nodes.scan_node import scan_node
from cerberus.state import CerberusState

# Session 5 minimal graph: scan → enrich → reason → approve → END
# Session 6 will replace this with the fully wired graph including
# revalidate_node, execute_node, audit_node, and error_node.


def _build_graph() -> StateGraph:
    builder = StateGraph(CerberusState)

    builder.add_node("scan_node", scan_node)
    builder.add_node("enrich_node", enrich_node)
    builder.add_node("reason_node", reason_node)
    builder.add_node("approve_node", approve_node)

    builder.add_edge(START, "scan_node")
    builder.add_edge("scan_node", "enrich_node")
    builder.add_edge("enrich_node", "reason_node")
    builder.add_edge("reason_node", "approve_node")
    builder.add_edge("approve_node", END)

    return builder


cerberus_graph = _build_graph().compile(checkpointer=MemorySaver())
