# Laín Performance

Filtro independiente de Open WebUI para el servidor de Laín. Muestra el tiempo total, el tiempo hasta el primer token (TTFT), la velocidad de generación y el uso de contexto. Sakura Performance permanece aparte y sin cambios.

## Configuración del servidor de Laín

La configuración actual de Laín usa:

| Ajuste | Valor |
| --- | --- |
| Ejecutable | `D:\Sakura\Modelos\llama-Vulkan-CUDA-ROCm\build-vulkan-cuda\bin\Release\llama-server.exe` |
| Modelo | `Qwen3.6-35B-A3B-UD-IQ4_XS.gguf` |
| Proyector multimodal | `mmproj-Qwen3.6-35B-A3B-F16.gguf` |
| Dispositivos | `CUDA0,Vulkan1` |
| División | `layer`, tensor split `1,2` |
| Contexto | `55000` tokens |
| GPU layers | `99` |
| Escucha | `0.0.0.0:50002` |
| Métricas llama.cpp | Activadas con `--metrics` |

En PowerShell, las continuaciones de línea se escriben con una tilde invertida al final. Usa rutas de cliente con `127.0.0.1`; `0.0.0.0` solo es la dirección de escucha del servidor.

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
    --port 50002 `
    --metrics
```

**Importante:** Sakura también usa el puerto `50002`. Solo uno de los dos servidores puede ocuparlo a la vez. Detén Sakura antes de iniciar Laín, o cambia uno de los puertos y actualiza la conexión de su modelo y su filtro. La dirección `0.0.0.0` permite escuchar en interfaces de red; limita el acceso mediante el Firewall de Windows si no necesitas conectarte desde otros equipos.

Comprueba que, con Laín encendido, `http://127.0.0.1:50002/metrics` y `http://127.0.0.1:50002/slots` respondan. Sin `--metrics`, los tiempos seguirán disponibles, pero velocidad y contadores de tokens no.

## Configurar Open WebUI

1. En **Admin Panel → Functions**, importa el contenido de [`filter.py`](filter.py) como un filtro independiente llamado **Lain Performance**. No reemplaces Sakura Performance.
2. Activa **Lain Performance**.
3. En sus válvulas configura:
   - `server_urls`: `http://127.0.0.1:50002`
   - `context_size`: `55000`
   - `request_timeout`: `2`
4. En **Workspace → Models → Laín → Filters**, selecciona **Lain Performance**. La función de Sakura debe seguir asignada solo al modelo Sakura.

El puerto `50002` es el endpoint de Laín mientras Sakura está detenida. Si Open WebUI corre en otra computadora, sustituye `127.0.0.1` por la IP del equipo donde corre Laín.

## Pruebas locales

Las pruebas usan respuestas simuladas; no inician el servidor ni descargan el modelo:

```powershell
python -m unittest discover -s tests -v
```
