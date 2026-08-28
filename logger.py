import logging
import os
from logging.handlers import RotatingFileHandler
import config

def setup_logger(name, log_file="app.log", level=logging.INFO):
    """Sets up a professional rotating logger."""
    
    # Path inside %AppData%\HybridOnCloud\logs
    log_dir = os.path.join(config.DATA_DIR, "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, log_file)
    
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # Rotating handler: Max 5MB per file, keep 5 backups
    handler = RotatingFileHandler(log_path, maxBytes=5*1024*1024, backupCount=5)
    handler.setFormatter(formatter)
    
    # Console handler for development
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.addHandler(handler)
    
    if not config.IS_FROZEN:
        logger.addHandler(console_handler)
        
    return logger

# Shared logger instance
logger = setup_logger("HybridToCloud")
