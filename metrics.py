import requests
from flask import Flask, jsonify

app = Flask(__name__)
LLAMA_METRICS = "http://127.0.0.1:50002/metrics"


def get_metrics():
    response = requests.get(LLAMA_METRICS, timeout=5)
    response.raise_for_status()
    metrics = {}
    for line in response.text.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        parts = line.rsplit(None, 1)
        if len(parts) != 2:
            continue
        name, value = parts
        try:
            metrics[name] = float(value)
        except ValueError:
            continue
    return metrics


@app.route("/health")
def health():
    try:
        metrics = get_metrics()
        return jsonify({"status": "ok", "metric_count": len(metrics), "endpoint": LLAMA_METRICS})
    except Exception as exc:
        app.logger.exception("Error consultando métricas")
        return jsonify({"status": "error", "error": str(exc)}), 502


@app.route("/snapshot")
def snapshot():
    try:
        metrics = get_metrics()
        return jsonify({
            "ready": True,
            "prompt_tokens": metrics.get("llamacpp:prompt_tokens_total", 0),
            "generated_tokens": metrics.get("llamacpp:tokens_predicted_total", 0),
            "prompt_seconds": metrics.get("llamacpp:prompt_seconds_total", 0),
            "generation_seconds": metrics.get("llamacpp:tokens_predicted_seconds_total", 0),
            "prompt_tps": metrics.get("llamacpp:prompt_tokens_seconds", 0),
            "generation_tps": metrics.get("llamacpp:predicted_tokens_seconds", 0),
            "requests_processing": metrics.get("llamacpp:requests_processing", 0),
        })
    except Exception as exc:
        app.logger.exception("Error generando snapshot")
        return jsonify({"ready": False, "error": str(exc)}), 502


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5050, debug=False, threaded=True)
