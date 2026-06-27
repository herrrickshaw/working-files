# Stock Portfolio Evaluator

A comprehensive stock portfolio analysis tool using the **Newsvendor Model** for inventory optimization applied to stock holdings.

## Features

### 1. **Portfolio Ingestion**
- Load from Excel/CSV files
- Parse INDmoney tax P&L reports
- Support for custom stock data formats

### 2. **Stock Evaluation**
- **Buy/Hold/Sell Recommendations** based on multiple factors
- **3-Month Gain Potential** estimation using momentum and sector analysis
- **Newsvendor Model** for holding cost vs opportunity cost analysis
- **Sector Classification** with beta-adjusted expectations

### 3. **Newsvendor Model Analysis**
The newsvendor model optimizes inventory by balancing:
- **Holding Cost**: Opportunity cost of capital tied up (default: 8% annually)
- **Shortage Cost**: Regret cost if stock appreciates without holding (default: 25%)
- **Critical Ratio**: 76% threshold for optimal decision

## Usage

### Command Line

```bash
# Full portfolio evaluation with detailed report
python -m pctk.stock.cli evaluate your_portfolio.csv --report --output report.txt

# Show top 10 potential gainers for next 3 months
python -m pctk.stock.cli gainers your_portfolio.csv --top 10

# Get hold/sell recommendations
python -m pctk.stock.cli actions your_portfolio.csv
```

### Python API

```python
from pctk.stock import TaxReportIngestor, PortfolioEvaluator

# Load portfolio from INDmoney tax report
portfolio = TaxReportIngestor.from_indmoney_report("tax_report.csv")

# Evaluate
evaluator = PortfolioEvaluator()

# Get top gainers
gainers = evaluator.get_gainers_list(portfolio, top_n=5)
for gainer in gainers:
    print(f"{gainer['symbol']}: {gainer['gain_potential_3m_pct']:.2f}%")

# Get hold/sell lists
hold_list, sell_list = evaluator.get_hold_sell_list(portfolio)

# Generate report
print(evaluator.generate_report(portfolio))
```

## Input Formats

### INDmoney Tax P&L Report
```
CSV file with UNREALIZED P/L section containing:
- Stock Name
- ISIN
- Buy Qty
- Sell Qty
- Buy Amount
- Sell Amount
- Unrealized P/L
```

### Generic CSV
```
symbol,quantity,purchase_price,current_price[,sector]
TCS,10,3500,4200,Technology
HDFC,5,1500,1800,Financials
```

### Generic Excel
```
Same format as CSV
```

## Recommendation Logic

### Score Calculation (Range: -50 to +50)

1. **Current Performance** (-25 to +25):
   - Undervalued stocks (< -30% loss) get +25 (buy signal)
   - Overvalued stocks (> 30% gain) get -25 (sell signal)

2. **Future Potential** (-25 to +25):
   - High gain potential (>15%) gets +25
   - No gain potential gets -10

3. **Inventory Cost** (0 to -15):
   - High cost relative to gain reduces score

### Recommendations

- **STRONG_BUY** (score ≥ 30): Highly undervalued with high gain potential
- **BUY** (score ≥ 15): Good entry point
- **HOLD** (score ≥ -15): Balanced risk/reward
- **SELL** (score ≥ -30): Low gain potential, high costs
- **STRONG_SELL** (score < -30): Divest immediately

## 3-Month Gain Potential Estimation

Formula:
```
Gain Potential = Base (3%) + Momentum + Sector + Beta-Adjusted
```

Where:
- **Base**: 3% quarterly market expectation
- **Momentum**: Mean reversion boost if undervalued, penalty if overvalued
- **Sector**: Industry-specific growth expectations
- **Beta**: Market correlation adjustment

## Portfolio Metrics

- **Total Cost Basis**: Sum of all purchases
- **Current Value**: Current market value of holdings
- **Unrealized P&L**: Total gain/loss
- **Return %**: Overall portfolio return percentage

## Example Output

```
================================================================================
STOCK PORTFOLIO EVALUATION REPORT
================================================================================

PORTFOLIO SUMMARY
Total Positions: 107
Total Cost Basis: ₹101,084.97
Current Value: ₹89,156.96
Unrealized P&L: ₹-11,928.01
Portfolio Return: -11.80%

TOP 5 POTENTIAL GAINERS (Next 3 Months)
1. AARTI SURFACTANTS LIMITED - Gain Potential: 20.60%
2. GANGA FORGING LIMITED - Gain Potential: 20.60%
3. BEARDSELL LIMITED - Gain Potential: 20.60%

STOCKS TO HOLD/BUY
STRONG_BUY: 12 stocks | Total Value: ₹1,888 | Avg Gain Potential: 18.61%
BUY: 67 stocks | Total Value: ₹54,426 | Avg Gain Potential: 18.71%
HOLD: 28 stocks | Total Value: ₹32,843 | Avg Gain Potential: 12.57%

STOCKS TO SELL
No stocks recommended to sell

================================================================================
```

## Configuration

Adjustable parameters in `StockEvaluator`:

```python
evaluator = StockEvaluator(
    risk_free_rate=0.06,      # 6% risk-free rate
    market_return=0.12,        # 12% expected market return
)

newsvendor = NewsvendorModel(
    holding_cost_rate=0.08,    # 8% opportunity cost
    shortage_cost_rate=0.25,   # 25% regret cost
)
```

## Files

- `portfolio.py`: Portfolio and StockPosition classes
- `models.py`: NewsvendorModel and StockEvaluator
- `evaluator.py`: PortfolioEvaluator for comprehensive analysis
- `ingest.py`: Data ingestion from various formats
- `cli.py`: Command-line interface

## Example Script

See `examples/analyze_portfolio.py` for complete working example with your portfolio.
