"""OpenTelemetry bootstrap helpers.

Initialises a global TracerProvider with resource attributes and an OTLP exporter
driven by the application Settings.  Safe to call multiple times — subsequent
calls after the first are no-ops.
"""

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from wolfpack.config.settings import Settings

_bootstrapped = False


def bootstrap_tracing(settings: Settings) -> TracerProvider:
    """Initialise the global TracerProvider from Settings.

    Sets resource attributes (service.name, service.namespace,
    deployment.environment) and wires an OTLP HTTP exporter pointed at
    settings.otel.endpoint.  The global provider is set on first call only.
    """
    global _bootstrapped
    if _bootstrapped:
        return trace.get_tracer_provider()  # type: ignore[return-value]

    resource = Resource.create(
        {
            "service.name": settings.otel.service_name,
            "service.namespace": settings.otel.service_namespace,
            "deployment.environment": settings.deployment_mode.value,
        }
    )

    exporter = OTLPSpanExporter(endpoint=f"{settings.otel.endpoint}/v1/traces")
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(provider)
    _bootstrapped = True
    return provider