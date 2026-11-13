"""Pruebas del filtro: memoria, errores de herramientas e imágenes.

    python -m unittest test_filtro test_acciones_fingidas
"""
import asyncio
import importlib.util
import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path

try:
    import requests  # noqa: F401
    import pydantic  # noqa: F401
except ImportError:  # sin Open WebUI: lo mínimo para importar filter.py
    stub = types.ModuleType("pydantic")
    stub.BaseModel = object
    stub.Field = lambda default=None, **_: default
    sys.modules.setdefault("pydantic", stub)
    req = types.ModuleType("requests")
    req.RequestException = Exception
    sys.modules.setdefault("requests", req)

spec = importlib.util.spec_from_file_location("sakura_filter_full", Path(__file__).with_name("filter.py"))
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)


def call(call_id, name, seconds=None):
    item = {"type": "function_call", "call_id": call_id, "name": name, "status": "completed"}
    if seconds is not None:
        item.update(started_at=1000.0, ended_at=1000.0 + seconds)
    return item


def output(call_id, text):
    return {"type": "function_call_output", "call_id": call_id, "status": "completed",
            "output": [{"type": "input_text", "text": text}]}


class HelperTests(unittest.TestCase):
    def test_memory_writer_answers(self):
        self.assertTrue(f.MEMORY_FAILURE.search("Hay varias coincidencias exactas; no se eliminó ningún recuerdo."))
        self.assertTrue(f.MEMORY_FAILURE.search("La actualización es ambigua o crearía un duplicado; no se hizo ningún cambio."))
        self.assertTrue(f.MEMORY_FAILURE.search("Sakura no guardó el recuerdo (HTTP 500)."))
        self.assertFalse(f.MEMORY_FAILURE.search("Recuerdo guardado en la memoria persistente de Sakura (ID 7)."))
        self.assertFalse(f.MEMORY_FAILURE.search("Recuerdo actualizado; la versión anterior quedó en el historial."))
        self.assertTrue(f.MEMORY_DUPLICATE.search("Ese recuerdo ya existía (ID 5); no se creó otro."))

    def test_tool_errors_inside_a_completed_call(self):
        self.assertTrue(f.tool_output_failed({"status": "completed"}, '{"error": "ComfyUI no responde"}'))
        self.assertFalse(f.tool_output_failed({"status": "completed"}, '{"status": "success", "images": []}'))
        self.assertTrue(f.tool_output_failed({"status": "failed"}, ""))

    def test_call_seconds(self):
        self.assertEqual(f.call_seconds({"duration": 13.5}), 13.5)
        self.assertEqual(f.call_seconds({"started_at": 10.0, "ended_at": 22.5}), 12.5)
        self.assertIsNone(f.call_seconds({}))


class OutletTests(unittest.TestCase):
    def make_filter(self, db=""):
        flt = f.Filter()
        if isinstance(flt.valves, f.Filter.Valves) and hasattr(flt.valves, "model_copy"):
            flt.valves = flt.valves.model_copy(update={"server_urls": "http://127.0.0.1:9", "history_db": db,
                                                       "request_timeout": 0.2})
        else:  # pydantic de prueba: los valores por defecto son atributos de clase
            flt.valves = types.SimpleNamespace(**{**{k: v for k, v in vars(f.Filter.Valves).items()
                                                     if not k.startswith("_")},
                                                  "server_urls": "http://127.0.0.1:9", "history_db": db,
                                                  "request_timeout": 0.2, "model": "", "tts_url": "",
                                                  "context_size": 81920,
                                                  "assistant": "Sakura"})
        return flt

    def run_message(self, flt, outputs, answer="Listo.", user="Hazme una imagen"):
        meta = {"message_id": "m1", "chat_id": "c1"}
        statuses = []

        async def emitter(event):
            statuses.append(event["data"]["description"])

        async def go():
            await flt.inlet({}, meta)
            await flt.request({}, meta)
            await flt.stream({"choices": [{"delta": {"content": "Hola"}, "finish_reason": "stop"}]}, meta)
            body = {"messages": [{"role": "user", "content": user},
                                 {"role": "assistant", "content": answer, "output": outputs}]}
            await flt.outlet(body, meta, emitter)

        asyncio.run(go())
        return statuses[-1]

    def test_image_time_and_duplicate_memory_in_the_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "r.db")
            flt = self.make_filter(db)
            line = self.run_message(flt, [
                call("a", "generate_image", 13.6), output("a", '{"status": "success", "images": []}'),
                call("b", "save_sakura_memory", 0.2), output("b", "Ese recuerdo ya existía (ID 5); no se creó otro."),
            ])
            self.assertIn("🎨 1 imagen en 13.6s", line)
            self.assertIn("💾 ya existía 1", line)
            self.assertNotIn("⚠️", line)
            conn = sqlite3.connect(db)
            try:
                row = conn.execute("select imagenes, imagen_s, herramientas_fallidas from mediciones").fetchone()
            finally:
                conn.close()
            self.assertEqual(row, (1, 13.6, 0))

    def test_failed_image_counts_as_failed_tool(self):
        flt = self.make_filter()
        line = self.run_message(flt, [call("a", "generate_image", 2.0), output("a", '{"error": "sin VRAM"}')])
        self.assertNotIn("🎨", line)

    def test_preparation_and_memory_only_tools(self):
        """⏳ separa la preparación de 🤔, y con solo herramientas de memoria el historial
        guarda igual su tiempo (antes quedaba vacío aunque la línea mostraba 🔧)."""
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "r.db")
            flt = self.make_filter(db)
            meta = {"message_id": "m2", "chat_id": "c1"}
            statuses = []

            async def emitter(event):
                statuses.append(event["data"]["description"])

            async def go():
                done = {"choices": [{"delta": {"content": "x"}, "finish_reason": "stop"}]}
                await flt.inlet({}, meta)
                await asyncio.sleep(0.3)  # preparación de Open WebUI
                await flt.request({}, meta)
                await flt.stream(done, meta)
                await asyncio.sleep(0.2)  # herramienta de memoria
                await flt.request({}, meta)
                await flt.stream(done, meta)
                body = {"messages": [{"role": "user", "content": "Hola"},
                                     {"role": "assistant", "content": "Listo.", "output": [
                                         call("a", "save_sakura_memory"), output("a", "Recuerdo guardado (ID 9).")]}]}
                await flt.outlet(body, meta, emitter)

            asyncio.run(go())
            line = statuses[-1]
            self.assertRegex(line, r"⏳ 0\.[3-9]s \+ 🤔 [\d.]+s \+ 🔧 1 en 0\.2s \+ ✍️ [\d.]+s = [\d.]+s")
            conn = sqlite3.connect(db)
            try:
                tools_s, prep_s = conn.execute("select herramientas_s, preparacion_s from mediciones").fetchone()
            finally:
                conn.close()
            self.assertAlmostEqual(tools_s, 0.2, delta=0.1)
            self.assertGreaterEqual(prep_s, 0.3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
