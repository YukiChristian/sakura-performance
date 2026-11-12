"""Pruebas de la detección de acciones fingidas (python -m unittest test_acciones_fingidas)."""
import importlib.util
import sys
import types
import unittest
from pathlib import Path

# filter.py importa requests y pydantic (Open WebUI los trae); para estas pruebas no hacen falta.
for name in ("requests", "pydantic"):
    if name not in sys.modules:
        try:
            __import__(name)
        except ImportError:
            stub = types.ModuleType(name)
            stub.BaseModel = object
            stub.Field = lambda default=None, **_: default
            stub.RequestException = Exception
            sys.modules[name] = stub

spec = importlib.util.spec_from_file_location("sakura_filter", Path(__file__).with_name("filter.py"))
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)


def check(user, answer, writes=0, failures=0, tools=0):
    return f.find_faked_actions(user, answer, writes, failures, tools)


class FakedActionTests(unittest.TestCase):
    def test_says_it_saved_without_the_tool(self):
        self.assertEqual(check("Guarda esta parte en tus recuerdos",
                               "¡Claro! Ya tengo estos datos bien grabados. He guardado el recuerdo de nuestra charla."),
                         ["memoria"])
        self.assertEqual(check("Guárdalo como recuerdo",
                               "Entendido. He tomado nota y los he integrado en mi memoria persistente."),
                         ["memoria"])

    def test_saved_for_real_is_not_flagged(self):
        self.assertEqual(check("Guarda esto", "Listo, lo guardé en mi memoria.", writes=1), [])

    def test_asked_to_save_and_answer_ignores_it(self):
        self.assertEqual(check("Anótalo en tu memoria, por favor", "Claro, ¿quieres algo más?"), ["memoria_pedida"])
        self.assertEqual(check("Memorízalo", "¡Va!"), ["memoria_pedida"])

    def test_instructions_that_are_not_save_requests(self):
        self.assertEqual(check("Hazla anime y recuerda que es pelirroja", "¡Listo, aquí tienes tu imagen!", tools=1), [])
        self.assertEqual(check("Guarda la imagen en Descargas", "Hecho.", tools=1), [])

    def test_failed_write_is_already_reported(self):
        self.assertEqual(check("Guarda esto", "No pude confirmar el guardado.", failures=1), [])

    def test_memory_call_written_as_text(self):
        self.assertEqual(check("Recuerda que me gusta el té", 'Voy a usar `save_sakura_memory(content="té")`.'),
                         ["memoria"])

    def test_narrated_tool_use_without_a_call(self):
        self.assertEqual(check("Pasa a la parte 3",
                               "*(Accediendo y analizando la carpeta `integracion`...)*\n\nAquí tienes el resumen…"),
                         ["herramienta"])

    def test_narration_with_a_real_call_is_fine(self):
        self.assertEqual(check("Lee el README", "*(Procediendo a leer el archivo...)*\n\nEl README dice…", tools=1), [])

    def test_recalling_old_memories_is_not_a_claim(self):
        self.assertEqual(check("¿Qué recuerdas de mí?",
                               "Basado en los recuerdos que tengo guardados, sé que te gusta Toy Story."), [])

    def test_editing_files_is_not_a_memory_claim(self):
        self.assertEqual(check("Arregla el README", "Actualicé el archivo README y borré la línea repetida.", tools=2), [])

    def test_examples_in_code_blocks_are_ignored(self):
        self.assertEqual(check("¿Cómo se usa la herramienta?",
                               "Así:\n```python\nsave_sakura_memory(content='hola')\n```\nLa llama el modelo."), [])

    def test_storage_words_about_other_things(self):
        self.assertEqual(check("¿Dónde quedó el archivo?", "El archivo quedó en la carpeta Descargas."), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
