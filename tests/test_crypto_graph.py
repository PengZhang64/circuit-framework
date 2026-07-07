"""Graph node order / shared snapshot store — no LLM invocation."""

from unittest.mock import MagicMock

from langgraph.prebuilt import ToolNode

from tradingagents.crypto.snapshot_store import clear_snapshot, get_snapshot, set_snapshot
from tradingagents.graph.conditional_logic import ConditionalLogic
from tradingagents.graph.setup import CRYPTO_DEFAULT_ANALYSTS, GraphSetup
from tests.crypto_test_utils import make_fresh_snapshot


def _fake_tool_nodes():
    nodes = {}
    for key in ("market", "derivatives", "social", "catalyst", "regime", "news", "fundamentals"):
        nodes[key] = ToolNode([])
    return nodes


def test_crypto_default_analyst_order():
    assert CRYPTO_DEFAULT_ANALYSTS == (
        "market",
        "derivatives",
        "social",
        "catalyst",
        "regime",
    )


def test_crypto_graph_contains_snapshot_and_risk_gate():
    llm = MagicMock()
    setup = GraphSetup(
        quick_thinking_llm=llm,
        deep_thinking_llm=llm,
        tool_nodes=_fake_tool_nodes(),
        conditional_logic=ConditionalLogic(),
        config={},
    )
    workflow = setup.setup_graph(
        selected_analysts=CRYPTO_DEFAULT_ANALYSTS,
        asset_type="crypto",
    )
    # Compile without invoking — inspect nodes via graph structure
    graph = workflow.compile()
    node_names = set(graph.get_graph().nodes)
    assert "Snapshot Builder" in node_names
    assert "Deterministic Risk Gate" in node_names
    assert "Market Analyst" in node_names or "market" in str(node_names).lower() or any(
        "Market" in n for n in node_names
    )


def test_shared_snapshot_store_used_by_tools():
    clear_snapshot()
    snap = make_fresh_snapshot()
    set_snapshot(snap)
    assert get_snapshot().snapshot_id == snap.snapshot_id
    # Second "consumer" sees the same object
    assert get_snapshot() is snap
    clear_snapshot()


def test_stock_graph_lacks_crypto_nodes():
    llm = MagicMock()
    setup = GraphSetup(
        quick_thinking_llm=llm,
        deep_thinking_llm=llm,
        tool_nodes=_fake_tool_nodes(),
        conditional_logic=ConditionalLogic(),
        config={},
    )
    workflow = setup.setup_graph(asset_type="stock")
    graph = workflow.compile()
    node_names = set(graph.get_graph().nodes)
    assert "Snapshot Builder" not in node_names
    assert "Deterministic Risk Gate" not in node_names
