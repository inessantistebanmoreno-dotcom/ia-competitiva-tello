# =============================================================================
# scrapers/argal_scraper.py — Scraper para argal.com
# Tipo: HTML con playwright-stealth (evita reCAPTCHA)
# URL real: argal.com (no argal.es)
# =============================================================================

import logging
import re
import time
from typing import Dict, List, Optional

from playwright.sync_api import Page, BrowserContext

from scrapers.base_scraper import BaseScraper

logger = logging.getLogger(__name__)


class ArgalScraper(BaseScraper):
    competidor_id = "argal"
    delay_entre_paginas = 3.0
    BASE_URL = "https://argal.com"

    # -----------------------------------------------------------------------
    # Override del método scrape() para usar stealth
    # -----------------------------------------------------------------------
    def scrape(self) -> List[Dict]:
        """Ciclo completo con playwright-stealth para evitar reCAPTCHA de Argal."""
        from playwright.sync_api import sync_playwright
        from playwright_stealth import Stealth

        resultados = []
        stealth = Stealth()

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
            stealth.apply_stealth_sync(context)
            page = context.new_page()
            page.set_default_timeout(20000)

            # 1. Obtener URLs del catálogo
            urls = self.obtener_urls_productos(page)
            logger.info(f"[argal] {len(urls)} URLs de producto encontradas")

            # 2. Extraer cada ficha
            for url in urls:
                time.sleep(self.delay_entre_paginas)
                try:
                    datos = self.extraer_producto(page, url)
                    if datos:
                        datos["competidor"] = self.competidor_id
                        datos["url_producto"] = url
                        resultados.append(datos)
                        logger.info(f"  ✓ {datos.get('nombre_producto', url)}")
                except Exception as e:
                    logger.warning(f"  ✗ Saltando {url}: {e}")

            browser.close()

        logger.info(f"[argal] Scraping completado: {len(resultados)} productos")
        return resultados

    # -----------------------------------------------------------------------
    # 1. Catálogo
    # -----------------------------------------------------------------------

    def obtener_urls_productos(self, page: Page) -> List[str]:
        urls = set()

        # Todas las categorías de Argal bajo /gama/
        categorias = [
            "/gama/jamon-cocido/",
            "/gama/pavo-y-pollo/",
            "/gama/mortadela-y-chopped/",
            "/gama/fuet-y-longaniza/",
            "/gama/jamon-y-lomo/",
            "/gama/chorizo-y-salchichon/",
            "/gama/ibericos/",
            "/gama/salchichas/",
            "/gama/pates/",
            "/gama/snacks/",
            "/gama/platos-preparados/",
            "/bonnatur/",
            "/oliving/",
        ]

        # Aceptar cookies en la primera visita
        page.goto(self.BASE_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        try:
            page.click('button:has-text("Aceptar"), button:has-text("Accept"), #accept-cookies', timeout=3000)
            page.wait_for_timeout(1000)
        except Exception:
            pass

        for cat in categorias:
            try:
                page.goto(f"{self.BASE_URL}{cat}", wait_until="domcontentloaded")
                page.wait_for_timeout(3000)

                # Scroll para cargar lazy-loading
                for _ in range(4):
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(1000)

                enlaces = page.query_selector_all("a[href]")
                nuevas = 0
                for el in enlaces:
                    href = el.get_attribute("href") or ""
                    if ("/productos/" in href and "argal.com" in href
                            and href not in urls
                            and href.rstrip("/") != f"{self.BASE_URL}/productos"):
                        urls.add(href)
                        nuevas += 1

                logger.info(f"[argal] {cat}: {nuevas} nuevos (total: {len(urls)})")
            except Exception as e:
                logger.warning(f"[argal] Error en {cat}: {e}")

        return list(urls)

    # -----------------------------------------------------------------------
    # 2. Ficha de producto
    # -----------------------------------------------------------------------

    def extraer_producto(self, page: Page, url: str) -> Optional[Dict]:
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(2500)

        nombre = self._texto(page, "h1")
        if not nombre or nombre.lower() in ["productos", "argal"]:
            return None

        descripcion  = self._texto(page, ".product-description, .entry-content p, .product-intro, .descripcion")
        categoria    = self._texto(page, "nav.breadcrumb li:nth-child(2) a, .breadcrumb-item:nth-child(2) a")
        subcategoria = self._texto(page, "nav.breadcrumb li:nth-child(3) a")
        gramaje      = self._extraer_gramaje(nombre)

        # Ingredientes
        ingredientes = self._buscar_seccion_js(page, "Ingredientes")

        # Tabla nutricional — HTML primero, Mistral Vision como fallback
        vision_porcentaje_carne = None
        nutricional = self._extraer_tabla_nutricional(page)
        if not nutricional or not any(nutricional.values()):
            try:
                from scrapers.mistral_vision import extraer_nutricional_con_mistral
                img = page.screenshot(full_page=True)
                datos_vision = extraer_nutricional_con_mistral(img)
                if datos_vision and any(v for v in datos_vision.values() if v is not None):
                    nutricional = {
                        "kcal":               datos_vision.get("kcal"),
                        "proteinas_g":        datos_vision.get("proteinas_g"),
                        "grasas_g":           datos_vision.get("grasas_g"),
                        "grasas_saturadas_g": datos_vision.get("grasas_saturadas_g"),
                        "carbohidratos_g":    datos_vision.get("carbohidratos_g"),
                        "azucares_g":         datos_vision.get("azucares_g"),
                        "fibra_g":            datos_vision.get("fibra_g"),
                        "sal_g":              datos_vision.get("sal_g"),
                    }
                    if not ingredientes and datos_vision.get("ingredientes"):
                        ingredientes = datos_vision["ingredientes"]
                    if datos_vision.get("porcentaje_carne"):
                        vision_porcentaje_carne = datos_vision["porcentaje_carne"]
                    logger.info(f"[argal] Mistral Vision extrajo nutricional de {url}")
            except Exception as e:
                logger.debug(f"[argal] Mistral Vision fallido: {e}")

        # Claims y alérgenos
        claims_dict  = self._extraer_claims_detallados(page, ingredientes or "")
        alergenos    = self.normalizar_alergenos(ingredientes or "")
        pct_carne    = self._extraer_porcentaje_carne(ingredientes or "") or vision_porcentaje_carne
        analisis     = self.analizar_ingredientes(ingredientes or "")
        url_foto     = self._extraer_foto(page)
        tipo_carne   = self._extraer_tipo_carne(nombre, ingredientes or "")

        datos = {
            "nombre_producto":     nombre.strip(),
            "descripcion":         descripcion,
            "categoria":           categoria,
            "subcategoria":        subcategoria,
            "formato":             None,
            "gramaje_g":           gramaje,
            "tipo_carne":          tipo_carne,
            "url_foto":            url_foto,
            "ingredientes":        ingredientes,
            "kcal":                nutricional.get("kcal"),
            "proteinas_g":         nutricional.get("proteinas_g"),
            "grasas_g":            nutricional.get("grasas_g"),
            "grasas_saturadas_g":  nutricional.get("grasas_saturadas_g"),
            "carbohidratos_g":     nutricional.get("carbohidratos_g"),
            "azucares_g":          nutricional.get("azucares_g"),
            "fibra_g":             nutricional.get("fibra_g"),
            "sal_g":               nutricional.get("sal_g"),
            "alergenos":           alergenos,
            "sin_gluten":          claims_dict.get("sin_gluten"),
            "sin_lactosa":         claims_dict.get("sin_lactosa"),
            "sin_colorantes":      claims_dict.get("sin_colorantes"),
            "sin_conservantes":    claims_dict.get("sin_conservantes"),
            "claims":              claims_dict.get("claims_lista", []),
            "claim_pct_carne":     claims_dict.get("claim_pct_carne"),
            "claim_nutricional":   claims_dict.get("claim_nutricional"),
            "claim_proteinas":     claims_dict.get("claim_proteinas"),
            "claim_grasa":         claims_dict.get("claim_grasa"),
            "claim_sellos":        claims_dict.get("claim_sellos"),
            "claim_gama":          claims_dict.get("claim_gama"),
            "claim_seleccion":     claims_dict.get("claim_seleccion"),
            "claim_conveniencia":  claims_dict.get("claim_conveniencia"),
            "claim_raciones":      claims_dict.get("claim_raciones"),
            "claim_modo_coccion":  claims_dict.get("claim_modo_coccion"),
            "porcentaje_carne":    pct_carne,
            "analisis_ingredientes": analisis,
        }
        return self.enriquecer_con_vision(page, datos)

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _texto(self, page: Page, selector: str) -> Optional[str]:
        try:
            el = page.query_selector(selector)
            return el.inner_text().strip() if el else None
        except Exception:
            return None

    def _buscar_seccion_js(self, page: Page, etiqueta: str) -> Optional[str]:
        try:
            resultado = page.evaluate(f"""
                () => {{
                    const etiqueta = '{etiqueta.lower()}';
                    const elementos = document.querySelectorAll('p, li, dt, dd, span, h3, h4');
                    for (const el of elementos) {{
                        const t = el.innerText ? el.innerText.trim() : '';
                        if (t.toLowerCase().startsWith(etiqueta) && t.length > etiqueta.length + 2) {{
                            return t.substring(etiqueta.length).replace(/^[:\\s]+/, '').trim();
                        }}
                    }}
                    return null;
                }}
            """)
            return resultado
        except Exception:
            return None

    def _extraer_tabla_nutricional(self, page: Page) -> Dict:
        nutri = {}
        mapa = {
            "kcal":               ["energía", "valor energético", "kcal"],
            "proteinas_g":        ["proteínas"],
            "grasas_g":           ["grasas"],
            "grasas_saturadas_g": ["saturadas"],
            "carbohidratos_g":    ["hidratos de carbono", "carbohidratos"],
            "azucares_g":         ["azúcares"],
            "fibra_g":            ["fibra"],
            "sal_g":              ["sal"],
        }
        try:
            filas = page.query_selector_all("table tr, dl.nutrition dt, .nutrition-item, .nutri-row")
            for fila in filas:
                celdas = fila.query_selector_all("td, dd, span")
                if len(celdas) >= 2:
                    etiq = celdas[0].inner_text().lower().strip()
                    val  = celdas[-1].inner_text().strip()
                    for campo, palabras in mapa.items():
                        if any(p in etiq for p in palabras) and campo not in nutri:
                            if campo == "kcal":
                                m = re.search(r"(\d[\d,\.]*)\s*kcal", val, re.IGNORECASE)
                                nutri[campo] = self.normalizar_numero(m.group(1)) if m else self.normalizar_numero(val)
                            else:
                                nutri[campo] = self.normalizar_numero(val)
        except Exception as e:
            logger.debug(f"[argal] Error tabla: {e}")
        return nutri

    def _extraer_claims_detallados(self, page: Page, ingredientes: str) -> Dict:
        try:
            todo = page.inner_text("body")
        except Exception:
            todo = ""
        return self.extraer_claims_completos(todo, ingredientes)

    def _extraer_foto(self, page: Page) -> Optional[str]:
        try:
            el = page.query_selector("img.product-image, .product-img img, img[class*='product'], .wp-post-image")
            return el.get_attribute("src") if el else None
        except Exception:
            return None

    def _extraer_tipo_carne(self, nombre: str, ingredientes: str) -> Optional[str]:
        texto = (nombre + " " + ingredientes).lower()
        if "ibérico" in texto or "iberico" in texto: return "Cerdo Ibérico"
        if "pavo" in texto: return "Pavo"
        if "pollo" in texto: return "Pollo"
        if "vacuno" in texto or "ternera" in texto: return "Vacuno"
        if "cerdo" in texto or "jamón" in texto or "paleta" in texto: return "Cerdo"
        return None

    def _extraer_gramaje(self, nombre: str) -> Optional[float]:
        m = re.search(r"(\d+[\.,]?\d*)\s*(?:g|gr|kg)\b", nombre, re.IGNORECASE)
        if m:
            peso = float(m.group(1).replace(",", "."))
            if "kg" in m.group(0).lower(): peso *= 1000
            return peso
        return None

    def _extraer_porcentaje_carne(self, ingredientes: str) -> Optional[float]:
        return self.extraer_porcentaje_carne_de_ingredientes(ingredientes)
