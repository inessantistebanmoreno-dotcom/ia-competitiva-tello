#!/usr/bin/env python3
# =============================================================================
# main.py — Orquestador del Agente de Inteligencia Competitiva
# Tello · Etiquetado · v1.0
#
# Uso:
#   python main.py                        → ciclo completo (todos los competidores)
#   python main.py --competidor noel      → solo Noel
#   python main.py --competidor elpozo    → solo El Pozo
#   python main.py --resumen-diario       → enviar resumen diario por email
#   python main.py --sin-alertas          → scraping sin enviar emails
# =============================================================================

import argparse
import logging
import sys
import time
from datetime import datetime

from config import COMPETIDORES
from database.db import get_connection, upsert_producto
from scrapers import SCRAPERS
from alertas import procesar_y_enviar_alertas, enviar_resumen_diario

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("agente_etiquetado.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("main")


# ---------------------------------------------------------------------------
# Ciclo de scraping para un competidor
# ---------------------------------------------------------------------------

def ejecutar_competidor(competidor_id: str, enviar_alertas: bool = True) -> dict:
    """Ejecuta el scraping de un competidor y guarda los resultados en BD."""
    cfg = COMPETIDORES.get(competidor_id)
    if not cfg:
        logger.error(f"Competidor desconocido: {competidor_id}")
        return {}

    logger.info(f"{'='*60}")
    logger.info(f"Iniciando scraping: {cfg['nombre']}")
    logger.info(f"{'='*60}")

    clase_scraper = SCRAPERS.get(competidor_id)
    if not clase_scraper:
        logger.error(f"No hay scraper implementado para: {competidor_id}")
        return {}

    inicio = time.time()
    scraper = clase_scraper()

    # Registrar inicio en log_ejecuciones
    log_id = _registrar_inicio(competidor_id)

    productos_ok = 0
    cambios_totales = []
    errores = 0

    try:
        productos = scraper.scrape()

        for datos in productos:
            try:
                cambios = upsert_producto(datos)
                productos_ok += 1
                if cambios:
                    cambios_totales.extend(cambios)
                    logger.info(
                        f"  [CAMBIO] {datos['nombre_producto']}: "
                        f"{[c['campo_modificado'] for c in cambios]}"
                    )
            except Exception as e:
                errores += 1
                logger.warning(f"  Error guardando {datos.get('nombre_producto', '?')}: {e}")

        duracion = round(time.time() - inicio, 1)
        _registrar_fin(log_id, productos_ok, len(cambios_totales), errores, "completado")
        logger.info(
            f"[{cfg['nombre']}] Completado en {duracion}s — "
            f"{productos_ok} productos, {len(cambios_totales)} cambios, {errores} errores"
        )

        # Enviar alertas inmediatas (crítico + alto)
        if enviar_alertas and cambios_totales:
            n = procesar_y_enviar_alertas()
            if n:
                logger.info(f"  → {n} alertas enviadas por email")

    except Exception as e:
        _registrar_fin(log_id, productos_ok, len(cambios_totales), errores + 1, "error", str(e))
        logger.error(f"Error general en {cfg['nombre']}: {e}", exc_info=True)

    return {
        "competidor": competidor_id,
        "productos":  productos_ok,
        "cambios":    len(cambios_totales),
        "errores":    errores,
    }


# ---------------------------------------------------------------------------
# Log de ejecuciones
# ---------------------------------------------------------------------------

def _registrar_inicio(competidor: str) -> int:
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO log_ejecuciones (competidor) VALUES (%s) RETURNING id",
                    (competidor,)
                )
                log_id = cur.fetchone()["id"]
                conn.commit()
                return log_id
    except Exception:
        return -1


def _registrar_fin(log_id: int, productos: int, cambios: int, errores: int, estado: str, error_txt: str = None):
    if log_id < 0:
        return
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE log_ejecuciones SET
                        fin = NOW(), productos_revisados = %s,
                        cambios_detectados = %s, errores = %s,
                        estado = %s, detalle_error = %s
                    WHERE id = %s
                """, (productos, cambios, errores, estado, error_txt, log_id))
                conn.commit()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Modo test: scraping de un único producto por URL
# ---------------------------------------------------------------------------

def _testear_url(competidor_id: str, url: str):
    """Extrae y muestra en consola los datos de un único producto sin guardar en BD."""
    import json
    from playwright.sync_api import sync_playwright

    clase_scraper = SCRAPERS.get(competidor_id)
    if not clase_scraper:
        logger.error(f"No hay scraper para: {competidor_id}")
        return

    scraper = clase_scraper()
    logger.info(f"Testeando {url} con scraper [{competidor_id}]…")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="es-ES",
        )
        page = context.new_page()
        page.set_default_timeout(30000)
        try:
            datos = scraper.extraer_producto(page, url)
            if datos:
                print("\n" + "="*60)
                print(f"PRODUCTO: {datos.get('nombre_producto')}")
                print("="*60)
                for k, v in datos.items():
                    # Mostrar también los False y None para diagnóstico
                    print(f"  {k:30} {v}")
                print("="*60 + "\n")
            else:
                logger.warning("No se pudo extraer el producto (extraer_producto devolvió None)")
        except Exception as e:
            logger.error(f"Error: {e}", exc_info=True)
        finally:
            browser.close()


# ---------------------------------------------------------------------------
# Punto de entrada
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Agente de Inteligencia Competitiva · Tello")
    parser.add_argument("--competidor", choices=list(COMPETIDORES.keys()),
                        help="Ejecutar solo para este competidor")
    parser.add_argument("--url",
                        help="Testear un único producto por URL (requiere --competidor)")
    parser.add_argument("--resumen-diario", action="store_true",
                        help="Enviar resumen diario de novedades por email")
    parser.add_argument("--sin-alertas", action="store_true",
                        help="Ejecutar scraping sin enviar alertas por email")
    args = parser.parse_args()

    if args.resumen_diario:
        logger.info("Enviando resumen diario...")
        enviar_resumen_diario()
        return

    # Modo test: scraping de un solo producto y volcado en consola
    if args.url:
        if not args.competidor:
            logger.error("--url requiere también --competidor")
            sys.exit(1)
        _testear_url(args.competidor, args.url)
        return

    competidores = [args.competidor] if args.competidor else list(COMPETIDORES.keys())
    enviar = not args.sin_alertas

    logger.info(f"Ciclo de extracción iniciado — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    logger.info(f"Competidores: {', '.join(competidores)}")

    resumen_global = []
    for comp_id in competidores:
        resultado = ejecutar_competidor(comp_id, enviar_alertas=enviar)
        resumen_global.append(resultado)

    # Resumen final en log
    logger.info("")
    logger.info("=== RESUMEN CICLO ===")
    for r in resumen_global:
        logger.info(
            f"  {r['competidor']:12} → {r['productos']:4} productos "
            f"| {r['cambios']:3} cambios | {r['errores']:2} errores"
        )
    logger.info("=====================")


if __name__ == "__main__":
    main()
