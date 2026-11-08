"""Resumen del historial de rendimiento de Sakura, Lain y Yoko.

Lee la base SQLite que escribe el filtro (válvula history_db; solo números, nunca
texto del chat) e imprime promedios por asistente y modelo.

Ejemplos:
    python ver_rendimiento.py                 # últimos 7 días
    python ver_rendimiento.py --dias 30
    python ver_rendimiento.py --asistente Lain
    python ver_rendimiento.py --ultimos 20    # los últimos 20 mensajes, uno por línea
    python ver_rendimiento.py --detalle       # desglose por vuelta del último mensaje
    python ver_rendimiento.py --detalle 3     # ... de los últimos 3 mensajes
"""
import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path


DEFAULT_DB = Path("rendimiento.db")


def fmt(value, pattern="{:.2f}", empty="—"):
    return empty if value is None else pattern.format(value)


def seconds(ms):
    return "—" if ms is None else f"{ms / 1000:.1f}s"


def print_detail(row):
    """Árbol de un mensaje: cada vuelta del modelo y las herramientas entre vueltas."""
    print(f"{row['fecha'].replace('T', ' ')} · {row['asistente']} · {row['modelo_completo']}")
    print(f"  {row['linea']}")
    try:
        rounds = json.loads((row["vueltas_detalle"] if "vueltas_detalle" in row.keys() else None) or "[]")
    except (TypeError, ValueError):
        rounds = []
    if not rounds:
        print("  (sin desglose por vuelta: mensaje anterior a la versión 2.1.0)\n")
        return
    print(f"  ⏱️ {row['total_s']:.1f}s total")
    if rounds[0].get("antes_ms"):
        print(f"  ├─ Preparación de Open WebUI       {seconds(rounds[0]['antes_ms'])}")
    for index, item in enumerate(rounds, 1):
        last = index == len(rounds)
        name = "respuesta final ✍️" if last and len(rounds) > 1 else "piensa qué hacer 🤔" if not last else "respuesta"
        branch, pipe = ("└─", "   ") if last else ("├─", "│  ")
        print(f"  {branch} Vuelta {index}: {name:<22} {seconds(item.get('duracion_ms'))}")
        cache = item.get("cache_tokens")
        prompt_tokens = item.get("prompt_tokens")
        tokens = f" ({prompt_tokens} nuevos, {cache} en caché)" if prompt_tokens is not None else ""
        print(f"  {pipe} ├─ 💾 búsqueda de recuerdos      {seconds(item.get('recuerdos_ms'))}")
        print(f"  {pipe} ├─ 📥 leer el prompt              {seconds(item.get('prompt_ms'))}{tokens}")
        generated = f" ({item['generados']} tokens)" if item.get("generados") is not None else ""
        print(f"  {pipe} ├─ ✏️ escribir                     {seconds(item.get('generar_ms'))}{generated}")
        print(f"  {pipe} └─ ⏳ Open WebUI, proxy y red      {seconds(item.get('otros_ms'))}")
        if item.get("herramientas_despues_ms") is not None:
            print(f"  ├─ 🔧 herramientas                  {seconds(item['herramientas_despues_ms'])}")
    print()


def main():
    parser = argparse.ArgumentParser(description="Resumen del historial de rendimiento.")
    parser.add_argument("--dias", type=int, default=7, help="Días hacia atrás (por defecto 7)")
    parser.add_argument("--asistente", help="Sakura, Lain o Yoko")
    parser.add_argument("--ultimos", type=int, help="Muestra los últimos N mensajes, uno por línea")
    parser.add_argument("--detalle", type=int, nargs="?", const=1, help="Desglose por vuelta de los últimos N mensajes")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args()

    if not args.db.is_file():
        raise SystemExit(f"Todavía no hay historial en {args.db}. Se crea con el primer mensaje.")
    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    since = (datetime.now() - timedelta(days=args.dias)).isoformat(timespec="seconds")
    where, params = ["fecha >= ?"], [since]
    if args.asistente:
        where.append("lower(asistente) = lower(?)")
        params.append(args.asistente)
    clause = " and ".join(where)

    if args.detalle:
        rows = conn.execute(
            f"select * from mediciones where {clause} order by fecha desc, id desc limit ?",
            (*params, args.detalle),
        ).fetchall()
        for row in reversed(rows):
            print_detail(row)
        return

    if args.ultimos:
        rows = conn.execute(
            f"select fecha, asistente, modelo_completo, linea from mediciones where {clause}"
            " order by fecha desc limit ?",
            (*params, args.ultimos),
        ).fetchall()
        for row in reversed(rows):
            print(f"{row['fecha'].replace('T', ' ')}  {row['asistente']:<6} {row['modelo_completo']:<24} {row['linea']}")
        return

    print(f"Historial desde {since[:10]} ({args.dias} días)\n")
    groups = conn.execute(
        f"""select asistente, modelo_completo, count(*) mensajes,
                   avg(total_s) total, avg(ttft_s) ttft, avg(tps) tps, avg(prompt_tps) prompt_tps,
                   avg(contexto_usado * 100.0 / contexto_max) contexto, avg(cache_pct) cache,
                   sum(case when cache_pct < 50 then 1 else 0 end) cache_baja
            from mediciones where {clause}
            group by asistente, modelo_completo order by asistente, mensajes desc""",
        params,
    ).fetchall()
    if not groups:
        print("Sin mensajes en ese periodo.")
        return
    print("Asistente  Modelo                    Mensajes  Total   1er token  t/s    Prompt t/s  Contexto  Caché")
    for g in groups:
        print(
            f"{g['asistente']:<10} {g['modelo_completo'] or '—':<25} {g['mensajes']:>8}  "
            f"{fmt(g['total'], '{:.1f} s'):>6}  {fmt(g['ttft'], '{:.2f} s'):>9}  {fmt(g['tps'], '{:.0f}'):>4}  "
            f"{fmt(g['prompt_tps'], '{:.0f}'):>10}  {fmt(g['contexto'], '{:.0f}%'):>8}  {fmt(g['cache'], '{:.0f}%'):>5}"
        )
        if g["cache_baja"]:
            print(f"{'':10} ↳ {g['cache_baja']} mensajes con caché baja (<50%): tardan más en empezar.")

    tools = conn.execute(
        f"""select count(*) mensajes, sum(herramientas) herramientas, sum(herramientas_fallidas) fallidas,
                   avg(herramientas_s) herramientas_s, avg(respuesta_final_s) final_s
            from mediciones where {clause} and herramientas > 0""",
        params,
    ).fetchone()
    print("\nHerramientas (web, comandos, scripts)")
    if tools["mensajes"]:
        print(
            f"  {tools['mensajes']} mensajes con herramientas · {tools['herramientas']} llamadas · "
            f"fallaron {tools['fallidas']} ({tools['fallidas'] * 100 / tools['herramientas']:.0f}%)"
        )
        print(
            f"  Promedio: {fmt(tools['herramientas_s'], '{:.1f} s')} en herramientas, "
            f"{fmt(tools['final_s'], '{:.1f} s')} en la respuesta final"
        )
    else:
        print("  Ninguna en este periodo.")

    memory = conn.execute(
        f"""select avg(recuerdos_leidos) leidos, avg(recuperacion_ms) recuperacion,
                   sum(memoria_guardados) guardados, sum(memoria_actualizados) actualizados,
                   sum(memoria_borrados) borrados, sum(memoria_fallos) fallos
            from mediciones where {clause}""",
        params,
    ).fetchone()
    print("\nMemoria")
    print(
        f"  Recuerdos leídos por mensaje: {fmt(memory['leidos'], '{:.1f}')} · "
        f"búsqueda de recuerdos: {fmt(memory['recuperacion'], '{:.0f} ms')}"
    )
    print(
        f"  {memory['guardados'] or 0} guardados · {memory['actualizados'] or 0} actualizaciones · "
        f"{memory['borrados'] or 0} borrados · fallos: {memory['fallos'] or 0}"
    )

    voice = conn.execute(
        f"""select count(*) mensajes, sum(voz_frases) frases, sum(voz_sintesis_s) / sum(voz_audio_s) rtf,
                   sum(case when voz_rtf > 1 then 1 else 0 end) lentas, avg(voz_primera_s) primera,
                   sum(voz_fallos) fallos
            from mediciones where {clause} and voz_frases > 0""",
        params,
    ).fetchone()
    print("\nVoz")
    if voice["mensajes"]:
        print(
            f"  {voice['mensajes']} mensajes con voz · {voice['frases']} frases · RTF promedio {fmt(voice['rtf'])}"
            f" · primera frase lista en {fmt(voice['primera'], '{:.1f} s')}"
        )
        if voice["lentas"]:
            print(f"  ⚠️ {voice['lentas']} mensajes con RTF > 1: la voz iba más lenta que el texto.")
        if voice["fallos"]:
            print(f"  ❌ {voice['fallos']} frases sin voz.")
    else:
        print("  Sin voz en este periodo.")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
