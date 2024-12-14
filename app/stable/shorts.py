# shorts.py
from ftplib import FTP
from datetime import datetime
import pytz
from typing import Dict, Tuple
import csv
from pathlib import Path
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ShortStockManager:
    def __init__(self):
        self.availability_dict: Dict[str, int] = {}
        self.last_updated: datetime = None
        self.scheduler = AsyncIOScheduler()
        
    async def fetch_and_parse_short_availability(self) -> None:
        """
        Fetches and parses the IB short stock availability data.
        Updates internal dictionary and timestamp.
        """
        try:
            logger.info("Starting short stock data update")
            
            # Connect to IB FTP
            ftp = FTP('ftp2.interactivebrokers.com')
            ftp.login('shortstock', '')
            
            # Download usa.txt content
            content = []
            def handle_line(line):
                content.append(line)
            
            ftp.retrlines('RETR usa.txt', handle_line)
            ftp.quit()
            
            # Find the BOF line for timestamp and convert to UTC
            ny_tz = pytz.timezone('America/New_York')
            new_availability: Dict[str, int] = {}
            
            for line in content:
                if line.startswith('#BOF'):
                    bof_parts = line.split('|')
                    date_str = bof_parts[1]
                    time_str = bof_parts[2]
                    
                    # Parse the timestamp in NY timezone
                    ny_time = ny_tz.localize(
                        datetime.strptime(f"{date_str} {time_str}", "%Y.%m.%d %H:%M:%S")
                    )
                    # Convert to UTC
                    self.last_updated = ny_time.astimezone(pytz.UTC)
                    continue
                
                if not line.startswith('#'):
                    fields = line.split('|')
                    if len(fields) >= 8:
                        symbol = fields[0]
                        available = fields[7]
                        
                        if available.startswith('>'):
                            available = available[1:]
                        try:
                            shares = int(available.replace(',', ''))
                            new_availability[symbol] = shares
                        except ValueError:
                            continue
            
            # Update the dictionary atomically
            self.availability_dict = new_availability
            
            logger.info(f"Short stock data updated successfully. Total symbols: {len(self.availability_dict)}")
            
            # Export to CSV if needed
            await self.export_to_csv()
            
        except Exception as e:
            logger.error(f"Error updating short stock data: {str(e)}")
    
    async def export_to_csv(self) -> None:
        """Exports the current data to a CSV file."""
        try:
            if not self.availability_dict or not self.last_updated:
                return
            
            timestamp = self.last_updated.strftime("%Y%m%d_%H%M%S")
            filename = f"short_availability_{timestamp}.csv"
            
            # Get script directory and create full path
            script_dir = Path(__file__).parent
            filepath = script_dir / filename
            
            # Write to CSV with ISO format timestamp
            with open(filepath, 'w', newline='') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(['Symbol', 'Available_Shares', 'Last_Updated'])
                for symbol, shares in sorted(self.availability_dict.items()):
                    writer.writerow([symbol, shares, self.last_updated.isoformat()])
            
            logger.info(f"CSV exported to: {filepath}")
            
        except Exception as e:
            logger.error(f"Error exporting CSV: {str(e)}")
    
    def get_availability(self, symbol: str) -> int:
        """Get the number of shares available for a symbol."""
        return self.availability_dict.get(symbol.upper())
    
    def get_last_updated(self) -> datetime:
        """Get the timestamp of the last update."""
        return self.last_updated
    
    def start_scheduler(self):
        """Start the background scheduler for data updates."""
        self.scheduler.add_job(
            self.fetch_and_parse_short_availability,
            CronTrigger(minute='*/15'),  # Run every 15 minutes
            id='short_stock_updater',
            name='Update short stock availability',
            replace_existing=True
        )
        self.scheduler.start()
        logger.info("Short stock update scheduler started")
    
    def stop_scheduler(self):
        """Stop the background scheduler."""
        self.scheduler.shutdown()
        logger.info("Short stock update scheduler stopped")

# Global instance for FastAPI to use
short_stock_manager = ShortStockManager()