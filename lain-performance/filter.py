from pydantic import BaseModel, Field
from typing import Optional
import time
import requests


class Filter:
    """Muestra tiempos, velocidad y contexto de servidores compatibles con llama.cpp."""

    class Valves(BaseModel):
        priority: int = Field(default=0, description="Prioridad de ejecución")
        server_urls: str = Field(
            default="http://127.0.0.1:50003",
            description=(
                "URLs base de los servidores llama.cpp que exponen /metrics y /slots, separadas por comas. "
                "En Laín, apunta al llama-server local (http://127.0.0.1:50003)."
            ),
        )
        context_size: int = Field(default=55000, description="Tamaño de contexto de respaldo de Laín")
        request_timeout: float = Field(default=2.0, description="Tiempo máximo de espera en segundos")

    def __init__(self):
        self.valves = self.Valves()
        self.start_time = None
        self.first_token_time = None
        self.metrics_start = None

    def get_server_urls(self):
        urls = []
        for value in self.valves.server_urls.split(","):
            url = value.strip().rstrip("/")
            if url.endswith("/v1"):
                url = url[:-3]
            if url and url not in urls:
                urls.append(url)
        return urls

    def get_llama_metrics(self, base_url: str) -> dict:
        try:
            response = requests.get(
                f"{base_url}/metrics", timeout=self.valves.request_timeout
            )
            response.raise_for_status()
            metrics = {}
            for line in response.text.splitlines():
                line = line.strip()
                if not line or line.startswith("#") or " " not in line:
                    continue
                name, value = line.rsplit(None, 1)
                try:
                    metrics[name] = float(value)
                except ValueError:
                    continue
            return metrics
        except requests.RequestException:
            return {}

    def get_context_usage(self, base_url: str):
        """Lee el slot reciente; acepta nombres de campos de varias versiones."""
        try:
            response = requests.get(
                f"{base_url}/slots", timeout=self.valves.request_timeout
            )
            response.raise_for_status()
            slots = response.json()
            if isinstance(slots, dict):
                slots = slots.get("slots", [])
            if not isinstance(slots, list) or not slots:
                return None, None

            candidates = [slot for slot in slots if isinstance(slot, dict)]
            if not candidates:
                return None, None
            candidates.sort(
                key=lambda slot: (
                    bool(slot.get("is_processing")),
                    int(slot.get("n_prompt_tokens", 0) or 0),
                    int(slot.get("n_past", 0) or 0),
                ),
                reverse=True,
            )
            slot = candidates[0]
            maximum = slot.get("n_ctx")
            used = slot.get("n_past")

            if used is None:
                prompt_tokens = slot.get("n_prompt_tokens")
                if prompt_tokens is not None:
                    decoded = slot.get("next_token", 0)
                    if isinstance(decoded, list) and decoded:
                        decoded = decoded[0].get("n_decoded", 0)
                    elif isinstance(decoded, dict):
                        decoded = decoded.get("n_decoded", 0)
                    else:
                        decoded = 0
                    used = int(prompt_tokens) + int(decoded or 0)

            if used is not None and maximum is not None and int(maximum) > 0:
                return max(0, int(used)), int(maximum)
        except (requests.RequestException, ValueError, TypeError, KeyError):
            pass
        return None, None

    @staticmethod
    def counter_delta(before: dict, after: dict, name: str):
        if name not in before or name not in after:
            return None
        delta = after[name] - before[name]
        return delta if delta >= 0 else None

    async def inlet(self, body: dict, __metadata__: Optional[dict] = None) -> dict:
        self.start_time = time.perf_counter()
        self.first_token_time = None
        self.metrics_start = {
            url: self.get_llama_metrics(url) for url in self.get_server_urls()
        }
        return body

    async def stream(self, event: dict, __event_emitter__=None) -> dict:
        now = time.perf_counter()
        for choice in event.get("choices", []):
            delta = choice.get("delta", {}) or {}
            generated_output = (
                bool(delta.get("content"))
                or bool(delta.get("tool_calls"))
                or bool(delta.get("function_call"))
                or bool(delta.get("refusal"))
            )
            if generated_output and self.first_token_time is None:
                self.first_token_time = now

        finished = event.get("done") is True or any(
            choice.get("finish_reason") is not None
            for choice in event.get("choices", [])
        )
        if not finished or self.start_time is None:
            return event

        total_time = max(0.0, now - self.start_time)
        ttft = (
            max(0.0, self.first_token_time - self.start_time)
            if self.first_token_time is not None
            else None
        )

        # Consulta todos los servidores configurados y elige el que registró
        # actividad en esta respuesta, por si Open WebUI usa varios puertos.
        metrics_end = {
            url: self.get_llama_metrics(url) for url in self.get_server_urls()
        }
        activity = []
        for url, end in metrics_end.items():
            start = (self.metrics_start or {}).get(url, {})
            token_delta = self.counter_delta(
                start, end, "llamacpp:tokens_predicted_total"
            )
            seconds_delta = self.counter_delta(
                start, end, "llamacpp:tokens_predicted_seconds_total"
            )
            prompt_delta = self.counter_delta(
                start, end, "llamacpp:prompt_tokens_total"
            )
            tps = (
                token_delta / seconds_delta
                if token_delta and seconds_delta and seconds_delta > 0
                else None
            )
            if (token_delta or 0) > 0 or (prompt_delta or 0) > 0:
                activity.append((token_delta or 0, prompt_delta or 0, url, tps))

        selected = max(activity, default=(0, 0, None, None))
        selected_url = selected[2]
        tokens_per_second = selected[3]

        # Si la versión del servidor no conserva campos del slot, usa el
        # contador de prompt como alternativa para estimar el contexto.
        context_used = context_max = None
        urls_to_check = ([selected_url] if selected_url else []) + [
            url for url in self.get_server_urls() if url != selected_url
        ]
        for url in urls_to_check:
            context_used, context_max = self.get_context_usage(url)
            if context_used is not None:
                break

        if context_used is None and selected_url:
            start = (self.metrics_start or {}).get(selected_url, {})
            end = metrics_end.get(selected_url, {})
            prompt_delta = self.counter_delta(
                start, end, "llamacpp:prompt_tokens_total"
            )
            cached_delta = self.counter_delta(
                start, end, "llamacpp:prompt_tokens_cached_total"
            ) or 0
            if prompt_delta is not None:
                context_used = int(prompt_delta + cached_delta)
                context_max = self.valves.context_size

        if context_used is not None and context_max:
            context_percent = min(100.0, context_used / context_max * 100.0)
            icon = (
                "🔴" if context_percent >= 95 else
                "🟠" if context_percent >= 85 else
                "🟡" if context_percent >= 70 else "🟢"
            )
            context_text = (
                f"{icon} {context_used / 1000:.1f}K/"
                f"{context_max / 1000:.1f}K ({context_percent:.0f}%)"
            )
        else:
            context_text = "⚪ contexto n/d"

        parts = [f"⏱️ {total_time:.2f}s"]
        parts.append(f"⚡ {ttft:.2f}s" if ttft is not None else "⚡ TTFT n/d")
        parts.append(
            f"🚀 {tokens_per_second:.1f}t/s"
            if tokens_per_second is not None
            else "🚀 tok/s n/d"
        )
        parts.append(context_text)

        if __event_emitter__:
            await __event_emitter__(
                {
                    "type": "status",
                    "data": {
                        "description": " · ".join(parts),
                        "done": True,
                        "hidden": False,
                    },
                }
            )

        self.start_time = None
        self.first_token_time = None
        self.metrics_start = None
        return event

