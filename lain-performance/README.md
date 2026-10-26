# Laín Performance

Variante de Sakura Performance para el `llama-server` que usa Laín. Muestra el tiempo total, el tiempo hasta el primer token (TTFT), la velocidad de generación y el uso del contexto en cada respuesta de Open WebUI.

## Valores detectados en Laín

| Ajuste | Valor |
| --- | --- |
| URL base del servidor | `http://127.0.0.1:50003` |
| Tamaño de contexto de respaldo | `50960` tokens |
| Métricas de llama.cpp | Requieren `--metrics` |

El lanzador local actual no incluye `--metrics`. Para que el filtro pueda leer velocidad y contexto, añade esa opción al comando de `llama-server` en `1 Llama Lain.bat`, antes de `--host`:

```bat
    --fit-target 4096,1024 ^
    --metrics ^
    --host 127.0.0.1 ^
    --port 50003
```

Guarda el archivo y reinicia Lain. El servidor debe escuchar en `127.0.0.1:50003`; comprueba que `http://127.0.0.1:50003/metrics` responde y que `/slots` muestra el slot activo. El filtro seguirá mostrando el tiempo total y el TTFT aunque el servidor no ofrezca métricas, pero velocidad y contexto aparecerán como no disponibles.

## Instalar el filtro

1. En Open WebUI, abre **Admin Panel → Functions** (en algunas versiones, **Workspace → Functions**).
2. Crea una función de tipo filtro y pega el contenido de [`filter.py`](filter.py).
3. Guarda y activa el filtro.
4. En los ajustes de la función, confirma estos valores:
   - `server_urls`: `http://127.0.0.1:50003`
   - `context_size`: `50960`
   - `request_timeout`: `2`
5. Habilita el filtro para el modelo de Laín.

Open WebUI y `llama-server` deben ejecutarse en el mismo equipo para que `127.0.0.1` apunte al servidor correcto. El endpoint de métricas queda limitado a la interfaz local porque Laín usa `--host 127.0.0.1`; no lo publiques en la red.

## Pruebas locales

Las pruebas usan respuestas simuladas y no necesitan iniciar Laín ni descargar el modelo:

```powershell
python -m unittest discover -s tests -v
```


