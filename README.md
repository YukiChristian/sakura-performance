# Sakura Performance

Filtro de Open WebUI y helper local para consultar métricas de generación de un servidor compatible con `llama.cpp`. **Sakura es el nombre de esta configuración; puedes usarla con otros modelos de IA.**

Aunque el proyecto se llama Sakura Performance, el filtro puede usarse con cualquier modelo de IA servido por una instancia compatible con `llama.cpp`. En cada respuesta muestra cuánto tarda el modelo, cuándo empieza a responder, a qué velocidad genera y cuánto contexto ocupa. Así puedes detectar demoras y ver si el contexto se acerca a su límite.

Ejemplo en Open WebUI:

> ⏱️ 6.41s · ⚡ 5.86s · 🚀 49.9t/s · 🟢 2.4K/40.2K (6%)

## Archivos

- `filter.py`: filtro de Open WebUI que muestra tiempo total, tiempo hasta el primer token, velocidad de generación y uso del contexto.
- `metrics.py`: servicio Flask local con los endpoints `/health` y `/snapshot`.
- `start_sakura.ps1`: inicia el helper de métricas y `llama-server` con los parámetros de ejemplo.
- `requirements.txt`: dependencias del helper.

## Requisitos

- Open WebUI instalado directamente en Windows con Python.
- Un servidor compatible con la API de `llama.cpp` que exponga `/metrics` y `/slots` (el ejemplo usa el puerto `50002`).
- Python disponible desde PowerShell o Símbolo del sistema.

## Arrancar el servidor y las métricas

El lanzador inicia `metrics.py` y luego ejecuta `llama-server` con los parámetros del proyecto. Usa un archivo GGUF que ya exista en el disco; **el script usa `--model` y no descarga Gemma ni ningún otro modelo**.

Primero instala las dependencias del helper:

```powershell
python -m pip install -r requirements.txt
```

Después, desde la carpeta del proyecto, pasa la ruta al GGUF local:

```powershell
.\start_sakura.ps1 -ModelPath "C:\ruta\a\tu-modelo.gguf"
```

Por defecto, el script busca `llama-server.exe` en `C:\Llama-Sakura\build-cuda\bin\Release\llama-server.exe`; si lo tienes en otro lugar, cambia `$ServerExe` al inicio de `start_sakura.ps1`. El helper escucha en `127.0.0.1:5050` y el servidor en el puerto `50002`. Al detener `llama-server`, el lanzador cierra el proceso de métricas.

El servidor usa `--host 0.0.0.0`, por lo que puede aceptar conexiones desde otros equipos de la red. Para limitarlo a esta computadora, cambia ese valor a `127.0.0.1` en `start_sakura.ps1`.

## Configurar el filtro

1. En Open WebUI, abre **Admin Panel → Functions** (en algunas versiones aparece como **Workspace → Functions**).
2. Crea una función/filtro nuevo y pega el contenido de `filter.py`, o importa el archivo si tu versión ofrece esa opción.
3. Guarda y activa el filtro.
4. En los ajustes del filtro, configura `server_urls` con la URL base de cada servidor compatible con `llama.cpp`, separadas por comas. Por ejemplo: `http://127.0.0.1:50002` o, si Open WebUI tiene conexiones a los puertos `10001` y `50002`, `http://127.0.0.1:10001,http://127.0.0.1:50002`. Escribe la URL base sin `/v1`, `/metrics` ni `/slots`.
5. Habilítalo para los modelos servidos por esos endpoints. El filtro compara sus contadores antes y después de cada respuesta para elegir el servidor que registró actividad.

El filtro consulta `/metrics` para estimar los tokens generados y `/slots` para calcular el uso del contexto. Si el slot no expone los campos de contexto esperados, usa el contador de tokens de prompt como estimación y el tamaño de contexto configurado como referencia. Si el servidor no expone métricas válidas, seguirá mostrando los tiempos de la respuesta y marcará velocidad/contexto como no disponibles.

El filtro puede usarse con distintos modelos de IA siempre que se sirvan mediante un backend compatible con `llama.cpp` y ofrezcan estas rutas y métricas. En otros tipos de backend, las rutas y los nombres de las métricas pueden ser diferentes y habría que adaptar el código.

## Cómo leer el indicador

![Infografía del indicador de Sakura Performance: tiempo total, TTFT, velocidad de generación y uso del contexto](indicador-sakura.svg)

Ejemplo:

```text
⏱️ 12.40s · ⚡ 0.85s · 🚀 42.3t/s · 🟢 8.2K/40.2K (20%)
```

| Indicador | Qué mide | Cómo interpretarlo |
| --- | --- | --- |
| `12.40s` — tiempo total | Tiempo desde que Open WebUI inicia la solicitud hasta que recibe el evento final. | Incluye la espera para procesar el prompt, generar la respuesta y el tiempo de comunicación entre componentes. |
| `0.85s` — TTFT | Tiempo hasta que el filtro detecta el primer fragmento de contenido en el flujo. | Un valor bajo significa que la respuesta comienza pronto. No es necesariamente igual al tiempo de prefill informado internamente por el servidor. |
| `42.3t/s` — velocidad | Tokens generados divididos entre los segundos de generación informados por las métricas de llama.cpp. | Es la velocidad durante la generación, no el tiempo total dividido entre tokens. Puede mostrarse como `0t/s` o no aparecer si el servidor no ofrece métricas válidas. |
| `8.2K/40.2K (20%)` — contexto | Tokens de prompt reportados por el primer slot, el límite de contexto configurado y el porcentaje usado. `K` representa miles de tokens. | El color pasa a amarillo desde 70%, naranja desde 85% y rojo desde 95%; por debajo de 70% aparece verde. |

**Nota:** las métricas de tokens de llama.cpp son contadores del servidor. Si se atienden varias solicitudes al mismo tiempo, la diferencia de contadores puede incluir actividad concurrente y la velocidad puede no corresponder exclusivamente a una sola conversación. El uso del contexto también depende de que `/slots` exponga el slot activo.

## Configurar el helper de métricas (opcional)

Abre PowerShell en esta carpeta y ejecuta:

```powershell
python -m pip install -r requirements.txt
python metrics.py
```

El helper queda escuchando solo en el equipo local, en `127.0.0.1:5050`. Puedes comprobarlo en el navegador:

- `http://127.0.0.1:5050/health`: estado de conexión y cantidad de métricas.
- `http://127.0.0.1:5050/snapshot`: resumen JSON de tokens, tiempos y velocidad.

El helper lee `http://127.0.0.1:50002/metrics`. Si el servidor usa otro puerto, edita `LLAMA_METRICS` en `metrics.py`.

## Seguridad y repositorio

No incluyas claves API, contraseñas, tokens, archivos de modelos, registros, audio generado ni rutas privadas de la máquina. Estos archivos no contienen credenciales. Mantén cualquier configuración local fuera del repositorio.

