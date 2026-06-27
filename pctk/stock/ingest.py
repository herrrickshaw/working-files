"""Data ingestion for tax reports and portfolio files."""

import pandas as pd
from typing import List, Optional
from .portfolio import Portfolio, StockPosition


class TaxReportIngestor:
    """Ingest stock portfolio from tax P&L reports."""

    @staticmethod
    def from_indmoney_report(filepath: str) -> Portfolio:
        """
        Load portfolio from INDmoney tax P&L report CSV.

        Extracts unrealized holdings from the UNREALIZED P/L section.

        Args:
            filepath: Path to CSV file

        Returns:
            Portfolio object with all holdings
        """
        portfolio = Portfolio()

        # Read CSV
        df = pd.read_csv(filepath, header=None)

        # Find the UNREALIZED P/L section
        unrealized_idx = None
        for idx, row in df.iterrows():
            if isinstance(row[0], str) and "UNREALIZED P/L" in row[0].upper():
                unrealized_idx = idx
                break

        if unrealized_idx is None:
            raise ValueError("Could not find 'UNREALIZED P/L' section in CSV")

        # Headers are at unrealized_idx + 1
        header_idx = unrealized_idx + 1
        data_start_idx = unrealized_idx + 2

        # Extract headers
        headers = df.iloc[header_idx].tolist()
        # Map headers: Stock Name, ISIN, Buy Qty, Sell Qty, Buy Amount, Sell Amount, Unrealized P/L
        header_map = {
            0: 'stock_name',
            1: 'isin',
            2: 'buy_qty',
            3: 'sell_qty',
            4: 'buy_amount',
            5: 'sell_amount',
            6: 'unrealized_pl',
        }

        # Process rows
        for idx in range(data_start_idx, len(df)):
            row = df.iloc[idx]

            # Stop at empty rows
            if pd.isna(row[0]) or row[0] == '':
                break

            try:
                stock_name = str(row[0]).strip()
                buy_qty = int(float(row[2]))
                buy_amount_total = float(row[4])
                unrealized_pl = float(row[6])

                # Skip if no holdings or malformed data
                if buy_qty <= 0 or pd.isna(buy_amount_total) or buy_amount_total <= 0:
                    continue

                # Calculate average purchase price
                purchase_price = buy_amount_total / buy_qty

                # Calculate current value
                # current_value = buy_amount + unrealized_pl
                current_value = buy_amount_total + unrealized_pl

                # Handle edge case where current value might be negative or zero
                if current_value <= 0:
                    # Use purchase price as fallback
                    current_price = purchase_price * 0.5
                else:
                    current_price = max(current_value / buy_qty, 0.01)

                # Create position
                position = StockPosition(
                    symbol=stock_name.upper(),
                    quantity=buy_qty,
                    purchase_price=purchase_price,
                    current_price=current_price
                )

                portfolio.add_position(position)

            except (ValueError, IndexError, TypeError):
                # Skip malformed rows
                continue

        return portfolio

    @staticmethod
    def from_generic_csv(filepath: str) -> Portfolio:
        """
        Load portfolio from generic CSV with columns:
        symbol, quantity, purchase_price, current_price, [sector]

        Args:
            filepath: Path to CSV file

        Returns:
            Portfolio object
        """
        return Portfolio.from_csv(filepath)

    @staticmethod
    def from_generic_excel(filepath: str) -> Portfolio:
        """
        Load portfolio from generic Excel with columns:
        symbol, quantity, purchase_price, current_price, [sector]

        Args:
            filepath: Path to Excel file

        Returns:
            Portfolio object
        """
        return Portfolio.from_excel(filepath)
