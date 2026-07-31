"""
Benchmark/instrumentation check: voice pipeline latency is measured against the
sub-200ms target and exported to Prometheus.

This does NOT claim a latency number — live STT/TTS need network. It verifies the
*measurement* is real: observe_voice_latency() records per-stage samples into the
voice_latency_seconds histogram, the 200ms SLA sits on a bucket boundary (so quantiles
answer "are we under target?"), and a simulated pipeline under budget lands in the
sub-200ms buckets while one over budget does not.
"""

from apps.api.core.metrics import VOICE_LATENCY_SECONDS, observe_voice_latency


def _bucket_count(stage: str, le: str) -> float:
    """Cumulative count of observations <= `le` seconds for a stage label."""
    for metric in VOICE_LATENCY_SECONDS.collect():
        for s in metric.samples:
            if (
                s.name == "voice_latency_seconds_bucket"
                and s.labels.get("stage") == stage
                and s.labels.get("le") == le
            ):
                return s.value
    return 0.0


def _count(stage: str) -> float:
    for metric in VOICE_LATENCY_SECONDS.collect():
        for s in metric.samples:
            if (
                s.name == "voice_latency_seconds_count"
                and s.labels.get("stage") == stage
            ):
                return s.value
    return 0.0


class TestVoiceLatencyInstrumentation:
    def test_observation_is_recorded(self):
        """observe_voice_latency must record into the Prometheus histogram."""
        before = _count("stt")
        observe_voice_latency("stt", 95.0)  # 95ms
        assert _count("stt") == before + 1

    def test_200ms_target_is_a_bucket_boundary(self):
        """The 200ms SLA must be a histogram bucket edge so quantiles are meaningful."""
        # prometheus_client renders the 0.2s boundary as "0.2".
        observe_voice_latency("end_to_end", 150.0)
        assert _bucket_count("end_to_end", "0.2") >= 1.0

    def test_under_budget_pipeline_lands_in_sub_200ms_buckets(self):
        """A simulated STT+LLM+TTS pipeline under budget is counted under 200ms."""
        stage = "end_to_end"
        under_before = _bucket_count(stage, "0.2")
        # 80ms STT + 60ms LLM + 50ms TTS = 190ms end-to-end, under the 200ms target.
        observe_voice_latency(stage, 80 + 60 + 50)
        assert _bucket_count(stage, "0.2") == under_before + 1

    def test_over_budget_pipeline_excluded_from_sub_200ms_buckets(self):
        """A pipeline over budget must NOT be counted in the <=200ms bucket."""
        stage = "end_to_end"
        under_before = _bucket_count(stage, "0.2")
        observe_voice_latency(stage, 350.0)  # 350ms, over target
        # The <=0.2s cumulative count is unchanged; it shows up only in higher buckets.
        assert _bucket_count(stage, "0.2") == under_before
