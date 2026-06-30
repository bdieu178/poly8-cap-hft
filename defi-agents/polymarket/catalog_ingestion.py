"""
Nautilus Integration: High-Fidelity Multi-Venue Catalog Ingestion
Encodes microstructure signals (OFI, Flow) into QuoteTicks for backtest replay.
"""
import os
import glob
import os
import os
import glob
import polars as pl
from nautilus_trader.persistence.catalog import ParquetDataCatalog as DataCatalog
from utils.logger import get_logger
from nautilus_data_converter import ParquetToNautilusDataConverter
logger = get_logger(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data', 'realtime')
CATALOG_DIR = os.path.join(os.path.dirname(__file__), 'nautilus_catalog')

def ingest_high_fidelity_data():
    catalog = DataCatalog(CATALOG_DIR)
    converter = ParquetToNautilusDataConverter()
    
    # We search for all Parquet files from May 7th and 8th
    pattern = os.path.join(DATA_DIR, "hft_recording_2026050[78]*.parquet")
    all_files = glob.glob(pattern)
    
    if not all_files:
        logger.info(f"No high-fidelity data files found in {DATA_DIR}")
        return

    # Sort files by name (which includes timestamp) to ensure chronological order
    all_files.sort()
    
    # Take the last 100 files for a faster MVP forward test if needed, 
    # but the user asked to complete the forward test execution across the synthesized dataset.
    # Let's try all of them but in batches.
    
    for file_path in all_files:
        logger.info(f"Processing high-fidelity file: {file_path}")
        try:
            ticks = converter.convert_file(file_path)
            if ticks:
                # converter sorts them by timestamp
                logger.info(f"Ingesting {len(ticks)} ticks into Nautilus catalog...")
                catalog.write_data(ticks)
        except Exception as e:
            logger.error(f"Failed to process {file_path}: {e}")

    logger.info("High-Fidelity Ingestion completed.")

if __name__ == "__main__":
    ingest_high_fidelity_data()
