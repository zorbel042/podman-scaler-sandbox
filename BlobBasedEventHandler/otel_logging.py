import logging
import os
import sys
from typing import Tuple

from opentelemetry import trace  # type: ignore
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter  # type: ignore
from opentelemetry.sdk.resources import SERVICE_NAME, Resource  # type: ignore
from opentelemetry.sdk.trace import TracerProvider  # type: ignore
from opentelemetry.sdk.trace.export import BatchSpanProcessor  # type: ignore
from pythonjsonlogger import jsonlogger  # type: ignore


def init_logging(service_name: str) -> Tuple[logging.Logger, trace.Tracer]:
    """Initialize structured JSON logging and OpenTelemetry tracing.

    Returns logger and tracer bound to the given service name.
    """
    logger = logging.getLogger(service_name)
    if logger.handlers:
        # Already configured – return existing tracer as well
        return logger, trace.get_tracer(__name__)

    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(jsonlogger.JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger.addHandler(handler)

    resource = Resource(attributes={SERVICE_NAME: service_name})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=os.getenv("OTLP_ENDPOINT", "http://localhost:4317"), insecure=True)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    tracer = trace.get_tracer(__name__)

    return logger, tracer 