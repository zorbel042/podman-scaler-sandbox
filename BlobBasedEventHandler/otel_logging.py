import logging
import sys
import json
from datetime import datetime
from typing import Tuple, Any


class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_entry = {
            "asctime": datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S,%f')[:-3],
            "levelname": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
            "taskName": None
        }
        
        # Add extra fields if present
        if hasattr(record, '__dict__'):
            for key, value in record.__dict__.items():
                if key not in ['name', 'msg', 'args', 'levelname', 'levelno', 'pathname', 'filename', 'module', 'exc_info', 'exc_text', 'stack_info', 'lineno', 'funcName', 'created', 'msecs', 'relativeCreated', 'thread', 'threadName', 'processName', 'process', 'message']:
                    log_entry[key] = value
        
        return json.dumps(log_entry)


def init_logging(service_name: str) -> Tuple[logging.Logger, Any]:
    logger = logging.getLogger(service_name)
    if logger.handlers:
        return logger, None

    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)

    # Return None as tracer since we're not using OTEL
    return logger, None 