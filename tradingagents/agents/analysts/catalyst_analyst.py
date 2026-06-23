from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.utils.agent_utils import (
    get_global_news,
    get_instrument_context_from_state,
    get_language_instruction,
    get_news,
)


def create_catalyst_analyst(llm):
    def catalyst_analyst_node(state):
        current_date = state["trade_date"]
        instrument_context = get_instrument_context_from_state(state)

        tools = [
            get_news,
            get_global_news,
        ]

        system_message = (
            "You are a Catalyst Analyst for crypto markets. Focus on event and "
            "narrative catalysts that can move perpetual futures, not company "
            "fundamentals. Use get_news for asset-specific coverage and "
            "get_global_news for broader crypto/macro headlines. Analyze:\n"
            "- Protocol announcements and governance outcomes\n"
            "- Exchange listings and delistings\n"
            "- Token unlocks and vesting cliffs\n"
            "- Security incidents, exploits, and bridging risk\n"
            "- Regulation and enforcement actions\n"
            "- Macro and market-wide crypto catalysts\n"
            "- Exchange or venue-specific events\n\n"
            "For every item, explicitly label it as Confirmed (sourced/dated) or "
            "Speculation (rumor, unverified, or speculative framing). Prefer "
            "confirmable facts; do not invent catalysts. Provide specific, "
            "actionable insights with supporting evidence."
            " Make sure to append a Markdown table at the end of the report to "
            "organize key points in the report, organized and easy to read."
            + get_language_instruction()
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful AI assistant, collaborating with other assistants."
                    " Use the provided tools to progress towards answering the question."
                    " If you are unable to fully answer, that's OK; another assistant with different tools"
                    " will help where you left off. Execute what you can to make progress."
                    " If you or any other assistant has the FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** or deliverable,"
                    " prefix your response with FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** so the team knows to stop."
                    " You have access to the following tools: {tool_names}."
                    " Today's date is {current_date}; treat it as 'now' for all analysis and tool-call date ranges. {instrument_context}\n"
                    "{system_message}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(tool_names=", ".join([tool.name for tool in tools]))
        prompt = prompt.partial(current_date=current_date)
        prompt = prompt.partial(instrument_context=instrument_context)

        chain = prompt | llm.bind_tools(tools)
        result = chain.invoke(state["messages"])

        report = ""
        if len(result.tool_calls) == 0:
            report = result.content

        return {
            "messages": [result],
            "catalyst_report": report,
        }

    return catalyst_analyst_node
