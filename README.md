# Sakura Performance

Filtro de Open WebUI y helper local para consultar métricas de generación de un servidor compatible con `llama.cpp`.

## Archivos

- `filter.py`: filtro de Open WebUI que muestra tiempo total, tiempo hasta el primer token, velocidad de generación y uso del contexto.
- `metrics.py`: servicio Flask local con los endpoints `/health` y `/snapshot`.
- `requirements.txt`: dependencias del helper.

## Requisitos

- Open WebUI instalado directamente en Windows con Python.
- Un servidor `llama.cpp` que exponga `/metrics` y `/slots` en el puerto `50002`.
- Python disponible desde PowerShell o Símbolo del sistema.

## Configurar el filtro

1. En Open WebUI, abre **Admin Panel → Functions** (en algunas versiones aparece como **Workspace → Functions**).
2. Crea una función/filtro nuevo y pega el contenido de `filter.py`, o importa el archivo si tu versión ofrece esa opción.
3. Guarda y activa el filtro.
4. En los ajustes del filtro, confirma `server_url` como `http://127.0.0.1:50002`. Si el servidor usa otro puerto, cambia este valor.
5. Habilítalo para el modelo Gemma 4 que quieras medir.

El filtro consulta `/metrics` para estimar los tokens generados y `/slots` para calcular el uso del contexto. Si esos endpoints no están disponibles, seguirá mostrando los tiempos de la respuesta y usará los valores de contexto de reserva.

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
