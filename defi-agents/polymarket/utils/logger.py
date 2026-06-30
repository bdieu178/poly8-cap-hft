import logging
import sys
import os
import json
import time

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs')
os.makedirs(LOG_DIR, exist_ok=True)

# Standardize to UTC for all log messages
logging.Formatter.converter = time.gmtime

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
            "time": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
            "module": record.module,
        }
        if record.exc_info:
            log_record["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(log_record)

def get_logger(name):
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        
        # Console Handler
        c_handler = logging.StreamHandler(sys.stdout)
        c_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s'))
        logger.addHandler(c_handler)
        
        # File Handler (JSON structured logs)
        f_handler = logging.FileHandler(os.path.join(LOG_DIR, 'pipeline.json.log'))
        f_handler.setFormatter(JSONFormatter())
        logger.addHandler(f_handler)
        
    return logger
