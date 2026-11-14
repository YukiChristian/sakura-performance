"""
title: Sakura Performance
description: Mide el mensaje completo (búsquedas, comandos, memoria e imágenes), la voz, avisa de acciones fingidas y guarda un historial sin texto.
version: 2.7.0
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from pathlib import Path
import asyncio
import json
import os
import re
import sqlite3
import time
import requests


# Herramientas de memoria de cada asistente: save_sakura_memory, update_lain_memory...
MEMORY_TOOL = re.compile(r"^(save|update|delete)_[a-z0-9]+_memory$")
# Memoria propia de Open WebUI (herramientas integradas): cuentan igual que save/update/delete.
NATIVE_MEMORY = {"add_memory": "save", "update_memory": "update", "replace_memory_content": "update",
                 "delete_memory": "delete"}
# Notas de Open WebUI: write_note crea una nota y replace_note_content la edita. Antes "Ya quedó
# guardada en la nota" se marcaba como acción fingida aunque write_note sí la guardó (2026-11-13).
NOTE_TOOLS = {"write_note": "save", "replace_note_content": "update"}
MEMORY_VERBS = {
    "save": ("guardó", "no guardó"),
    "update": ("actualizó", "no actualizó"),
    "delete": ("borró", "no borró"),
}
# Respuestas de los Memory Writer que significan que la operación no se hizo. Antes solo se
# miraba el principio del texto y "Hay varias coincidencias…; no se eliminó ningún recuerdo"
# o "La actualización es ambigua…; no se hizo ningún cambio" contaban como hechas.
MEMORY_FAILURE = re.compile(
    r"^(No se|No pude)|\bno\s+(se\s+)?(guardó|actualizó|eliminó|borró|hizo|confirmó)\b|no afirmes|ningún cambio",
    re.IGNORECASE,
)
# "Ese recuerdo ya existía (ID 5); no se creó otro": ni guardado nuevo ni fallo.
MEMORY_DUPLICATE = re.compile(r"\bya exist[ií]a\b", re.IGNORECASE)
# Herramientas de imagen de Open WebUI (ComfyUI, OpenAI, etc.).
IMAGE_TOOLS = {"generate_image", "edit_image"}
# Nombre del GGUF de cada perfil del router: se vuelve a preguntar pasado este tiempo
# (antes se guardaba para siempre y, al cambiar de modelo, el historial seguía con el viejo).
MODEL_NAME_SECONDS = 300
# Un mensaje abandonado (error, pestaña cerrada) se olvida a la hora.
STALE_SECONDS = 3600

# Acciones fingidas: el modelo dice que hizo algo sin llamar a la herramienta. Gemma 4 12B
# llegó a escribir "He guardado el recuerdo…" o "(Accediendo a la carpeta…)" sin ninguna
# llamada, y la memoria seguía igual (2026-11-11).
# Se pide guardar un recuerdo: "guárdalo como recuerdo", "anótalo en tu memoria",
# "memorízalo". "Guarda la imagen" o "recuerda que es anime" no cuentan: hace falta que
# hable de recuerdos o memoria.
SAVE_REQUEST = re.compile(
    r"\b(gu[aá]rda(lo|la|los|las|me)?|guardar|an[oó]ta(lo|la|los|las)?|anotar|ap[uú]nta(lo|la)?|"
    r"gr[aá]ba(lo|la|te)|registra(lo|la)?)\b[^.?!\n]{0,60}\b(recuerdos?|memoria)\b|"
    r"\bmemor[ií]za(lo|la|los|las)?\b|\bno\s+(lo\s+|la\s+)?olvides\b",
    re.IGNORECASE,
)
# El modelo afirma que guardó un recuerdo. Verbos que en el chat casi solo significan eso:
SAVE_CLAIM = re.compile(
    r"\b(he|ya|lo|la|los|las|te\s+lo)\s+(he\s+)?(guardado|grabado|anotado|apuntado|memorizado)\b|"
    r"\b(guard[eé]|anot[eé]|grab[eé]|apunt[eé]|memoric[eé])\b|"
    r"\b(qued[oó]|quedaron|est[aá]n?)\s+(bien\s+)?(guardad[oa]s?|grabad[oa]s?|anotad[oa]s?)\b|"
    r"\b(he\s+)?tomado\s+nota\b|"
    r"\b(en|a)\s+mi\s+memoria\s+persistente\b",
    re.IGNORECASE,
)
# Verbos que también se usan para archivos o código: cuentan solo cerca de "recuerdo" o "memoria".
MEMORY_EDIT_CLAIM = re.compile(
    r"\b(he\s+)?(actualizado|corregido|borrado|eliminado|registrado|integrado|actualic[eé]|correg[ií]|"
    r"borr[eé]|elimin[eé]|registr[eé]|integr[eé])\b[^.\n]{0,60}\b(recuerdos?|memoria)\b|"
    r"\b(recuerdos?|memoria)\b[^.\n]{0,40}\b(actualizad[oa]s?|corregid[oa]s?|borrad[oa]s?|eliminad[oa]s?)\b",
    re.IGNORECASE,
)
# El modelo narra una acción con herramientas que no llamó: "(Accediendo a la carpeta…)",
# "*Procediendo a leer el archivo...*", o escribe la llamada como texto.
ACTION_PLACEHOLDER = re.compile(
    r"[(*_]\s*(Accediendo|Procesando|Procediendo|Leyendo|Analizando|Consultando|Revisando|Buscando|"
    r"Explorando|Ejecutando|Abriendo|Descargando)\b[^)\n]{0,120}?(\.\.\.|…)",
    re.IGNORECASE,
)
# La llamada escrita como texto en lugar de hacerla: save_sakura_memory(content="…").
FAKE_MEMORY_CALL = re.compile(r"\b(save|update|delete)_[a-z0-9]+_memory\s*\(", re.IGNORECASE)

SCHEMA = """
CREATE TABLE IF NOT EXISTS mediciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT UNIQUE,
    fecha TEXT,
    asistente TEXT,
    modelo TEXT,
    modelo_completo TEXT,
    total_s REAL,
    ttft_s REAL,
    tps REAL,
    prompt_tps REAL,
    contexto_usado INTEGER,
    contexto_max INTEGER,
    cache_pct REAL,
    vueltas INTEGER,
    herramientas INTEGER,
    herramientas_fallidas INTEGER,
    herramientas_s REAL,
    herramientas_nombres TEXT,
    respuesta_final_s REAL,
    recuerdos_leidos INTEGER,
    recuperacion_ms REAL,
    memoria_guardados INTEGER,
    memoria_actualizados INTEGER,
    memoria_borrados INTEGER,
    memoria_fallos INTEGER,
    voz_frases INTEGER,
    voz_fallos INTEGER,
    voz_audio_s REAL,
    voz_sintesis_s REAL,
    voz_rtf REAL,
    voz_primera_s REAL,
    linea TEXT
);
CREATE INDEX IF NOT EXISTS mediciones_fecha ON mediciones (fecha);
"""
# Columnas añadidas después de la versión 2.0.0 (se crean si faltan).
EXTRA_COLUMNS = {
    "decidir_s": "REAL",
    "vueltas_detalle": "TEXT",
    "acciones_fingidas": "TEXT",
    "imagenes": "INTEGER",
    "imagen_s": "REAL",
    "preparacion_s": "REAL",
    "notas": "INTEGER",
}


def tool_output_failed(output: dict, text: str) -> bool:
    """Una herramienta puede terminar "completed" y devolver un error: generate_image
    devuelve {"error": "..."} cuando ComfyUI falla."""
    if output.get("status") in ("failed", "incomplete"):
        return True
    stripped = text.strip()
    if stripped.startswith("{"):
        try:
            data = json.loads(stripped)
            return isinstance(data, dict) and bool(data.get("error"))
        except ValueError:
            return False
    return stripped.lower().startswith(("error:", "error ", "traceback"))


def call_seconds(call: dict):
    """Duración de una llamada a herramienta que Open WebUI guarda en el mensaje."""
    duration = call.get("duration")
    if isinstance(duration, (int, float)):
        return float(duration)
    start, end = call.get("started_at"), call.get("ended_at")
    if isinstance(start, (int, float)) and isinstance(end, (int, float)) and end >= start:
        return float(end - start)
    return None


def message_text(message) -> str:
    """Texto de un mensaje de Open WebUI (cadena o lista de partes)."""
    content = message.get("content") if isinstance(message, dict) else ""
    if isinstance(content, list):
        return " ".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
    return content if isinstance(content, str) else ""


def strip_quotes(text: str) -> str:
    """Quita bloques de código y citas para no tomar ejemplos como afirmaciones."""
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"`[^`\n]*`", " ", text)
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith(">"))


def find_faked_actions(user_text: str, answer: str, memory_writes: int, memory_failures: int, other_tools: int) -> list:
    """Avisos (sin texto del chat) cuando la respuesta afirma algo que no ocurrió en este mensaje."""
    raw = answer or ""
    answer = strip_quotes(raw)
    warnings = []
    if memory_writes == 0:
        # La llamada escrita como texto se busca también dentro de `código` (suele salir así),
        # pero no en bloques ``` que pueden ser un ejemplo pedido.
        no_blocks = re.sub(r"```.*?```", " ", raw, flags=re.DOTALL)
        if SAVE_CLAIM.search(answer) or MEMORY_EDIT_CLAIM.search(answer) or FAKE_MEMORY_CALL.search(no_blocks):
            warnings.append("memoria")
        elif SAVE_REQUEST.search(strip_quotes(user_text or "")) and not memory_failures:
            warnings.append("memoria_pedida")
    if other_tools == 0 and ACTION_PLACEHOLDER.search(answer):
        warnings.append("herramienta")
    return warnings


FAKED_LABELS = {
    "memoria": "⚠️ dijo que guardó, pero no usó la herramienta de memoria: no se guardó nada",
    "memoria_pedida": "⚠️ pediste guardar y no usó la herramienta de memoria: no se guardó nada",
    "herramienta": "⚠️ describió una acción (leer, buscar, abrir…) sin usar ninguna herramienta",
}


class Filter:
    """Medidor de rendimiento para Sakura, Lain y Yoko (llama-server en modo router)."""

    class Valves(BaseModel):
        priority: int = Field(default=0, description="Prioridad de ejecución")
        assistant: str = Field(
            default="Sakura", description="Nombre de la asistente para el historial (Sakura, Lain o Yoko)"
        )
        server_urls: str = Field(
            default="http://127.0.0.1:50000",
            description="URLs base de llama-server (o del router) con /metrics y /slots, separadas por comas. No el proxy.",
        )
        model: str = Field(
            default="qwen-9b",
            description="Perfil del router (qwen-9b Sakura, qwen-9b-yoko Yoko, qwen-27b Lain). Vacío si no es router.",
        )
        context_size: int = Field(
            default=81920, description="Contexto de respaldo si el servidor no informa n_ctx (--ctx-size)"
        )
        request_timeout: float = Field(default=2.0, description="Espera máxima por consulta, en segundos")
        tts_url: str = Field(
            default="",
            description="URL del servidor de voz (http://127.0.0.1:5052) para medir el TTS. Vacío: sin voz.",
        )
        tts_wait_seconds: int = Field(
            default=300, description="Cuánto tiempo esperar a que pulses la bocina (o a la voz automática) tras el texto"
        )
        history_db: str = Field(
            default="",
            description="Ruta de una base SQLite para el historial (solo números, nunca texto del chat). Vacío: sin historial.",
        )

    def __init__(self):
        self.valves = self.Valves()
        self.runs: dict = {}
        self.full_model_names: dict = {}
        # Hora del último mensaje de cada chat: la espera de voz de un mensaje se detiene
        # cuando empieza otro en el mismo chat, para no atribuirle la voz del nuevo.
        # (Antes era una sola hora para todos los chats: un mensaje en otro chat la cortaba.)
        self.newest_by_chat: dict = {}

    # ------------------------------------------------------------------ util

    def get_server_urls(self):
        urls = []
        for value in self.valves.server_urls.split(","):
            url = value.strip().rstrip("/")
            if url.endswith("/v1"):
                url = url[:-3]
            if url and url not in urls:
                urls.append(url)
        return urls

    def router_params(self) -> dict:
        """En modo router /metrics y /slots necesitan ?model=. autoload=false evita
        que el filtro cargue un modelo (y descargue el de otra asistente)."""
        model = (self.valves.model or "").strip()
        return {"model": model, "autoload": "false"} if model else {}

    @staticmethod
    def message_id(metadata) -> str:
        if isinstance(metadata, dict):
            return str(metadata.get("message_id") or metadata.get("chat_id") or "sin-id")
        return "sin-id"

    def get_run(self, metadata, create=False):
        key = self.message_id(metadata)
        run = self.runs.get(key)
        if run is None and create:
            now = time.time()
            for old in [k for k, v in self.runs.items() if now - v["wall_start"] > STALE_SECONDS]:
                self.runs.pop(old, None)
            run = {
                "start": time.perf_counter(),
                "wall_start": now,
                "first_token": None,
                "rounds": [],
                "metrics_start": {},
                "stream_tool_names": [],
            }
            self.runs[key] = run
        return run

    @staticmethod
    def open_round(run, now):
        rounds = run["rounds"]
        if not rounds or rounds[-1].get("end") is not None:
            rounds.append({"start": now, "end": None, "core": None})
        return rounds[-1]

    # ---------------------------------------------------------- llama-server

    def get_llama_metrics(self, base_url: str) -> dict:
        try:
            response = requests.get(
                f"{base_url}/metrics", params=self.router_params(), timeout=self.valves.request_timeout
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

    async def collect_metrics(self, urls) -> dict:
        results = await asyncio.gather(*(asyncio.to_thread(self.get_llama_metrics, url) for url in urls))
        return dict(zip(urls, results))

    def get_context_usage(self, base_url: str):
        """Lee el slot reciente; acepta nombres de campos de varias versiones."""
        try:
            response = requests.get(
                f"{base_url}/slots", params=self.router_params(), timeout=self.valves.request_timeout
            )
            response.raise_for_status()
            slots = response.json()
            if isinstance(slots, dict):
                slots = slots.get("slots", [])
            candidates = [slot for slot in slots if isinstance(slot, dict)] if isinstance(slots, list) else []
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
            if used is None and slot.get("n_prompt_tokens") is not None:
                decoded = slot.get("next_token", 0)
                if isinstance(decoded, list) and decoded:
                    decoded = decoded[0].get("n_decoded", 0)
                elif isinstance(decoded, dict):
                    decoded = decoded.get("n_decoded", 0)
                else:
                    decoded = 0
                used = int(slot["n_prompt_tokens"]) + int(decoded or 0)
            return (
                int(used) if used is not None else None,
                int(maximum) if maximum else None,
            )
        except (requests.RequestException, ValueError, TypeError, KeyError):
            return None, None

    def get_full_model_name(self, base_url: str, alias: str) -> str:
        """Nombre del GGUF que carga el perfil del router (p. ej. Qwen3.5-9B.Q6_K)."""
        if not alias:
            return ""
        cached = self.full_model_names.get(alias)
        if cached and time.time() - cached[1] < MODEL_NAME_SECONDS:
            return cached[0]
        name = ""
        try:
            response = requests.get(f"{base_url}/v1/models", timeout=self.valves.request_timeout)
            response.raise_for_status()
            for item in response.json().get("data", []):
                if item.get("id") != alias:
                    continue
                args = (item.get("status") or {}).get("args") or item.get("args") or []
                path = item.get("path") or item.get("model_path") or ""
                if not path and isinstance(args, list):
                    for flag, value in zip(args, args[1:]):
                        if flag in ("-m", "--model"):
                            path = value
                            break
                if path:
                    name = os.path.basename(str(path))
                break
        except (requests.RequestException, ValueError, TypeError, AttributeError):
            pass
        if not name:
            try:
                response = requests.get(
                    f"{base_url}/props", params=self.router_params(), timeout=self.valves.request_timeout
                )
                response.raise_for_status()
                name = os.path.basename(str(response.json().get("model_path") or ""))
            except (requests.RequestException, ValueError, TypeError, AttributeError):
                pass
        name = re.sub(r"\.gguf$", "", name, flags=re.IGNORECASE)
        if name:
            self.full_model_names[alias] = (name, time.time())
        return name or (cached[0] if cached else alias)

    @staticmethod
    def counter_delta(before: dict, after: dict, name: str):
        if name not in before or name not in after:
            return None
        delta = after[name] - before[name]
        return delta if delta >= 0 else None

    # ------------------------------------------------------------- historial

    def save_history(self, key: str, row: dict) -> None:
        path = (self.valves.history_db or "").strip()
        if not path:
            return
        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(path, timeout=10)
            try:
                conn.executescript(SCHEMA)
                existing = {r[1] for r in conn.execute("PRAGMA table_info(mediciones)")}
                for column, kind in EXTRA_COLUMNS.items():
                    if column not in existing:
                        conn.execute(f"ALTER TABLE mediciones ADD COLUMN {column} {kind}")
                        existing.add(column)
                row = {k: v for k, v in row.items() if k in existing}
                columns = ", ".join(row)
                marks = ", ".join("?" for _ in row)
                updates = ", ".join(f"{c} = excluded.{c}" for c in row if c != "message_id")
                with conn:
                    conn.execute(
                        f"INSERT INTO mediciones (message_id, {columns}) VALUES (?, {marks}) "
                        f"ON CONFLICT(message_id) DO UPDATE SET {updates}",
                        (key, *row.values()),
                    )
            finally:
                conn.close()
        except (sqlite3.Error, OSError):
            pass

    # ------------------------------------------------------------------ hooks

    async def inlet(self, body: dict, __metadata__: Optional[dict] = None) -> dict:
        run = self.get_run(__metadata__, create=True)
        chat = str((__metadata__ or {}).get("chat_id") or "") if isinstance(__metadata__, dict) else ""
        run["chat_id"] = chat
        self.newest_by_chat[chat] = max(self.newest_by_chat.get(chat, 0.0), run["wall_start"])
        run["metrics_start"] = await self.collect_metrics(self.get_server_urls())
        return body

    async def request(self, body: dict, __metadata__: Optional[dict] = None) -> dict:
        """Open WebUI lo llama antes de cada vuelta al modelo (la primera y tras cada herramienta)."""
        run = self.get_run(__metadata__, create=True)
        self.open_round(run, time.perf_counter())
        return body

    async def stream(self, event: dict, __metadata__: Optional[dict] = None, __event_emitter__=None) -> dict:
        run = self.get_run(__metadata__)
        if run is None:
            return event
        now = time.perf_counter()
        current = self.open_round(run, run["rounds"][-1]["end"] if run["rounds"] else run["start"])
        if isinstance(event.get("sakura_metrics"), dict):
            current["core"] = event["sakura_metrics"]
        for choice in event.get("choices", []) or []:
            delta = choice.get("delta", {}) or {}
            if run["first_token"] is None and (
                delta.get("content")
                or delta.get("tool_calls")
                or delta.get("reasoning_content")
                or delta.get("function_call")
                or delta.get("refusal")
            ):
                run["first_token"] = now
            for call in delta.get("tool_calls") or []:
                name = (call.get("function") or {}).get("name")
                if name:
                    run["stream_tool_names"].append(name)
            if choice.get("finish_reason") is not None:
                current["end"] = now
                current["finish_reason"] = choice.get("finish_reason")
        return event

    async def outlet(
        self, body: dict, __metadata__: Optional[dict] = None, __event_emitter__=None
    ) -> dict:
        key = self.message_id(__metadata__)
        run = self.runs.pop(key, None)
        if run is None:
            return body
        now = time.perf_counter()
        rounds = [r for r in run["rounds"] if r.get("end") is not None] or [
            {"start": run["start"], "end": now, "core": None}
        ]
        end = rounds[-1]["end"]
        total_time = max(0.0, end - run["start"])
        ttft = run["first_token"] - run["start"] if run["first_token"] is not None else None

        # Tiempos de llama-server que el Core reenvía en cada vuelta.
        timings = [r["core"]["timings"] for r in rounds if (r.get("core") or {}).get("timings")]
        predicted_n = sum(t.get("predicted_n", 0) for t in timings)
        predicted_ms = sum(t.get("predicted_ms", 0) for t in timings)
        prompt_n = sum(t.get("prompt_n", 0) for t in timings)
        prompt_ms = sum(t.get("prompt_ms", 0) for t in timings)
        cache_n = sum(t.get("cache_n", 0) for t in timings)
        tps = predicted_n / (predicted_ms / 1000) if predicted_ms > 0 else None
        prompt_tps = prompt_n / (prompt_ms / 1000) if prompt_ms > 0 and prompt_n > 0 else None
        cache_pct = cache_n / (cache_n + prompt_n) * 100 if (cache_n + prompt_n) > 0 else None

        urls = self.get_server_urls()
        metrics_end = await self.collect_metrics(urls)
        selected_url = None
        best = (0, 0)
        for url, after in metrics_end.items():
            before = run["metrics_start"].get(url, {})
            tokens = self.counter_delta(before, after, "llamacpp:tokens_predicted_total") or 0
            prompt = self.counter_delta(before, after, "llamacpp:prompt_tokens_total") or 0
            if (tokens, prompt) > best:
                best, selected_url = (tokens, prompt), url
            if tps is None and tokens:
                seconds = self.counter_delta(before, after, "llamacpp:tokens_predicted_seconds_total")
                if seconds:
                    tps = tokens / seconds
        selected_url = selected_url or (urls[0] if urls else None)

        # Contexto: tokens de la última vuelta; el máximo lo da el slot.
        context_used = context_max = None
        if selected_url:
            context_used, context_max = await asyncio.to_thread(self.get_context_usage, selected_url)
        if timings:
            last = timings[-1]
            context_used = int(last.get("cache_n", 0) + last.get("prompt_n", 0) + last.get("predicted_n", 0))
        context_max = context_max or self.valves.context_size

        # Herramientas y memoria, desde el resultado que Open WebUI guardó en el mensaje.
        calls, outputs = {}, {}
        messages = body.get("messages") or []
        assistant = next((m for m in reversed(messages) if m.get("role") == "assistant"), {})
        for item in assistant.get("output") or []:
            if item.get("type") == "function_call":
                calls[item.get("call_id")] = item
            elif item.get("type") == "function_call_output":
                outputs[item.get("call_id")] = item
        if not calls:
            calls = {f"stream-{i}": {"name": n} for i, n in enumerate(run["stream_tool_names"])}

        tool_names, tool_failures = [], 0
        memory_ok = {"save": 0, "update": 0, "delete": 0}
        memory_failed = {"save": 0, "update": 0, "delete": 0}
        memory_duplicates = 0
        images, image_seconds = 0, 0.0
        notes_ok = {"save": 0, "update": 0}
        notes_failed = 0
        for call_id, call in calls.items():
            name = call.get("name") or ""
            output = outputs.get(call_id) or {}
            text = " ".join(
                part.get("text", "") for part in output.get("output") or [] if isinstance(part, dict)
            ).strip()
            failed = call.get("status") == "failed" or tool_output_failed(output, text)
            match = MEMORY_TOOL.match(name)
            verb = NATIVE_MEMORY.get(name) or (match.group(1) if match else None)
            if verb:
                if not failed and MEMORY_DUPLICATE.search(text):
                    memory_duplicates += 1
                elif failed or MEMORY_FAILURE.search(text):
                    memory_failed[verb] += 1
                else:
                    memory_ok[verb] += 1
            else:
                tool_names.append(name)
                tool_failures += int(bool(failed))
                if name in NOTE_TOOLS:
                    if failed:
                        notes_failed += 1
                    else:
                        notes_ok[NOTE_TOOLS[name]] += 1
                if name in IMAGE_TOOLS and not failed:
                    images += 1
                    image_seconds += call_seconds(call) or 0.0

        # Tiempo de herramientas = huecos entre vueltas del modelo.
        tools_seconds = sum(
            max(0.0, rounds[i + 1]["start"] - rounds[i]["end"]) for i in range(len(rounds) - 1)
        )
        final_seconds = rounds[-1]["end"] - rounds[-1]["start"] if len(rounds) > 1 else None
        # Preparación de Open WebUI antes de la primera vuelta (filtros, plantillas, RAG).
        # Antes se sumaba a 🤔 y "pensar" parecía más lento de lo que era.
        prep_seconds = max(0.0, rounds[0]["start"] - run["start"])
        core_metrics = [r["core"] for r in rounds if r.get("core")]
        memories_read = core_metrics[0].get("memories") if core_metrics else None
        retrieval_ms = sum(c.get("retrieval_ms") or 0 for c in core_metrics) if core_metrics else None
        alias = (core_metrics[0].get("model") if core_metrics else None) or self.valves.model
        full_model = (
            await asyncio.to_thread(self.get_full_model_name, selected_url, alias) if selected_url else alias
        )

        # ---- línea de estado (formato fijo + extras solo cuando ocurren)
        parts = [f"⏱️ {total_time:.2f}s"]
        parts.append(f"⚡ {ttft:.2f}s" if ttft is not None else "⚡ TTFT n/d")
        parts.append(f"🚀 {tps:.1f}t/s" if tps is not None else "🚀 tok/s n/d")
        if context_used is not None and context_max:
            percent = min(100.0, context_used / context_max * 100.0)
            icon = "🔴" if percent >= 95 else "🟠" if percent >= 85 else "🟡" if percent >= 70 else "🟢"
            parts.append(f"{icon} {context_used / 1000:.1f}K/{context_max / 1000:.1f}K ({percent:.0f}%)")
        else:
            parts.append("⚪ contexto n/d")
        # Con herramientas: ⏳ preparación + 🤔 pensar qué hacer + 🔧 herramientas + ✍️ respuesta
        # final = total. 🤔 se calcula como resto de los valores redondeados para que la suma cuadre.
        decide_seconds = None
        if final_seconds is not None:
            total_r, tools_r, final_r = round(total_time, 1), round(tools_seconds, 1), round(final_seconds, 1)
            prep_r = round(prep_seconds, 1)
            decide_seconds = max(0.0, total_r - prep_r - tools_r - final_r)
            all_calls = len(calls)
            text = f"🔧 {all_calls} en {tools_r:.1f}s"
            failures = tool_failures + sum(memory_failed.values())
            if failures:
                text += f" ({failures} {'falló' if failures == 1 else 'fallaron'})"
            prep_text = f"⏳ {prep_r:.1f}s + " if prep_r >= 0.1 else ""
            parts.append(f"{prep_text}🤔 {decide_seconds:.1f}s + {text} + ✍️ {final_r:.1f}s = {total_r:.1f}s")
        memory_parts = []
        if memories_read:
            memory_parts.append(f"leyó {memories_read}")
        for verb, (ok_word, fail_word) in MEMORY_VERBS.items():
            if memory_ok[verb]:
                memory_parts.append(f"{ok_word} {memory_ok[verb]}")
            if memory_failed[verb]:
                memory_parts.append(f"❌ {fail_word}")
        if memory_duplicates:
            memory_parts.append(f"ya existía {memory_duplicates}")
        if memory_parts:
            parts.append("💾 " + ", ".join(memory_parts))
        if images:
            word = "imagen" if images == 1 else "imágenes"
            parts.append(f"🎨 {images} {word} en {image_seconds:.1f}s" if image_seconds else f"🎨 {images} {word}")
        note_parts = []
        for kind, (one, many) in {"save": ("guardada", "guardadas"), "update": ("actualizada", "actualizadas")}.items():
            n = notes_ok[kind]
            if n:
                note_parts.append(f"nota {one}" if n == 1 else f"{n} notas {many}")
        if notes_failed:
            note_parts.append("❌ nota no guardada")
        if note_parts:
            parts.append("📝 " + ", ".join(note_parts))
        # Acciones fingidas: se compara lo que dice la respuesta con las herramientas que se llamaron.
        user_message = next((m for m in reversed(messages) if m.get("role") == "user"), {})
        faked = find_faked_actions(
            message_text(user_message),
            message_text(assistant),
            # una nota guardada también es "guardar": "Ya quedó guardada en la nota" es cierto
            sum(memory_ok.values()) + memory_duplicates + sum(notes_ok.values()),
            sum(memory_failed.values()),
            len(tool_names),
        )
        parts.extend(FAKED_LABELS[w] for w in faked)
        line = " · ".join(parts)

        if __event_emitter__:
            await __event_emitter__(
                {"type": "status", "data": {"description": line, "done": True, "hidden": False}}
            )

        # Desglose de cada vuelta: recuerdos (Core), leer prompt y generar (llama-server),
        # y "otros" = lo que sobra (Open WebUI, red local, preparación del Core).
        round_details = []
        for index, item in enumerate(rounds):
            core = item.get("core") or {}
            timing = core.get("timings") or {}
            duration_ms = (item["end"] - item["start"]) * 1000
            retrieval = core.get("retrieval_ms") or 0
            prompt = timing.get("prompt_ms") or 0
            generate = timing.get("predicted_ms") or 0
            round_details.append({
                # Solo la primera: preparación de Open WebUI antes de llamar al modelo.
                "antes_ms": round((item["start"] - run["start"]) * 1000, 1) if index == 0 else None,
                "duracion_ms": round(duration_ms, 1),
                "recuerdos_ms": round(retrieval, 1),
                "prompt_ms": round(prompt, 1),
                "prompt_tokens": timing.get("prompt_n"),
                "cache_tokens": timing.get("cache_n"),
                "generar_ms": round(generate, 1),
                "generados": timing.get("predicted_n"),
                "otros_ms": round(max(0.0, duration_ms - retrieval - prompt - generate), 1),
                "herramientas_despues_ms": round((rounds[index + 1]["start"] - item["end"]) * 1000, 1)
                if index + 1 < len(rounds)
                else None,
                "fin": item.get("finish_reason"),
            })

        row = {
            "fecha": datetime.now().isoformat(timespec="seconds"),
            "asistente": self.valves.assistant,
            "modelo": alias,
            "modelo_completo": full_model,
            "total_s": round(total_time, 3),
            "ttft_s": round(ttft, 3) if ttft is not None else None,
            "tps": round(tps, 2) if tps is not None else None,
            "prompt_tps": round(prompt_tps, 1) if prompt_tps is not None else None,
            "contexto_usado": context_used,
            "contexto_max": context_max,
            "cache_pct": round(cache_pct, 1) if cache_pct is not None else None,
            "vueltas": len(rounds),
            "herramientas": len(tool_names),
            "herramientas_fallidas": tool_failures,
            "herramientas_s": round(tools_seconds, 3) if final_seconds is not None else None,
            "preparacion_s": round(prep_seconds, 3),
            "herramientas_nombres": json.dumps(
                {n: tool_names.count(n) for n in sorted(set(tool_names))}, ensure_ascii=False
            )
            if tool_names
            else None,
            "respuesta_final_s": round(final_seconds, 3) if final_seconds is not None else None,
            "decidir_s": round(decide_seconds, 3) if decide_seconds is not None else None,
            "vueltas_detalle": json.dumps(round_details, ensure_ascii=False),
            "recuerdos_leidos": memories_read,
            "recuperacion_ms": round(retrieval_ms, 1) if retrieval_ms is not None else None,
            "memoria_guardados": memory_ok["save"],
            "memoria_actualizados": memory_ok["update"],
            "memoria_borrados": memory_ok["delete"],
            "memoria_fallos": sum(memory_failed.values()),
            "acciones_fingidas": ",".join(faked) or None,
            "imagenes": images,
            "notas": sum(notes_ok.values()),
            "imagen_s": round(image_seconds, 3) if images and image_seconds else None,
            "linea": line,
        }
        await asyncio.to_thread(self.save_history, key, row)

        if (self.valves.tts_url or "").strip() and __event_emitter__:
            asyncio.create_task(
                self.watch_voice(key, run["wall_start"], line, __event_emitter__, run.get("chat_id", ""))
            )
        return body

    # ------------------------------------------------------------------- voz

    def get_tts_samples(self, since: float) -> list:
        try:
            response = requests.get(
                f"{self.valves.tts_url.strip().rstrip('/')}/metrics",
                params={"since": since},
                timeout=self.valves.request_timeout,
            )
            response.raise_for_status()
            return response.json().get("samples", []) or []
        except (requests.RequestException, ValueError, AttributeError):
            return []

    async def watch_voice(self, key: str, wall_start: float, line: str, emitter, chat: str = "") -> None:
        """La voz se genera mientras y después del texto: espera a que callen las frases
        y añade 🔊 a la misma línea. Espera hasta tts_wait_seconds a que pulses la bocina; si nadie la pulsa, no añade nada."""
        try:
            deadline = time.time() + max(10, self.valves.tts_wait_seconds)
            samples, last_change = [], time.time()
            while time.time() < deadline:
                await asyncio.sleep(1.5)
                if not samples and self.newest_by_chat.get(chat, 0.0) > wall_start:
                    return
                current = await asyncio.to_thread(self.get_tts_samples, wall_start)
                if len(current) != len(samples):
                    samples, last_change = current, time.time()
                quiet = time.time() - last_change
                if samples and quiet >= 6:
                    break
            if not samples:
                return
            ok = [s for s in samples if not s.get("failed")]
            failures = len(samples) - len(ok)
            audio = sum(s.get("audio_seconds", 0) for s in ok)
            synthesis = sum(s.get("synthesis_seconds", 0) for s in ok)
            rtf = synthesis / audio if audio > 0 else None
            first = min((s["finished_at"] for s in ok), default=None)
            first_seconds = first - wall_start if first else None
            voice = f"🔊 RTF {rtf:.2f}" if rtf is not None else "🔊"
            if rtf is not None and rtf > 1:
                voice += " ⚠️"
            if failures:
                voice += f" ❌ {failures} sin voz"
            new_line = f"{line} · {voice}"
            await emitter({"type": "status", "data": {"description": new_line, "done": True, "hidden": False}})
            await asyncio.to_thread(
                self.save_history,
                key,
                {
                    "voz_frases": len(ok),
                    "voz_fallos": failures,
                    "voz_audio_s": round(audio, 3),
                    "voz_sintesis_s": round(synthesis, 3),
                    "voz_rtf": round(rtf, 3) if rtf is not None else None,
                    "voz_primera_s": round(first_seconds, 3) if first_seconds is not None else None,
                    "linea": new_line,
                },
            )
        except Exception:
            pass
