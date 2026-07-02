"""Risk decision schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field

from tradingagents.crypto.schemas import CryptoTradeAction


class RiskDecision(BaseModel):
    approved: bool
    final_action: CryptoTradeAction
    approved_position_pct: float = 0.0
    approved_leverage: float = 1.0
    risk_per_trade_pct: float = 0.0
    estimated_reward_risk: float | None = None
    estimated_spread_bps: float | None = None
    rejection_reasons: list[str] = Field(default_factory=list)
    adjustments: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def to_markdown(self) -> str:
        lines = [
            "# Deterministic Risk Decision",
            "",
            f"- Approved: {'yes' if self.approved else 'no'}",
            f"- Final action: {self.final_action.value}",
            f"- Position: {self.approved_position_pct:.4f}%",
            f"- Leverage: {self.approved_leverage:.2f}x",
            f"- Risk per trade: {self.risk_per_trade_pct:.4f}%",
            f"- Reward/risk: {self.estimated_reward_risk}",
            f"- Spread (bps): {self.estimated_spread_bps}",
        ]
        if self.rejection_reasons:
            lines.append("")
            lines.append("## Rejection reasons")
            for r in self.rejection_reasons:
                lines.append(f"- {r}")
        if self.adjustments:
            lines.append("")
            lines.append("## Adjustments")
            for a in self.adjustments:
                lines.append(f"- {a}")
        if self.warnings:
            lines.append("")
            lines.append("## Warnings")
            for w in self.warnings:
                lines.append(f"- {w}")
        return "\n".join(lines) + "\n"
