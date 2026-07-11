You are the lead Python, quantitative trading and LangGraph engineer responsible for converting this TradingAgents fork into a production-quality crypto-native research and paper-trading framework called Circuit Framework.
Work directly in the repository. Inspect the existing implementation before making changes. Do not ask me questions. Make reasonable engineering decisions, implement the complete scope, run all tests and fix failures before finishing.
Primary objective
Transform TradingAgents from a stock-first research framework with basic crypto compatibility into a crypto-native framework for perpetual futures research, structured trade generation, deterministic risk management and simulated execution.
The system must:
1. Analyze crypto perpetual markets rather than treating crypto as a Yahoo Finance ticker.
2. Support BTC, ETH, SOL, HYPE and other Hyperliquid perpetual markets.
3. Use market structure, derivatives, sentiment, catalysts and market-regime analysis.
4. Produce structured LONG, SHORT or NO_TRADE proposals.
5. Pass every proposal through deterministic risk controls.
6. Support multiple strategy profiles using the same data and execution rules.
7. Persist paper positions, trades and performance.
8. Remain compatible with the existing LLM-provider system.
9. Preserve the existing stock pipeline where practical.
10. Never place real trades or request private keys.
Do not perform a large package rename. Keep the internal Python package named tradingagents to avoid breaking imports. Change user-facing branding, CLI descriptions and documentation to Circuit Framework.
Non-negotiable engineering rules
* Preserve the Apache 2.0 license and upstream attribution.
* Do not delete existing stock functionality or existing tests.
* Crypto functionality must be selected through asset_type="crypto".
* All numeric market calculations must be deterministic Python code, not LLM calculations.
* LLMs may interpret calculated data but may not invent prices, funding, open interest, indicators or order-book values.
* Use UTC timestamps everywhere.
* Use Pydantic models for structured objects.
* Use Decimal for balances, position quantities, fees and realized PnL.
* Unit tests must not call live external APIs.
* Mock network responses using fixtures.
* Never silently substitute one data provider for another.
* Missing data must be explicitly marked unavailable.
* Do not implement real-money execution in this task.
* Do not add a web frontend.
* Complete the implementation before writing a summary.
1. Add crypto configuration
Extend tradingagents/default_config.py with the following settings:
"crypto_venue": "hyperliquid",
"crypto_instrument_type": "perp",
"crypto_quote_currency": "USDG",
"crypto_default_interval": "1h",
"crypto_analysis_intervals": ["15m", "1h", "4h", "1d"],
"crypto_candle_limit": 300,
"crypto_snapshot_cache_seconds": 30,
"crypto_request_timeout_seconds": 15,
"crypto_max_data_age_seconds": 180,
"paper_starting_balance": 100000,
"paper_fee_bps": 4.5,
"paper_slippage_bps": 2.0,
"paper_max_leverage": 3.0,
"paper_max_position_pct": 10.0,
"paper_risk_per_trade_pct": 1.0,
"paper_min_reward_risk": 1.5,
"paper_max_spread_bps": 30.0,
"paper_database_path": "~/.tradingagents/circuit/paper.db",
"default_crypto_strategy": "balanced",


Add corresponding environment overrides using the existing TRADINGAGENTS_* configuration pattern.
Add documented variables to .env.example.
2. Implement canonical crypto instruments
Create:
tradingagents/crypto/
├── __init__.py
├── instruments.py
├── schemas.py
└── indicators.py


In instruments.py, implement canonical crypto-symbol parsing.
Accept inputs such as:
BTC
BTC-USD
BTC-USDT
BTC/USDC
BTC-PERP
ETH
SOL-PERP
HYPE


Normalize them internally into an immutable model containing:
base_asset: str
quote_asset: str
venue: str
instrument_type: Literal["perp", "spot"]
venue_symbol: str
display_symbol: str


For the default Hyperliquid perpetual venue:
BTC-USD -> base_asset BTC -> venue_symbol BTC
BTC-PERP -> base_asset BTC -> venue_symbol BTC
HYPE -> base_asset HYPE -> venue_symbol HYPE


Do not alter stock symbol normalization.
Update cli/utils.py so valid standalone crypto symbols can be detected when crypto mode or the crypto command is selected. Preserve current suffix-based detection.
3. Add typed crypto market schemas
In tradingagents/crypto/schemas.py, create Pydantic models for:
CryptoInstrument
OHLCVCandle
OrderBookLevel
OrderBookSnapshot
DerivativesSnapshot
TechnicalSnapshot
MarketRegimeSnapshot
DataQuality
CryptoMarketSnapshot
EvidenceItem


CryptoMarketSnapshot must contain at least:
snapshot_id: str
timestamp: datetime
instrument: CryptoInstrument


mark_price: float | None
mid_price: float | None
oracle_price: float | None


candles: dict[str, list[OHLCVCandle]]
order_book: OrderBookSnapshot | None
derivatives: DerivativesSnapshot
technical: TechnicalSnapshot
regime: MarketRegimeSnapshot


data_quality: DataQuality
source_timestamps: dict[str, datetime]
warnings: list[str]


DerivativesSnapshot should support:
funding_rate
funding_history
open_interest
open_interest_change_24h_pct
perpetual_premium
day_notional_volume
day_price_change_pct
long_liquidations
short_liquidations


Fields unavailable from the selected public source should be None, not estimated.
TechnicalSnapshot should include deterministically calculated:
returns_1h
returns_4h
returns_24h
ema_20
ema_50
rsi_14
atr_14
realized_volatility
volume_change_pct
distance_from_ema20_pct
distance_from_ema50_pct
order_book_imbalance
spread_bps
support_levels
resistance_levels


MarketRegimeSnapshot should include:
trend: Literal["strong_uptrend", "uptrend", "range", "downtrend", "strong_downtrend"]
volatility: Literal["low", "normal", "high", "extreme"]
liquidity: Literal["thin", "normal", "deep"]
risk_mode: Literal["risk_on", "neutral", "risk_off"]
confidence: float
reasons: list[str]


4. Build a Hyperliquid public market-data adapter
Create:
tradingagents/dataflows/hyperliquid.py
tradingagents/dataflows/crypto_interface.py


Use the public Hyperliquid Info endpoint:
POST `https://api.hyperliquid.xyz/info`


Use the existing requests dependency unless there is a strong repository-specific reason to use another installed HTTP client.
Implement a reusable client with:
* Timeout handling
* Response validation
* Explicit user agent
* Small in-memory TTL cache
* Clear typed exceptions
* Retry only for transient errors
* No retries for invalid symbols
* No authentication requirement
* No exchange endpoint calls
Implement methods for:
get_asset_contexts()
get_candles(coin, interval, start_time, end_time)
get_l2_book(coin)
get_funding_history(coin, start_time, end_time)
get_market_snapshot(instrument, as_of=None)


Use the documented Hyperliquid request types, including:
metaAndAssetCtxs
candleSnapshot
l2Book
fundingHistory


Before relying on response field positions, inspect and validate the current response schema. Create defensive parsers because the API returns numeric values as strings.
Fetch candle intervals:
15m
1h
4h
1d


The snapshot builder should:
1. Fetch raw data.
2. Convert all timestamps to UTC.
3. Calculate indicators in Python.
4. Calculate order-book spread and imbalance.
5. Classify the market regime.
6. Produce a complete CryptoMarketSnapshot.
7. Record missing sources in data_quality.
8. Never fabricate unavailable fields.
Add a snapshot_id generated from venue, instrument and source timestamps so reports can be traced to the exact data snapshot.
5. Add deterministic crypto indicators
Implement indicator functions in tradingagents/crypto/indicators.py.
Use pandas where useful but do not depend on LLMs or third-party technical-analysis APIs.
Implement and test:
calculate_ema
calculate_rsi
calculate_atr
calculate_realized_volatility
calculate_returns
calculate_volume_change
calculate_order_book_imbalance
calculate_spread_bps
calculate_support_resistance
classify_market_regime


Functions must handle:
* Empty data
* Too few candles
* Missing values
* Zero volume
* Flat prices
* Numeric strings
* Unsorted timestamps
Return None where a valid calculation is impossible.
6. Integrate crypto tools into the existing agent system
Add LangChain tools in tradingagents/agents/utils/agent_utils.py:
get_crypto_market_snapshot
get_crypto_candles
get_crypto_derivatives
get_crypto_order_book
get_crypto_regime


The main tool should return a concise JSON-compatible representation of the verified snapshot.
Do not dump hundreds of raw candles into the LLM prompt. Return:
* Calculated metrics
* Recent candle summary
* Important levels
* Derivatives metrics
* Order-book metrics
* Data-quality warnings
* Snapshot timestamp
* Snapshot ID
Store the full snapshot in graph state and save it as JSON in the report directory.
7. Replace the crypto analyst team
Keep the existing stock analysts operational.
For asset_type="crypto", use these analysts:
Market Structure Analyst
Derivatives Analyst
Sentiment Analyst
Catalyst Analyst
Regime Analyst


Create:
tradingagents/agents/analysts/derivatives_analyst.py
tradingagents/agents/analysts/regime_analyst.py
tradingagents/agents/analysts/catalyst_analyst.py


Modify the existing market analyst so that in crypto mode it becomes the Market Structure Analyst.
The Market Structure Analyst must analyze:
* Multi-timeframe trend
* Momentum
* ATR and realized volatility
* Volume behavior
* Support and resistance
* Spread
* Order-book imbalance
* Entry quality
* Conditions that invalidate its view
The Derivatives Analyst must analyze:
* Funding
* Funding trend
* Open interest
* Open-interest change
* Perpetual premium
* Day volume
* Crowded positioning
* Potential squeeze conditions
* Data limitations
The Sentiment Analyst should remain grounded in retrieved sources but use crypto-oriented language and avoid company-specific terminology.
The Catalyst Analyst should replace the crypto use of the current News Analyst. It should focus on:
* Protocol announcements
* Listings and delistings
* Token unlocks
* Governance
* Security incidents
* Regulation
* Macroeconomic events
* Exchange events
* Market-wide crypto catalysts
It must distinguish confirmed events from speculation.
The Regime Analyst should synthesize:
* BTC market direction
* Broad risk-on or risk-off conditions
* Volatility regime
* Liquidity regime
* Whether altcoin exposure is appropriate
* Whether the current environment favors momentum, mean reversion or no trade
Do not create an on-chain analyst unless the repository has a real configured on-chain data source. Do not build an agent around placeholder data.
8. Extend graph state and graph construction
Update tradingagents/agents/utils/agent_states.py with:
crypto_snapshot
derivatives_report
catalyst_report
regime_report
trade_proposal
risk_decision
strategy_profile
paper_execution_result


Update tradingagents/graph/analyst_execution.py with crypto analyst specifications.
Update tradingagents/graph/setup.py so graph construction depends on asset type.
Stock graph:
Existing stock workflow, unchanged


Crypto graph:
Snapshot Builder
→ Market Structure Analyst
→ Derivatives Analyst
→ Sentiment Analyst
→ Catalyst Analyst
→ Regime Analyst
→ Bull Researcher
→ Bear Researcher
→ Research Manager
→ Crypto Trader
→ Existing Risk Debate
→ Portfolio Manager
→ Deterministic Risk Gate
→ END


The Snapshot Builder must run once. Every crypto analyst must use the same immutable snapshot. Do not let each analyst independently fetch market data.
Include asset type, strategy profile, venue and instrument type in the checkpoint graph signature.
Make graph logging resilient when stock-only or crypto-only report fields are absent.
9. Replace stock-style crypto decisions with structured trade proposals
Extend tradingagents/agents/schemas.py.
Do not remove the existing stock schemas.
Add:
class CryptoTradeAction(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    NO_TRADE = "NO_TRADE"


Create CryptoTradeProposal with:
action: CryptoTradeAction
instrument: CryptoInstrument
venue: str
time_horizon: str


entry_min: float | None
entry_max: float | None
stop_loss: float | None
take_profit_levels: list[float]


requested_position_pct: float
requested_leverage: float
confidence: float


thesis: str
invalidation: str
supporting_evidence: list[EvidenceItem]
risks: list[str]
snapshot_id: str
data_timestamp: datetime
no_trade_reason: str | None


Validation rules:
* Confidence must be between 0 and 1.
* Position percentage cannot be negative.
* Leverage must be at least 1 when trading.
* LONG requires stop below entry.
* SHORT requires stop above entry.
* NO_TRADE must contain no_trade_reason.
* NO_TRADE must not request position size.
* At least one take-profit level is required for LONG or SHORT.
* Snapshot ID is required.
* Reject NaN and infinite values.
* Do not automatically repair logically invalid prices inside the Pydantic model.
Create deterministic markdown and JSON renderers.
The crypto Trader prompt must explicitly permit NO_TRADE and must not force a directional recommendation.
The Trader should cite evidence by metric and snapshot ID rather than making unsupported claims.
10. Implement a deterministic risk engine
Create:
tradingagents/risk/
├── __init__.py
├── schemas.py
├── engine.py
└── sizing.py


Create RiskDecision with:
approved: bool
final_action: CryptoTradeAction
approved_position_pct: float
approved_leverage: float
risk_per_trade_pct: float
estimated_reward_risk: float | None
estimated_spread_bps: float | None
rejection_reasons: list[str]
adjustments: list[str]
warnings: list[str]


The deterministic risk engine must run after the Portfolio Manager and be the final authority.
It must:
1. Reject trades with missing entry, stop or take-profit.
2. Reject stale market snapshots.
3. Reject logically invalid stops.
4. Reject trades below minimum reward-to-risk.
5. Reject trades when spread exceeds the configured maximum.
6. Clamp leverage to the configured maximum.
7. Clamp position size to the configured maximum.
8. Calculate volatility-adjusted and stop-distance-adjusted position sizing.
9. Ensure estimated loss at the stop does not exceed configured portfolio risk.
10. Reduce position size during high volatility.
11. Reduce position size when confidence is low.
12. Reject trades when confidence is below 0.50.
13. Preserve NO_TRADE without attempting to convert it into a trade.
14. Return deterministic reasons for every adjustment or rejection.
Suggested sizing:
risk_budget = portfolio_equity * risk_per_trade_pct
stop_distance_pct = abs(entry_price - stop_loss) / entry_price
risk_based_notional = risk_budget / stop_distance_pct
position_cap_notional = portfolio_equity * max_position_pct
approved_notional = min(risk_based_notional, position_cap_notional)


Apply leverage only after calculating risk-based exposure. Never allow leverage to bypass the maximum loss constraint.
The final human-readable report must clearly show:
Trader Proposal
Portfolio Manager View
Deterministic Risk Decision
Final Approved Action


11. Add six Circuit strategy profiles
Create:
tradingagents/strategies/
├── __init__.py
├── loader.py
├── balanced.yaml
├── momentum.yaml
├── mean_reversion.yaml
├── derivatives.yaml
├── narrative.yaml
├── macro_regime.yaml
└── quant_systematic.yaml


Each strategy profile should define:
name:
description:
analyst_weights:
prompt_overlay:
preferred_time_horizon:
minimum_confidence:
max_position_pct:
max_leverage:
risk_per_trade_pct:


Strategy behavior:
* balanced: Uses all analyst reports evenly.
* momentum: Favors trend, volume expansion and continuation.
* mean_reversion: Favors stretched prices, funding extremes and exhaustion.
* derivatives: Favors funding, OI, premium and squeeze signals.
* narrative: Favors confirmed catalysts and sentiment acceleration.
* macro_regime: Trades only when market regime and directional thesis align.
* quant_systematic: Gives the greatest weight to deterministic metrics and should choose NO_TRADE frequently.
Do not create six different codebases or six independent market-data requests.
All strategies must:
* Use the same snapshot
* Use the same fees
* Use the same risk engine
* Use the same paper execution engine
* Differ only through configuration, prompts and risk parameters
Pass strategy_profile through graph state and report metadata.
12. Implement paper portfolio and simulated execution
Create:
tradingagents/paper/
├── __init__.py
├── database.py
├── portfolio.py
├── execution.py
├── performance.py
└── schemas.py


Use SQLite at the configured database path.
Create tables for:
portfolios
orders
fills
positions
equity_snapshots
strategy_runs


Store:
* Strategy
* Snapshot ID
* Instrument
* Side
* Entry
* Stop
* Take profits
* Size
* Leverage
* Fee
* Slippage
* Realized PnL
* Unrealized PnL
* Timestamp
* Source proposal
* Risk decision
Paper execution rules:
* Paper execution is disabled unless explicitly requested.
* Fill approved trades at current mid price plus configured directional slippage.
* Apply configured fees.
* Reject execution when no current mid price exists.
* Never execute rejected or NO_TRADE decisions.
* Prevent duplicate execution of the same strategy and snapshot ID.
* Support one net position per strategy and instrument.
* Mark positions to market using current mark price.
* Calculate realized and unrealized PnL deterministically.
* Record all changes transactionally.
* Never connect to the Hyperliquid Exchange endpoint.
* Never request or store wallet credentials.
Add performance calculations:
total_return
realized_pnl
unrealized_pnl
win_rate
profit_factor
maximum_drawdown
sharpe_ratio
average_leverage
fees_paid
trade_count


Return None for metrics that cannot yet be calculated rather than producing misleading zeros.
13. Extend the CLI
Keep the current CLI entry point.
Add non-interactive commands similar to:
tradingagents crypto analyze BTC
tradingagents crypto analyze ETH --strategy momentum
tradingagents crypto analyze SOL --interval 1h
tradingagents crypto analyze HYPE --strategy derivatives --paper
tradingagents crypto portfolio
tradingagents crypto positions
tradingagents crypto leaderboard


Exact Typer organization should follow the repository’s current CLI style.
The analyze command should support:
symbol
--strategy
--venue
--instrument
--interval
--date
--paper
--json
--checkpoint


Default to analysis only. --paper may execute only the deterministic risk-approved proposal.
leaderboard should rank strategy profiles using:
Total return
Sharpe ratio
Maximum drawdown
Profit factor
Win rate
Fees paid
Trade count


When there is insufficient history, show the available metrics and an explicit insufficient-history label.
Update interactive analyst selection to display crypto analyst names when crypto is selected.
14. Reporting and auditability
For every crypto run, save:
run_metadata.json
market_snapshot.json
market_structure_report.md
derivatives_report.md
sentiment_report.md
catalyst_report.md
regime_report.md
research_debate.md
research_plan.md
trade_proposal.json
trade_proposal.md
portfolio_manager_report.md
risk_decision.json
final_decision.md
paper_execution.json


paper_execution.json should only exist when paper execution was requested.
run_metadata.json must include:
run_id
snapshot_id
symbol
canonical_instrument
venue
strategy
analysis_timestamp
snapshot_timestamp
asset_type
model_provider
quick_model
deep_model
framework_version
paper_execution_requested


Do not expose API keys or full environment variables.
Update tradingagents/reporting.py without breaking stock reports.
15. Improve memory and evaluation for crypto
The existing memory log evaluates stock decisions using a fixed future return and benchmark.
For crypto:
* Use BTC as the default benchmark for altcoin decisions.
* Use raw return only for BTC.
* Store the structured action, entry, stop, targets and confidence.
* Resolve LONG and SHORT outcomes correctly.
* Do not evaluate NO_TRADE as though it were a directional position.
* Preserve unresolved entries when sufficient future candle data is unavailable.
* Record maximum favorable excursion and maximum adverse excursion when possible.
* Record whether the stop or a take-profit level was reached.
* Record confidence calibration separately from profitability.
Keep stock reflection behavior unchanged.
16. Add comprehensive tests
Create fixtures under:
tests/fixtures/hyperliquid/


Include sanitized example responses for:
metaAndAssetCtxs
candleSnapshot
l2Book
fundingHistory


Add tests for:
test_crypto_instruments.py
test_crypto_schemas.py
test_hyperliquid_adapter.py
test_crypto_indicators.py
test_crypto_snapshot.py
test_crypto_graph.py
test_crypto_trade_proposal.py
test_crypto_risk_engine.py
test_strategy_profiles.py
test_paper_execution.py
test_crypto_reporting.py
test_crypto_cli.py


Tests must verify:
* Every accepted symbol normalization path
* Invalid symbol rejection
* String-to-number API parsing
* Missing API fields
* Empty candles
* Unsorted candles
* Indicator correctness
* Snapshot immutability
* Snapshot ID stability
* Analyst graph order
* Shared snapshot usage
* LONG validation
* SHORT validation
* NO_TRADE validation
* Risk rejection for invalid stops
* Risk rejection for poor reward-to-risk
* Leverage clamping
* Position-size clamping
* High-volatility size reduction
* Stale data rejection
* Fee calculation
* Slippage calculation
* Long and short PnL
* Duplicate execution protection
* SQLite persistence
* Leaderboard metrics
* Existing stock tests remain passing
No test should require internet access or an LLM API key.
17. Documentation
Rewrite the README introduction to present Circuit Framework as:
A crypto-native multi-agent research and paper-trading framework where specialized agents analyze market structure, derivatives, sentiment, catalysts and market regime before a deterministic risk engine approves or rejects each trade.
Document:
* Architecture
* Crypto analyst roles
* Hyperliquid public-data integration
* Supported symbols
* Strategy profiles
* Structured proposal format
* Risk rules
* Paper-trading commands
* Environment variables
* Testing
* Known limitations
* Research-only disclaimer
* Upstream TradingAgents attribution
Clearly state:
* This is not financial advice.
* LLM output can be incorrect.
* Paper results do not represent live execution.
* No real trades are placed.
* On-chain data is not included until a verified provider is configured.
* Liquidation data may be unavailable depending on public-data coverage.
Add an architecture diagram in Mermaid.
18. Backward compatibility
The following must continue to work:
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG


ta = TradingAgentsGraph(config=DEFAULT_CONFIG.copy())
state, decision = ta.propagate("AAPL", "2026-01-15")


Add crypto support through:
ta = TradingAgentsGraph(
    selected_analysts=[
        "market",
        "derivatives",
        "social",
        "catalyst",
        "regime",
    ],
    config=config,
)


state, decision = ta.propagate(
    "BTC",
    "2026-07-14",
    asset_type="crypto",
    strategy_profile="balanced",
)


Extend method signatures compatibly. Existing callers that do not provide strategy_profile must continue working.
19. Implementation sequence
Complete the work in this order:
1. Inspect current architecture and tests.
2. Add schemas and instrument normalization.
3. Add Hyperliquid adapter and fixtures.
4. Add deterministic indicators and snapshot builder.
5. Add crypto tools and state fields.
6. Add crypto analysts.
7. Update graph construction.
8. Add structured crypto trade proposal.
9. Add deterministic risk engine.
10. Add strategy profiles.
11. Add paper portfolio.
12. Add CLI commands.
13. Add reporting.
14. Add memory evaluation.
15. Update documentation.
16. Run and repair the entire test suite.
Do not stop after scaffolding. Do not leave TODO implementations or methods raising NotImplementedError.
20. Required completion checks
Run all applicable commands and fix failures:
python -m pip install -e .
pytest -q
ruff check .
python -m cli.main --help
tradingagents --help
tradingagents crypto --help


Also run a local mocked smoke test that:
1. Loads the BTC fixture.
2. Builds a crypto snapshot.
3. Generates a valid sample trade proposal.
4. Passes it through the risk engine.
5. Executes it in a temporary paper database.
6. Reads back the resulting position.
Do not require live APIs for the smoke test.
At completion, provide:
1. A concise implementation summary.
2. The final repository tree for new files.
3. Existing files modified.
4. Test results.
5. Example commands.
6. Any genuinely incomplete items.
7. Any assumptions made.
Prioritize correctness, testability and a complete working vertical slice over unnecessary abstraction.