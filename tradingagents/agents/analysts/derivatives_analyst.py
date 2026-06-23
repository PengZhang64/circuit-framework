from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.utils.agent_utils import (
    get_crypto_derivatives,
    get_crypto_market_snapshot,
    get_instrument_context_from_state,
    get_language_instruction,
)


def create_derivatives_analyst(llm):
    def derivatives_analyst_node(state):
        current_date = state["trade_date"]
        instrument_context = get_instrument_context_from_state(state)

        tools = [
            get_crypto_market_snapshot,
            get_crypto_derivatives,
        ]

        system_message = (
            "You are a Derivatives Analyst for crypto perpetual futures. "
            "Use only the shared market snapshot tools — do not invent funding, "
            "open interest, or premium figures. Analyze:\n"
            "- Funding rate and funding trend (from funding history when present)\n"
            "- Open interest and open-interest change\n"
            "- Perpetual premium\n"
            "- Day notional volume / day price change when available\n"
            "- Crowded positioning and potential long/short squeeze conditions\n"
            "- Liquidation pressure if long/short liquidation fields are present\n"
            "- Data limitations and quality warnings from the snapshot\n\n"
            "Call get_crypto_market_snapshot first for context, then "
            "get_crypto_derivatives for the derivatives block. Cite snapshot_id "
            "when referencing metrics. Provide specific, actionable insights with "
            "supporting evidence."
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
            "derivatives_report": report,
        }

    return derivatives_analyst_node
