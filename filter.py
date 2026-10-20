from pydantic import BaseModel, Field
from typing import Optional
import time
import requests


class Filter:
    class Valves(BaseModel):
        priority: int = Field(default=0, description="Execution priority")
        server_url: str = Field(
            default="http://127.0.0.1:50002",
            description="Base URL of the llama.cpp server",
        )
        context_size: int = Field(default=40192, description="Fallback context size")

    def __init__(self):
        self.valves = self.Valves()
        self.start_time = None
        self.first_token_time = None
        self.metrics_start = None

    def get_llama_metrics(self):
        try:
            response = requests.get(f"{self.valves.server_url}/metrics", timeout=1)
            response.raise_for_status()
            metrics = {}
            for line in response.text.splitlines():
                if not line.startswith("llamacpp:") or " " not in line:
                    continue
                name, value = line.rsplit(" ", 1)
                try:
                    metrics[name] = float(value)
                except ValueError:
                    pass
            return metrics
        except Exception:
            return {}

    def get_context_usage(self):
        try:
            response = requests.get(f"{self.valves.server_url}/slots", timeout=1)
            response.raise_for_status()
            slots = response.json()
            if isinstance(slots, list) and slots:
                slot = slots[0]
                return (
                    int(slot.get("n_prompt_tokens", 0)),
                    int(slot.get("n_ctx", self.valves.context_size)),
                )
        except Exception:
            pass
        return 0, self.valves.context_size

    async def inlet(self, body: dict, __metadata__: Optional[dict] = None) -> dict:
        self.start_time = time.perf_counter()
        self.first_token_time = None
        self.metrics_start = self.get_llama_metrics()
        return body

    async def stream(self, event: dict, __event_emitter__=None) -> dict:
        now = time.perf_counter()
        for choice in event.get("choices", []):
            content = choice.get("delta", {}).get("content")
            if content and self.first_token_time is None:
                self.first_token_time = now

        finished = event.get("done") is True or any(
            choice.get("finish_reason") is not None
            for choice in event.get("choices", [])
        )

        if finished and self.start_time is not None:
            total_time = now - self.start_time
            ttft = (
                self.first_token_time - self.start_time
                if self.first_token_time is not None
                else total_time
            )
            metrics_end = self.get_llama_metrics()
            generated_tokens = 0
            generation_seconds = 0.0
            if self.metrics_start and metrics_end:
                generated_tokens = max(
                    0,
                    int(
                        metrics_end.get("llamacpp:tokens_predicted_total", 0)
                        - self.metrics_start.get("llamacpp:tokens_predicted_total", 0)
                    ),
                )
                generation_seconds = max(
                    0.0,
                    metrics_end.get("llamacpp:tokens_predicted_seconds_total", 0)
                    - self.metrics_start.get("llamacpp:tokens_predicted_seconds_total", 0),
                )
            tokens_per_second = (
                generated_tokens / generation_seconds
                if generated_tokens > 0 and generation_seconds > 0
                else 0
            )
            context_used, context_max = self.get_context_usage()
            context_percent = context_used / context_max * 100 if context_max > 0 else 0
            context_icon = (
                "🔴" if context_percent >= 95 else
                "🟠" if context_percent >= 85 else
                "🟡" if context_percent >= 70 else "🟢"
            )
            description = f"⏱️ {total_time:.2f}s · ⚡ {ttft:.2f}s"
            if generated_tokens > 0:
                description += f" · 🚀 {tokens_per_second:.1f}t/s"
            description += (
                f" · {context_icon} {context_used / 1000:.1f}K/"
                f"{context_max / 1000:.1f}K ({context_percent:.0f}%)"
            )
            if __event_emitter__:
                await __event_emitter__({
                    "type": "status",
                    "data": {"description": description, "done": True, "hidden": False},
                })
            self.start_time = None
            self.first_token_time = None
            self.metrics_start = None
        return event
