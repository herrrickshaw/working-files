#!/usr/bin/env python3
"""
Example: Analyze stock portfolio using newsvendor model.

This script demonstrates:
1. Loading a portfolio from INDmoney tax P&L report
2. Evaluating holdings with buy/hold/sell recommendations
3. Identifying top potential gainers for next 3 months
4. Analyzing holding costs vs opportunity costs
"""

import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from pctk.stock import TaxReportIngestor, PortfolioEvaluator


def main():
    """Analyze portfolio and generate recommendations."""

    # Example: Use your tax report file
    report_file = "/root/.claude/uploads/ecf54ba6-f0d7-5306-8497-93562fcc9b7b/e83e27d8-IndmoneyAnnualTaxPnlReportXLEKDZZGLM31Mar2026.csv"

    print("=" * 100)
    print("STOCK PORTFOLIO ANALYZER - NEWSVENDOR MODEL EVALUATION")
    print("=" * 100)
    print()

    # Load portfolio from tax report
    print(f"Loading portfolio from: {Path(report_file).name}")
    portfolio = TaxReportIngestor.from_indmoney_report(report_file)
    print(f"✓ Loaded {len(portfolio.positions)} stock positions")
    print()

    # Initialize evaluator
    evaluator = PortfolioEvaluator()

    # 1. Portfolio Summary
    print("=" * 100)
    print("1. PORTFOLIO SUMMARY")
    print("=" * 100)
    print(f"Total Cost Basis: ₹{portfolio.total_cost_basis:,.2f}")
    print(f"Current Value: ₹{portfolio.total_current_value:,.2f}")
    print(f"Unrealized P&L: ₹{portfolio.total_unrealized_gain_loss:,.2f}")
    print(f"Portfolio Return: {portfolio.portfolio_return_percent:.2f}%")
    print()

    # 2. Top Gainers
    print("=" * 100)
    print("2. TOP 10 POTENTIAL GAINERS (Next 3 Months)")
    print("=" * 100)
    gainers = evaluator.get_gainers_list(portfolio, top_n=10)
    for i, gainer in enumerate(gainers, 1):
        print(
            f"{i:2d}. {gainer['symbol']:<35} {gainer['sector']:<15} "
            f"Gain: {gainer['gain_potential_3m_pct']:>6.2f}% | "
            f"Current: {gainer['current_return_pct']:>7.2f}% | "
            f"Qty: {gainer['quantity']:>5} | Value: ₹{gainer['value']:>12,.0f}"
        )
    print()

    # 3. Hold vs Sell
    print("=" * 100)
    print("3. STOCKS TO HOLD/BUY")
    print("=" * 100)
    hold_list, sell_list = evaluator.get_hold_sell_list(portfolio)
    print(f"Total Hold/Buy stocks: {len(hold_list)}")
    if hold_list:
        for stock in hold_list[:12]:
            print(
                f"• {stock['symbol']:<35} [{stock['recommendation']:<12}] "
                f"Return: {stock['current_return_pct']:>7.2f}% | "
                f"Gain Pot: {stock['gain_potential_3m_pct']:>6.2f}% | "
                f"Value: ₹{stock['value']:>12,.0f}"
            )
    print()

    print("=" * 100)
    print("4. STOCKS TO SELL")
    print("=" * 100)
    print(f"Total Sell stocks: {len(sell_list)}")
    if sell_list:
        for stock in sell_list[:12]:
            holding_cost_str = f"₹{stock['holding_cost']:,.0f}"
            print(
                f"• {stock['symbol']:<35} [{stock['recommendation']:<12}] "
                f"Return: {stock['current_return_pct']:>7.2f}% | "
                f"Holding Cost: {holding_cost_str:>12} | "
                f"Value: ₹{stock['value']:>12,.0f}"
            )
    print()

    # 4. Generate full report
    print("=" * 100)
    print("5. DETAILED EVALUATION REPORT")
    print("=" * 100)
    report = evaluator.generate_report(portfolio)
    print(report)

    # 5. Newsvendor Model Insights
    print()
    print("=" * 100)
    print("6. NEWSVENDOR MODEL INSIGHTS")
    print("=" * 100)
    print("""
The Newsvendor Model is applied to optimize stock holdings:

CONCEPT:
- Holding Cost: Opportunity cost of capital tied up in stocks (~8% annually)
- Shortage Cost: Regret cost if stock rises without holding (~25% potential)
- Critical Ratio: (Shortage Cost) / (Holding Cost + Shortage Cost) = 76%

APPLICATION TO STOCKS:
- Underage Cost: Missing gains if stock appreciates
- Overage Cost: Opportunity cost of capital if stock underperforms
- Recommendation: Adjust holdings based on expected gain potential

INTERPRETATION:
- STRONG_BUY: High gain potential, low current holdings
- BUY: Good entry point, undervalued
- HOLD: Balanced risk/reward, maintain position
- SELL: Low gain potential, high holding costs
- STRONG_SELL: Negative outlook, divest immediately
""")

    print()
    print("=" * 100)
    print(f"Analysis completed for {len(portfolio.positions)} positions")
    print("=" * 100)


if __name__ == '__main__':
    main()
