"""
Contract Splitter
=================

Splits combined OHLCV data into per-contract files.
"""
import os
import logging
from pathlib import Path
from typing import Optional, List
import pandas as pd

logger = logging.getLogger(__name__)


class ContractSplitter:
    """
    Splits a combined DataFrame into per-contract CSV files.

    Responsibilities:
    - Group data by contract
    - Sort each contract by date
    - Save to individual files
    """

    def __init__(
        self,
        output_dir: str,
        contract_column: str = "contract",
        date_column: str = "date"
    ):
        """
        Initialize splitter.

        Args:
            output_dir: Directory to save per-contract files
            contract_column: Name of contract column
            date_column: Name of date column for sorting
        """
        self.output_dir = Path(output_dir)
        self.contract_column = contract_column
        self.date_column = date_column

    def split(
        self,
        df: pd.DataFrame,
        subdirectory: str = "sort_by_contract"
    ) -> List[str]:
        """
        Split DataFrame by contract and save to files.

        Args:
            df: Combined OHLCV DataFrame with contract column
            subdirectory: Subdirectory name for output files

        Returns:
            List of contract names that were saved
        """
        if self.contract_column not in df.columns:
            logger.error(f"[SPLITTER] Column '{self.contract_column}' not found")
            return []

        # Create output directory
        output_path = self.output_dir / subdirectory
        output_path.mkdir(parents=True, exist_ok=True)

        # Get unique contracts
        contracts = df[self.contract_column].unique()
        logger.info(f"[SPLITTER] Splitting {len(contracts)} contracts")

        saved_contracts = []

        for contract in contracts:
            # Filter for this contract
            contract_data = df[df[self.contract_column] == contract].copy()

            # Sort by datetime (minute data) or date (day data)
            if 'datetime' in contract_data.columns:
                contract_data = contract_data.sort_values('datetime')
            elif self.date_column in contract_data.columns:
                contract_data = contract_data.sort_values(self.date_column)

            # Save to CSV
            output_file = output_path / f"{contract}.csv"
            contract_data.to_csv(output_file, index=False)
            saved_contracts.append(str(contract))

        logger.info(f"[SPLITTER] Saved {len(saved_contracts)} contracts to {output_path}")
        return saved_contracts

    def split_from_file(
        self,
        input_file: str,
        subdirectory: str = "sort_by_contract"
    ) -> List[str]:
        """
        Load data from file and split by contract.

        Args:
            input_file: Path to combined CSV file
            subdirectory: Subdirectory name for output files

        Returns:
            List of contract names that were saved
        """
        if not os.path.exists(input_file):
            logger.error(f"[SPLITTER] File not found: {input_file}")
            return []

        df = pd.read_csv(input_file)
        logger.info(f"[SPLITTER] Loaded {len(df)} rows from {input_file}")

        return self.split(df, subdirectory)
