import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch


FILTER_PATH = Path(__file__).resolve().parents[1] / "filter.py"
SPEC = importlib.util.spec_from_file_location("lain_performance_filter", FILTER_PATH)
filter_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(filter_module)
Filter = filter_module.Filter


def run_without_event_loop(coroutine):
    """Drive async filter code whose mocked emitter has no suspension point."""
    try:
        coroutine.send(None)
    except StopIteration as completed:
        return completed.value
    finally:
        coroutine.close()
    raise AssertionError("The mocked filter coroutine unexpectedly suspended")


class LainFilterTests(unittest.TestCase):
    def setUp(self):
        self.filter = Filter()

    def test_lain_defaults_match_server_configuration(self):
        self.assertEqual(self.filter.valves.server_urls, "http://127.0.0.1:50002")
        self.assertEqual(self.filter.valves.context_size, 55000)

    def test_server_urls_are_normalized_and_deduplicated(self):
        self.filter.valves.server_urls = (
            " http://127.0.0.1:50002/v1/ , http://127.0.0.1:50002 ,,"
        )
        self.assertEqual(
            self.filter.get_server_urls(), ["http://127.0.0.1:50002"]
        )

    def test_counter_delta_rejects_counter_reset(self):
        self.assertEqual(Filter.counter_delta({"n": 12}, {"n": 20}, "n"), 8)
        self.assertIsNone(Filter.counter_delta({"n": 20}, {"n": 3}, "n"))

    def test_finished_response_emits_lain_performance_metrics(self):
        url = "http://127.0.0.1:50002"
        now = filter_module.time.perf_counter()
        self.filter.start_time = now - 10.0
        self.filter.first_token_time = now - 8.75
        self.filter.metrics_start = {
            url: {
                "llamacpp:tokens_predicted_total": 40,
                "llamacpp:tokens_predicted_seconds_total": 2.0,
                "llamacpp:prompt_tokens_total": 300,
            }
        }
        metrics_end = {
            "llamacpp:tokens_predicted_total": 60,
            "llamacpp:tokens_predicted_seconds_total": 3.0,
            "llamacpp:prompt_tokens_total": 320,
        }
        emitted_events = []

        async def emitter(payload):
            emitted_events.append(payload)

        event = {"choices": [{"finish_reason": "stop", "delta": {}}]}

        with (
            patch.object(self.filter, "get_server_urls", return_value=[url]),
            patch.object(self.filter, "get_llama_metrics", return_value=metrics_end),
            patch.object(self.filter, "get_context_usage", return_value=(10000, 55000)),
        ):
            result = run_without_event_loop(self.filter.stream(event, emitter))

        self.assertIs(result, event)
        emitted = emitted_events[0]["data"]["description"]
        self.assertIn("⏱️ 10.", emitted)
        self.assertIn("⚡ 1.25s", emitted)
        self.assertIn("🚀 20.0t/s", emitted)
        self.assertIn("🟢 10.0K/55.0K (20%)", emitted)
        self.assertIsNone(self.filter.start_time)

    def test_missing_metrics_still_reports_timing(self):
        url = "http://127.0.0.1:50002"
        self.filter.start_time = filter_module.time.perf_counter() - 3.0
        self.filter.first_token_time = None
        self.filter.metrics_start = {url: {}}
        emitted_events = []

        async def emitter(payload):
            emitted_events.append(payload)

        event = {"choices": [{"finish_reason": "stop", "delta": {}}]}

        with (
            patch.object(self.filter, "get_server_urls", return_value=[url]),
            patch.object(self.filter, "get_llama_metrics", return_value={}),
            patch.object(self.filter, "get_context_usage", return_value=(None, None)),
        ):
            run_without_event_loop(self.filter.stream(event, emitter))

        emitted = emitted_events[0]["data"]["description"]
        self.assertIn("⏱️ 3.", emitted)
        self.assertIn("⚡ TTFT n/d", emitted)
        self.assertIn("🚀 tok/s n/d", emitted)
        self.assertIn("⚪ contexto n/d", emitted)


if __name__ == "__main__":
    unittest.main()

