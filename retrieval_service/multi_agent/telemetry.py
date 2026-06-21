"""
Monitoring for the multi-agent module — wires ADK's built-in OpenTelemetry
instrumentation to Cloud Trace, Cloud Monitoring, and Cloud Logging.

Unlike the LangGraph layer (agent.py / retrieval_service.py), which needed a
hand-built structured-logging -> BigQuery Log Sink -> Looker Studio pipeline
(see monitoring.tf), ADK ships OTel instrumentation natively. Enabling GCP
export is a single function call — no custom log parsing required.

Verified against google-adk==2.3.0: get_gcp_exporters() and
maybe_set_otel_providers() signatures confirmed by local inspection.

What you get once this is wired in:
  Cloud Trace      -> full span per agent run: risk_analyst's tool call,
                       its latency, mitigation_advisor's turn, total duration
  Cloud Monitoring  -> token usage and request count metrics, auto-exported
  Cloud Logging     -> structured log entries per agent turn

This is the ADK-native equivalent of the BigQuery monitoring views built for
the LangGraph layer — same observability goal, framework-provided instead of
hand-rolled.
"""

import logging
import os

logger = logging.getLogger(__name__)

_initialized = False


def enable_gcp_telemetry() -> bool:
    """Wire ADK's OTel instrumentation to Cloud Trace/Monitoring/Logging.

    Call once at module import time. Safe to call multiple times — ADK's
    maybe_set_otel_providers() is a no-op if a provider is already set.

    Returns True if telemetry was enabled, False if it failed (e.g. no GCP
    credentials available — falls back silently so local dev still works).
    """
    global _initialized
    if _initialized:
        return True

    try:
        from google.adk.telemetry.google_cloud import get_gcp_exporters
        from google.adk.telemetry.setup import maybe_set_otel_providers

        hooks = get_gcp_exporters(
            enable_cloud_tracing=True,
            enable_cloud_metrics=True,
            enable_cloud_logging=True,
        )
        maybe_set_otel_providers([hooks])
        _initialized = True
        logger.info("ADK GCP telemetry enabled: Cloud Trace + Monitoring + Logging")
        return True

    except Exception as exc:
        # Don't let telemetry setup failures break the agent — log and continue.
        logger.warning("ADK GCP telemetry setup failed (continuing without it): %s", exc)
        return False
