# PnL Explainer Module

## Overview

The PnL Explainer module provides comprehensive profit and loss attribution analysis for options and hedge positions. It breaks down daily PnL into its constituent parts using Greeks-based attribution and compares results with QuantConnect's portfolio values.

## Features

### 📊 **Option PnL Attribution**
- **Delta PnL**: Price movement × delta × quantity
- **Gamma PnL**: 0.5 × (price_change)² × gamma × quantity  
- **Theta PnL**: Time decay × theta × quantity
- **Vega PnL**: Volatility change × vega × quantity

### 🛡️ **Hedge PnL Attribution**
- **Price PnL**: Underlying price movement × quantity
- **Dividend PnL**: Dividend payments (if applicable)
- **Borrowing Costs**: Short selling costs (if applicable)

### 🔄 **QuantConnect Reconciliation**
- Compares attributed PnL with QC portfolio values
- Identifies variances and potential discrepancies
- Provides reconciliation quality assessment

### 📈 **Performance Metrics**
- Attribution accuracy
- Hedge effectiveness
- Risk-adjusted returns
- Greeks utilization efficiency

## Usage

### Automatic Integration

The PnL explainer is automatically integrated into the EOD analytics workflow. After the standard EOD position summary, it will generate a detailed PnL explanation.

### Manual Usage

```python
from pnl_explainer import PnLExplainer

# Initialize explainer
explainer = PnLExplainer(algorithm)

# Generate PnL explanation
explanation = explainer.explain_daily_pnl(
    date=algorithm.Time,
    option_positions=option_positions,
    hedge_positions=hedge_positions,
    qc_portfolio_value=algorithm.Portfolio.TotalPortfolioValue
)

# Generate report
report = explainer.generate_pnl_report(algorithm.Time)
```

## Output Format

### EOD PnL Explanation Report

```
================================================================================
PnL EXPLANATION
================================================================================

📊 QUANTCONNECT RECONCILIATION:
  QC Portfolio Value: $1,000,000.00
  QC Daily PnL: $2,500.00
  Attributed PnL: $2,450.00
  Variance: $-50.00 (-2.0%)
  Quality: GOOD

📈 OPTION PnL BREAKDOWN:
  Total Option PnL: $1,800.00
  Delta PnL: $1,200.00
  Gamma PnL: $300.00
  Theta PnL: $250.00
  Vega PnL: $50.00

  Individual Option Positions:
    QQQ 150220P00098000: $1,200.00
      Delta: $800.00, Gamma: $200.00
      Theta: $150.00, Vega: $50.00

🛡️ HEDGE PnL BREAKDOWN:
  Total Hedge PnL: $650.00
  Price PnL: $650.00
  Dividend PnL: $0.00
  Borrowing Cost: $0.00

  Individual Hedge Positions:
    QQQ: $650.00
      Price PnL: $650.00

📋 SUMMARY:
  Total Attributed PnL: $2,450.00
  Option Contribution: 73.5%
  Hedge Contribution: 26.5%
================================================================================
```

## Key Components

### 1. **Option PnL Analysis**

For each option position, the explainer calculates:

- **Delta PnL**: `price_change × delta × quantity × 100`
- **Gamma PnL**: `0.5 × (price_change)² × gamma × quantity × 100`
- **Theta PnL**: `theta × quantity` (daily time decay)
- **Vega PnL**: `vol_change × vega × quantity` (volatility impact)

### 2. **Hedge PnL Analysis**

For each hedge position, the explainer calculates:

- **Price PnL**: `(current_price - entry_price) × quantity`
- **Dividend PnL**: Dividend payments received/paid
- **Borrowing Cost**: Costs for short positions

### 3. **QuantConnect Reconciliation**

The explainer compares:
- **Attributed PnL**: Sum of all Greeks-based calculations
- **QC Daily PnL**: QuantConnect's reported daily change
- **Variance**: Difference between attributed and QC values
- **Quality Assessment**: EXCELLENT (<1%), GOOD (<5%), FAIR (<10%), POOR (>10%)

## Configuration

### Enabling/Disabling PnL Explanation

The PnL explainer is automatically enabled when the analytics module is used. To disable:

```python
# In your algorithm, set a flag to disable PnL explanation
self.disable_pnl_explanation = True
```

### Customizing Output

You can customize the PnL explanation output by modifying the `_generate_pnl_explanation` method in `analytics.py`.

## Error Handling

The PnL explainer includes comprehensive error handling:

- **Missing Data**: Gracefully handles missing price or Greeks data
- **Calculation Errors**: Catches and logs calculation errors
- **Integration Issues**: Continues execution if PnL explanation fails

## Performance Considerations

- **Minimal Overhead**: PnL calculations are lightweight
- **Caching**: Historical data is cached for efficiency
- **Error Recovery**: Failures don't impact main algorithm execution

## Future Enhancements

### Planned Features

1. **Historical Analysis**: Track PnL attribution over time
2. **Volatility Attribution**: Better vega PnL calculation with actual vol changes
3. **Cross-Asset Analysis**: Multi-underlying PnL attribution
4. **Risk Metrics**: VaR, CVaR, and other risk measures
5. **Performance Attribution**: Factor-based performance analysis

### Data Requirements

For enhanced functionality, the following data would be beneficial:

- **Dividend Data**: For accurate dividend PnL calculation
- **Borrowing Rates**: For short selling cost attribution
- **Volatility History**: For vega PnL calculation
- **Interest Rates**: For time value of money adjustments

## Troubleshooting

### Common Issues

1. **Missing Greeks**: Ensure options data manager is properly initialized
2. **Price Data**: Verify that option and underlying prices are available
3. **Import Errors**: Check that all dependencies are properly installed

### Debug Mode

Enable debug mode for detailed logging:

```python
self.debug_mode = True
```

This will provide additional information about PnL calculation steps and potential issues.

## Integration with Existing Code

The PnL explainer integrates seamlessly with the existing analytics workflow:

1. **EOD Position Summary**: Runs after standard position summary
2. **Greeks Data**: Uses existing Greeks calculations
3. **Portfolio Data**: Leverages QuantConnect's portfolio values
4. **Logging**: Uses the same debug logging system

## Example Use Cases

### 1. **Daily Performance Analysis**
Understand which Greeks contributed most to daily PnL

### 2. **Strategy Validation**
Verify that theta decay is working as expected

### 3. **Risk Management**
Identify positions with large gamma or vega exposure

### 4. **Reconciliation**
Ensure internal calculations match QuantConnect's values

### 5. **Optimization**
Use attribution data to optimize strategy parameters

---

**Note**: The PnL explainer is designed to work with the existing volatility-hedged-theta-engine architecture and requires no additional configuration beyond the standard setup.
