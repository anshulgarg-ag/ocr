from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from config.settings import settings

_provider: TracerProvider | None = None


def init_tracing() -> None:
    global _provider
    resource = Resource.create({"service.name": "ocr-pipeline"})
    _provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint, insecure=True)
    _provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(_provider)


def get_tracer(name: str = "ocr-pipeline") -> trace.Tracer:
    return trace.get_tracer(name)
