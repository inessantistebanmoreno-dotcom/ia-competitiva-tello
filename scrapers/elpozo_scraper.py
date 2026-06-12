# =============================================================================
# scrapers/elpozo_scraper.py — Scraper para elpozo.com
# Tipo: HTML con paginación (/productos/page/N/)
# =============================================================================

import logging
import re
from typing import Dict, List, Optional

from playwright.sync_api import Page

from scrapers.base_scraper import BaseScraper
from scrapers.ocr_extractor import extraer_nutricional_de_imagen

logger = logging.getLogger(__name__)


class ElPozoScraper(BaseScraper):
    competidor_id = "elpozo"
    delay_entre_paginas = 0.8  # reducido para GitHub Actions (evitar timeout)
    BASE_URL = "https://www.elpozo.com"

    def obtener_urls_productos(self, page: Page) -> List[str]:
        urls = set()

        # Timeout más generoso para El Pozo (web lenta con muchos assets)
        page.set_default_timeout(45000)

        # Aceptar cookies en la primera visita
        page.goto(f"{self.BASE_URL}/productos/", wait_until="domcontentloaded")
        page.wait_for_timeout(4000)
        try:
            page.click('button:has-text("Aceptar"), #onetrust-accept-btn-handler', timeout=4000)
            page.wait_for_timeout(2000)
        except Exception:
            pass

        pagina = 1
        fallos_consecutivos = 0
        while True:
            url_pag = f"{self.BASE_URL}/productos/page/{pagina}/" if pagina > 1 else f"{self.BASE_URL}/productos/"

            # Cada página tiene su propio try/except — un timeout no para el scan
            try:
                page.goto(url_pag, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(2000)
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(1000)
                fallos_consecutivos = 0
            except Exception as e:
                fallos_consecutivos += 1
                logger.warning(f"[elpozo] Página {pagina} timeout ({fallos_consecutivos} fallo(s)): {e}")
                if fallos_consecutivos >= 3:
                    logger.warning(f"[elpozo] 3 fallos consecutivos — deteniendo paginación")
                    break
                pagina += 1
                continue

            enlaces = page.query_selector_all("a[href]")
            nuevas = 0
            for el in enlaces:
                href = el.get_attribute("href")
                if (href and "elpozo.com/productos/" in href
                        and "/page/" not in href
                        and href != f"{self.BASE_URL}/productos/"):
                    if href not in urls:
                        urls.add(href)
                        nuevas += 1

            logger.info(f"[elpozo] Página {pagina}: {nuevas} nuevos (total: {len(urls)})")
            if nuevas == 0:
                break
            pagina += 1

        return list(urls)

    def extraer_producto(self, page: Page, url: str) -> Optional[Dict]:
        page.goto(url, wait_until="networkidle")
        page.wait_for_timeout(2000)

        nombre = self._texto(page, "h1")
        if not nombre:
            return None

        descripcion  = self._texto(page, ".product-description, .entry-content p, .product-intro")
        categoria    = self._texto(page, ".breadcrumb li:nth-child(2) a, nav.breadcrumb li:nth-child(2)") or \
                       self._inferir_categoria_por_nombre(nombre)
        subcategoria = self._texto(page, ".breadcrumb li:nth-child(3) a")
        gramaje      = self._extraer_gramaje(nombre)

        # Ingredientes
        ingredientes = self._buscar_ingredientes_elpozo(page)

        # Tabla nutricional — intentar en orden de fiabilidad
        nutricional = self._extraer_nutricional_texto(page)
        if not nutricional or not any(nutricional.values()):
            nutricional = self._extraer_tabla_nutricional(page)
        vision_porcentaje_carne = None
        if not nutricional or not any(nutricional.values()):
            # Fallback: Mistral Vision (gratuito, disponible en España)
            try:
                from scrapers.mistral_vision import extraer_nutricional_de_screenshot
                datos_vision = extraer_nutricional_de_screenshot(page)
                if datos_vision:
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
                    # Aprovechar ingredientes, claims y % carne si los extrajo Mistral
                    if not ingredientes and datos_vision.get("ingredientes"):
                        ingredientes = datos_vision["ingredientes"]
                    # Guardar % carne de Mistral como fallback por si el regex falla
                    if datos_vision.get("porcentaje_carne"):
                        vision_porcentaje_carne = datos_vision["porcentaje_carne"]
            except Exception as e:
                logger.debug(f"[elpozo] Mistral Vision fallido: {e}")

        # Alérgenos y claims
        alergenos    = self.normalizar_alergenos(ingredientes or "")
        claims_dict  = self._extraer_claims_detallados(page, ingredientes or "")
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
        # El Pozo: tabla nutricional en imagen → Vision siempre obligatorio (forzar=True)
        return self.enriquecer_con_vision(page, datos, forzar=True)

    # -----------------------------------------------------------------------
    def _texto(self, page: Page, selector: str) -> Optional[str]:
        try:
            el = page.query_selector(selector)
            return el.inner_text().strip() if el else None
        except Exception:
            return None

    def _buscar_seccion(self, page: Page, etiqueta: str) -> Optional[str]:
        try:
            # Usar JavaScript para buscar el texto — mucho más rápido que iterar elementos
            resultado = page.evaluate(f"""
                () => {{
                    const etiqueta = '{etiqueta.lower()}';
                    const elementos = document.querySelectorAll('p, li, dt, dd, span.label, h3, h4');
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
            pass
        return None

    def _extraer_nutricional_ocr(self, page: Page) -> Dict:
        """
        Cuando la tabla nutricional está en imagen, captura screenshot
        y usa EasyOCR para extraer los valores. Gratis, sin API key.
        """
        try:
            # Selectores comunes donde El Pozo pone la imagen nutricional
            selectores = [
                "img[alt*='nutri']", "img[alt*='Nutri']",
                "img[src*='nutri']", "img[src*='tabla']",
                ".nutritional-image img", ".nutrition-image img",
                ".product-nutrition img", "img[class*='nutri']",
            ]
            img_el = None
            for sel in selectores:
                img_el = page.query_selector(sel)
                if img_el:
                    break

            if img_el:
                img_bytes = img_el.screenshot()
                logger.debug(f"[elpozo] OCR en imagen nutricional")
            else:
                # Captura de la zona inferior de la página donde suele estar la tabla
                img_bytes = page.screenshot(full_page=True)

            from scrapers.ocr_extractor import extraer_nutricional_de_imagen
            return extraer_nutricional_de_imagen(img_bytes)

        except Exception as e:
            logger.debug(f"[elpozo] OCR fallido: {e}")
            return {}

    def _buscar_ingredientes_elpozo(self, page: Page) -> Optional[str]:
        """Extrae ingredientes de El Pozo, expandiendo tabs/acordeones si es necesario."""
        try:
            # Intentar expandir secciones de ingredientes/información
            TRIGGERS = [
                "li:has-text('Ingredientes')", "a:has-text('Ingredientes')",
                "button:has-text('Ingredientes')", ".tab:has-text('Ingredientes')",
                "li:has-text('Composición')", "a:has-text('Composición')",
                ".accordion:has-text('Ingredientes')", "[data-tab*='ingredient']",
                "li:has-text('Información')", "a:has-text('Información del producto')",
            ]
            for trigger in TRIGGERS:
                try:
                    el = page.query_selector(trigger)
                    if el:
                        el.click()
                        page.wait_for_timeout(500)
                        break
                except Exception:
                    continue

            texto = page.inner_text('body')
            lineas = [l.strip() for l in texto.split('\n') if l.strip()]
            SECCIONES_FIN = ['alérgenos', 'alergenos', 'inf. nutricional', 'información nutricional',
                             'recetas', 'productos relacionados', 'también te puede gustar',
                             'conservación', 'modo de empleo']
            for i, linea in enumerate(lineas):
                if linea.lower() in ('ingredientes', 'ingredientes:'):
                    contenido = []
                    for j in range(i + 1, min(i + 15, len(lineas))):
                        sig = lineas[j]
                        if any(sig.lower().startswith(s) for s in SECCIONES_FIN):
                            break
                        if len(sig) > 5:
                            contenido.append(sig)
                    if contenido:
                        return ' '.join(contenido)
                if linea.lower().startswith('ingredientes:') and len(linea) > 15:
                    return linea.split(':', 1)[1].strip()
        except Exception as e:
            logger.debug(f"[elpozo] Error extrayendo ingredientes: {e}")
        return None

    def _extraer_nutricional_texto(self, page: Page) -> Dict:
        """
        Extrae la tabla nutricional de El Pozo desde el texto de la página.
        Formato: 'Energía: 220 kcal', 'Grasas: 9,6 g', etc.
        """
        nutri = {}
        try:
            texto = page.inner_text('body')
            lineas = [l.strip() for l in texto.split('\n') if l.strip()]

            MAPA = {
                "kcal":               ["energía", "energia", "valor energético"],
                "proteinas_g":        ["proteínas", "proteinas"],
                "grasas_g":           ["grasas:"],
                "grasas_saturadas_g": ["saturadas"],
                "carbohidratos_g":    ["hidratos de carbono", "carbohidratos"],
                "azucares_g":         ["azúcares", "azucares"],
                "fibra_g":            ["fibra"],
                "sal_g":              ["sal:"],
            }

            for linea in lineas:
                linea_l = linea.lower()
                for campo, palabras in MAPA.items():
                    if campo in nutri:
                        continue
                    if any(linea_l.startswith(p) for p in palabras):
                        # Extraer el valor numérico de la línea
                        if campo == "kcal":
                            import re
                            m = re.search(r"(\d[\d,\.]*)\s*kcal", linea, re.IGNORECASE)
                            if m:
                                nutri[campo] = self.normalizar_numero(m.group(1))
                        else:
                            # Formato: "Grasas: 9,6 g" → extraer "9,6"
                            import re
                            m = re.search(r":\s*([<>]?\d[\d,\.]*)\s*g", linea, re.IGNORECASE)
                            if m:
                                nutri[campo] = self.normalizar_numero(m.group(1))
        except Exception as e:
            logger.debug(f"[elpozo] Error nutricional texto: {e}")
        return nutri

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
            filas = page.query_selector_all("table tr, .nutrition tr, .nutritional-info tr")
            for fila in filas:
                celdas = fila.query_selector_all("td, th")
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
            logger.debug(f"[elpozo] Error tabla nutricional: {e}")
        return nutri

    def _extraer_claims_detallados(self, page: Page, ingredientes: str) -> Dict:
        try:
            todo = page.inner_text("body")
        except Exception:
            todo = ""
        return self.extraer_claims_completos(todo, ingredientes)

    def _extraer_foto(self, page: Page) -> Optional[str]:
        """Extrae la URL de la imagen principal del producto.
        El Pozo usa CSS background-image en div.image, NO etiquetas <img>.
        """
        try:
            # Primario: extraer URL de CSS background-image (formato propio de El Pozo)
            src = page.evaluate("""
                () => {
                    const selectors = [
                        '.image[style*="background-image"]',
                        '.product-image[style*="background-image"]',
                        '.foto[style*="background-image"]',
                        'div[style*="background-image"]',
                    ];
                    for (const sel of selectors) {
                        const els = document.querySelectorAll(sel);
                        for (const el of els) {
                            const style = el.getAttribute('style') || '';
                            const m = style.match(/background-image:\\s*url\\(['"]?([^'"\\)\\s]+)['"]?\\)/);
                            if (m && m[1]
                                && !m[1].includes('logo')
                                && !m[1].includes('banner')
                                && !m[1].includes('icon')
                                && (m[1].includes('/productos/') || m[1].includes('/uploads/'))) {
                                return m[1];
                            }
                        }
                    }
                    // Segunda pasada: cualquier background-image que parezca packaging
                    const all = document.querySelectorAll('[style*="background-image"]');
                    for (const el of all) {
                        const style = el.getAttribute('style') || '';
                        const m = style.match(/background-image:\s*url\(['"]?([^'")\s]+)['"]?\)/);
                        if (m && m[1] && !m[1].includes('logo') && !m[1].includes('banner')) {
                            return m[1];
                        }
                    }
                    return null;
                }
            """)
            if src:
                return src

            # Fallback: selectores <img> estándar (por si cambiasen la web)
            SELECTORES = [
                ".woocommerce-product-gallery__image img",
                ".product-gallery img",
                ".wp-post-image",
                "img.attachment-woocommerce_single",
                "img.size-full",
                ".product-image img",
                "img[class*='product']",
                "article img",
            ]
            for sel in SELECTORES:
                el = page.query_selector(sel)
                if el:
                    src = el.get_attribute("src") or el.get_attribute("data-src")
                    if src and not src.endswith('.svg') and 'placeholder' not in src:
                        return src

            # Último recurso JS: imagen <img> más grande de la página
            src = page.evaluate("""
                () => {
                    const imgs = Array.from(document.querySelectorAll('img[src]'));
                    const candidates = imgs
                        .filter(img => img.naturalWidth > 200 && img.naturalHeight > 200)
                        .filter(img => !img.src.includes('logo') && !img.src.includes('icon')
                                    && !img.src.includes('banner') && !img.src.endsWith('.svg'));
                    if (!candidates.length) return null;
                    candidates.sort((a,b) => (b.naturalWidth*b.naturalHeight) - (a.naturalWidth*a.naturalHeight));
                    return candidates[0].src;
                }
            """)
            return src or None
        except Exception as e:
            logger.debug(f"[elpozo] Error extrayendo foto: {e}")
            return None

    def _extraer_tipo_carne(self, nombre: str, ingredientes: str) -> Optional[str]:
        texto = (nombre + " " + ingredientes).lower()
        if "ibérico" in texto or "iberico" in texto: return "Cerdo Ibérico"
        if "pavo" in texto: return "Pavo"
        if "pollo" in texto: return "Pollo"
        if "vacuno" in texto or "añojo" in texto or "ternera" in texto: return "Vacuno"
        if "cordero" in texto: return "Cordero"
        if "cerdo" in texto or "jamón" in texto or "lomo" in texto: return "Cerdo"
        if "mixto" in texto or "mixta" in texto: return "Mixto"
        return None

    def _extraer_gramaje(self, nombre: str) -> Optional[float]:
        m = re.search(r"(\d+[\.,]?\d*)\s*(?:g|gr|kg)\b", nombre, re.IGNORECASE)
        if m:
            peso = float(m.group(1).replace(",", "."))
            if "kg" in m.group(0).lower():
                peso *= 1000
            return peso
        return None

    def _extraer_porcentaje_carne(self, ingredientes: str) -> Optional[float]:
        return self.extraer_porcentaje_carne_de_ingredientes(ingredientes)
