# Laín Performance

Filtro independiente de Open WebUI para el servidor de Laín. Muestra el tiempo total, el tiempo hasta el primer token (TTFT), la velocidad de generación y el uso del contexto. Sakura Performance permanece aparte y sin cambios.

## Configuración del servidor de Laín

| Ajuste | Valor |
| --- | --- |
| Ejecutable | `D:\Sakura\Modelos\llama-Vulkan-CUDA-ROCm\build-vulkan-cuda\bin\Release\llama-server.exe` |
| Modelo | `Qwen3.6-35B-A3B-UD-IQ4_XS.gguf` |
| Proyector multimodal | `mmproj-Qwen3.6-35B-A3B-F16.gguf` |
| Dispositivos | `CUDA0,Vulkan1` |
| División | `layer`, tensor split `1,2` |
| Capas en GPU | `99` |
| Contexto | `55000` tokens |
| Dirección y puerto | `0.0.0.0:50003` |
| Métricas de llama.cpp | Activadas con `--metrics` |

En PowerShell, usa una tilde invertida (`) al final de cada línea que continúa el comando. El servidor escucha en `0.0.0.0`; para las conexiones desde Open WebUI en el mismo equipo, usa `127.0.0.1`.

```powershell
$Build = 'D:\Sakura\Modelos\llama-Vulkan-CUDA-ROCm\build-vulkan-cuda\bin\Release'
$Model = 'D:\Sakura\Modelos\llama-Vulkan-CUDA-ROCm\models\Qwen3.6-35B-A3B-UD-IQ4_XS.gguf'
$MMProj = 'D:\Sakura\Modelos\llama-Vulkan-CUDA-ROCm\models\mmproj-Qwen3.6-35B-A3B-F16.gguf'

& "$Build\llama-server.exe" `
    --model $Model `
    --mmproj $MMProj `
    --device CUDA0,Vulkan1 `
    --split-mode layer `
    --tensor-split 1,2 `
    --ctx-size 55000 `
    --n-gpu-layers 99 `
    --host 0.0.0.0 `
    --port 50003 `
    --metrics
```

Sakura utiliza el puerto `50002` y Laín `50003`, por lo que ambos servidores pueden funcionar a la vez. Asegúrate de iniciar el ejecutable correspondiente al modelo que vas a usar. Al escuchar en todas las interfaces (`0.0.0.0`), limita el acceso con el Firewall de Windows si no necesitas conexiones desde otros equipos.

Con Laín encendido, comprueba que `http://127.0.0.1:50003/metrics` y `http://127.0.0.1:50003/slots` respondan. Sin `--metrics`, el filtro seguirá mostrando los tiempos, pero velocidad y contadores de tokens no estarán disponibles.

## Configurar Open WebUI

1. En **Admin Panel → Functions**, crea o conserva el filtro independiente **Lain Performance** usando el contenido de [`filter.py`](filter.py). No reemplaces Sakura Performance.
2. Activa **Lain Performance**.
3. En sus válvulas configura:
   - `server_urls`: `http://127.0.0.1:50003`
   - `context_size`: `55000`
   - `request_timeout`: `2`
4. En **Workspace → Models → Laín → Filters**, selecciona **Lain Performance**. Deja Sakura Performance asociada solamente al modelo Sakura.

Si Open WebUI se ejecuta en otra computadora, sustituye `127.0.0.1` por la IP del equipo donde corre Laín.

## Pruebas locales

Las pruebas usan respuestas simuladas; no inician Laín ni descargan el modelo:

```powershell
python -m unittest discover -s tests -v
```
