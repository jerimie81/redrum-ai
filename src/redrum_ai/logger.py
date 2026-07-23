import logging
import json
import uuid
import os
from logging.handlers import RotatingFileHandler
from contextvars import ContextVar

# Correlation ID Context Variable
correlation_id: ContextVar[str] = ContextVar('correlation_id', default='')

def get_correlation_id() -> str:
    cid = correlation_id.get()
    if not cid:
        cid = str(uuid.uuid4())
        correlation_id.set(cid)
    return cid

def new_correlation_id() -> str:
    cid = str(uuid.uuid4())
    correlation_id.set(cid)
    return cid

class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
            "time": self.formatTime(record, self.datefmt),
            "name": record.name,
            "level": record.levelname,
            "message": record.getMessage(),
            "correlation_id": correlation_id.get(),
            "filename": record.filename,
            "lineno": record.lineno,
        }
        if record.exc_info:
            log_record["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(log_record)

def setup_logger(name: str, log_dir: str = os.path.expanduser("~/.gemini/redrum-ai/logs")) -> logging.Logger:
    os.makedirs(log_dir, exist_ok=True)
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    
    if not logger.handlers:
        # 10 MB per file, keep 5 backups
        log_file = os.path.join(log_dir, "redrum-ai.log")
        handler = RotatingFileHandler(log_file, maxBytes=10*1024*1024, backupCount=5)
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
        
    return logger

# Example usage
# logger = setup_logger("redrum_ai")
