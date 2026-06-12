# =============================================================================
# scrapers/campofrio_scraper.py — Scraper para campofrio.es
# Tipo: SPA — URLs de producto con patrón /p/nombre-producto
# =============================================================================

import logging
import re
from typing import Dict, List, Optional

from playwright.sync_api import Page

from scrapers.base_scraper import BaseScraper

logger = logging.getLogger(__name__)


class CampofrioScraper(BaseScraper):
    competidor_id = "campofrio"
    delay_entre_paginas = 2.5
    BASE_URL = "https://www.campofrio.es"

    def obtener_urls_productos(self, page: Page) -> List[str]:
        urls = set()

        categorias = [
            "/productos/jamon-cocido",
            "/productos/chorizo",
            "/productos/fuet",
            "/productos/mortadela-chopped",
            "/productos/pavo",
            "/productos/pollo",
            "/productos/salami",
            "/productos/salchichas",
            "/productos/salchichon",
            "/productos/snack",
            "/productos/vegetariano",
            "/productos/pizzas",
        ]

        # Aceptar cookies una sola vez
        page.goto(self.BASE_URL + "/productos", wait_until="networkidle")
        page.wait_for_timeout(3000)
        try:
            page.click('#onetrust-accept-btn-handler, button:has-text("Aceptar")', timeout=4000)
            page.wait_for_timeout(1500)
        except Exception:
            pass

        CATEGORIA_MAP = {
            "/productos/jamon-cocido":      "Jamón cocido",
            "/productos/chorizo":           "Embutidos",
            "/productos/fuet":              "Embutidos",
            "/productos/mortadela-chopped": "Embutidos",
            "/productos/pavo":              "Fiambres de ave",
            "/productos/pollo":             "Fiambres de ave",
            "/productos/salami":            "Embutidos",
            "/productos/salchichas":        "Salchichas",
            "/productos/salchichon":        "Embutidos",
            "/productos/snack":             "Snacking",
            "/productos/vegetariano":       "Vegetariano",
            "/productos/pizzas":            "Pizzas",
        }
        self._url_categoria_map = {}

        for cat in categorias:
            categoria_nombre = CATEGORIA_MAP.get(cat, cat.replace("/productos/","").replace("-"," ").title())
            try:
                page.goto(self.BASE_URL + cat, wait_until="networkidle")
                page.wait_for_timeout(3000)

                enlaces = page.query_selector_all("a[href]")
                nuevas = 0
                for el in enlaces:
                    href = el.get_attribute("href")
                    if href and href.startswith("/p/"):
                        url_completa = self.BASE_URL + href
                        if url_completa not in urls:
                            urls.add(url_completa)
                            self._url_categoria_map[url_completa] = categoria_nombre
                            nuevas += 1

                logger.info(f"[campofrio] {cat}: {nuevas} productos nuevos (total: {len(urls)})")
            except Exception as e:
                logger.warning(f"[campofrio] Error en {cat}: {e}")

        return list(urls)

    def extraer_producto(self, page: Page, url: str) -> Optional[Dict]:
        page.goto(url, wait_until="networkidle")
        page.wait_for_timeout(2000)

        nombre = self._texto(page, "h1")
        if not nombre:
            return None

        descripcion  = self._texto(page, ".product-description, .description, p.intro")
        categoria    = getattr(self, '_url_categoria_map', {}).get(url) or \
                       self._texto(page, ".breadcrumb li:nth-child(2) a") or \
                       self._inferir_categoria_por_nombre(nombre)
        subcategoria = self._texto(page, ".breadcrumb li:nth-child(3) a")
        gramaje      = self._extraer_gramaje(nombre)

        ingredientes     = self._buscar_seccion(page, "Ingredientes")
        nutricional      = self._extraer_tabla_nutricional(page)
        if not nutricional or not any(nutricional.values()):
            try:
                from scrapers.mistral_vision import extraer_nutricional_con_mistral
                img = page.screenshot(full_page=True)
                datos_vision = extraer_nutricional_con_mistral(img)
                if datos_vision and any(v for v in datos_vision.values() if v is not None):
                    nutricional = {k: datos_vision.get(k) for k in [
                        "kcal","proteinas_g","grasas_g","grasas_saturadas_g",
                        "carbohidratos_g","azucares_g","fibra_g","sal_g"]}
                    if not ingredientes and datos_vision.get("ingredientes"):
                        ingredientes = datos_vision["ingredientes"]
                    logger.info(f"[campofrio] Mistral Vision extrajo nutricional de {url}")
            except Exception as e:
                logger.debug(f"[campofrio] Mistral Vision fallido: {e}")
        porcentaje_carne = self._extraer_porcentaje_carne(ingredientes or "")
        analisis         = self.analizar_ingredientes(ingredientes or "")
        # Alérgenos: desde ingredientes + texto web de alérgenos
        alergenos        = self.normalizar_alergenos(ingredientes or "")
        alerg_texto      = self._buscar_alergenos_campofrio(page)
        if alerg_texto:
            alergenos = list(set(alergenos + self.normalizar_alergenos(alerg_texto)))
        claims_dict      = self._extraer_claims_detallados(page, ingredientes or "")
        url_foto         = self._extraer_foto(page)
        tipo_carne       = self._extraer_tipo_carne(nombre, ingredientes or "")

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
            "porcentaje_carne":    porcentaje_carne,
            "analisis_ingredientes": analisis,
        }
        return self.enriquecer_con_vision(page, datos)

    def _buscar_ingredientes_campofrio(self, page: Page) -> Optional[str]:
        """Extrae ingredientes del formato div de Campofrío."""
        try:
            resultado = page.evaluate("""
                () => {
                    const divs = document.querySelectorAll('div, section, article');
                    for (const el of divs) {
                        if (el.children.length > 8) continue;
                        const t = (el.innerText || '').trim();
                        const tl = t.toLowerCase();
                        // Buscar bloque que empiece con "Ingredientes" y tenga lista real
                        if (tl.startsWith('ingredientes') && t.length > 30 && t.length < 1500) {
                            return t.replace(/^ingredientes[:\\s]*/i, '').trim();
                        }
                    }
                    // Fallback: buscar línea "Ingredientes" seguida de contenido
                    const all = document.querySelectorAll('p, span, div');
                    for (let i = 0; i < all.length; i++) {
                        const t = (all[i].innerText || '').trim();
                        if (t.toLowerCase() === 'ingredientes' && i+1 < all.length) {
                            const next = (all[i+1].innerText || '').trim();
                            if (next.length > 20) return next;
                        }
                    }
                    return null;
                }
            """)
            return resultado
        except Exception:
            return None

    def _buscar_alergenos_campofrio(self, page: Page) -> Optional[str]:
        """Extrae el texto de alérgenos de Campofrío."""
        try:
            resultado = page.evaluate("""
                () => {
                    // Buscar span/div/p que diga "Libre de Alérgenos" o liste alérgenos
                    const candidatos = document.querySelectorAll('span, p, div, li');
                    for (const el of candidatos) {
                        const t = (el.innerText || '').trim();
                        const tl = t.toLowerCase();
                        if ((tl === 'libre de alérgenos' || tl === 'libre de alergenos')
                            && t.length < 100) {
                            return t;
                        }
                        // Texto corto que menciona alérgenos específicos
                        if (tl.includes('contiene') && tl.includes('alérgenos') && t.length < 300) {
                            return t;
                        }
                    }
                    return null;
                }
            """)
            return resultado
        except Exception:
            return None

    # -----------------------------------------------------------------------
    def _texto(self, page: Page, selector: str) -> Optional[str]:
        try:
            el = page.query_selector(selector)
            return el.inner_text().strip() if el else None
        except Exception:
            return None

    def _buscar_seccion(self, page: Page, etiqueta: str) -> Optional[str]:
        """
        Extrae el contenido de una sección del producto usando el texto completo de la página.
        Funciona con el formato de Campofrío que usa divs con texto plano.
        """
        try:
            # Obtener texto completo de la página
            texto_pagina = page.inner_text('body')
            lineas = [l.strip() for l in texto_pagina.split('\n') if l.strip()]
            etiqueta_lower = etiqueta.lower()

            # Secciones que indican el fin del bloque que buscamos
            SECCIONES_FIN = ['información nutricional', 'alérgenos', 'alergenos',
                             'ingredientes', 'información del producto', 'modo de empleo',
                             'conservación', 'valores medios']

            # Secciones que indican FIN del contenido buscado
            SECCIONES_FIN_EXTRA = [
                'recetas relacionadas', 'productos relacionados', 'también te puede gustar',
                'comida', 'cena', 'desayuno', 'merienda',
            ]
            todas_secciones_fin = [s for s in SECCIONES_FIN if s != etiqueta_lower] + SECCIONES_FIN_EXTRA

            for i, linea in enumerate(lineas):
                if linea.lower() == etiqueta_lower or linea.lower().startswith(etiqueta_lower + ':'):
                    contenido = []
                    for j in range(i + 1, min(i + 10, len(lineas))):
                        siguiente = lineas[j]
                        if any(siguiente.lower().startswith(s) for s in todas_secciones_fin):
                            break
                        if len(siguiente) > 5:
                            contenido.append(siguiente)
                    if contenido:
                        return ' '.join(contenido)
        except Exception as e:
            logger.debug(f"[campofrio] Error buscar sección '{etiqueta}': {e}")
        return None

    def _extraer_tabla_nutricional(self, page: Page) -> Dict:
        """
        Extrae la tabla nutricional de Campofrío.
        La web usa divs con texto plano: 'Etiqueta\\nValor' en lugar de <table>.
        """
        nutri = {}
        try:
            # Buscar el bloque que contiene "kcal" y "proteínas"
            bloque = page.evaluate("""
                () => {
                    const divs = document.querySelectorAll('div, section');
                    for (const el of divs) {
                        const t = el.innerText || '';
                        if (t.toLowerCase().includes('kcal') &&
                            t.toLowerCase().includes('prote') &&
                            t.length < 800) {
                            return t;
                        }
                    }
                    return null;
                }
            """)
            if not bloque:
                return {}

            import re
            lineas = [l.strip() for l in bloque.split('\n') if l.strip()]

            MAPA_ETIQUETAS = {
                "kcal":               ["valor", "energétic", "energia", "kcal"],
                "proteinas_g":        ["proteína", "proteina"],
                "grasas_g":           ["grasa"],
                "grasas_saturadas_g": ["saturada"],
                "carbohidratos_g":    ["hidrato", "carbohidrat"],
                "azucares_g":         ["azúcar", "azucar"],
                "fibra_g":            ["fibra"],
                "sal_g":              ["sal"],
            }

            for i, linea in enumerate(lineas):
                linea_l = linea.lower()
                for campo, palabras in MAPA_ETIQUETAS.items():
                    if campo in nutri:
                        continue
                    if any(p in linea_l for p in palabras):
                        # El valor está en la misma línea o en la siguiente
                        valor_txt = linea
                        if i + 1 < len(lineas):
                            valor_txt = lineas[i + 1]
                        if campo == "kcal":
                            m = re.search(r"(\d[\d,\.]*)\s*kcal", valor_txt, re.IGNORECASE)
                            if m:
                                nutri[campo] = self.normalizar_numero(m.group(1))
                        else:
                            nutri[campo] = self.normalizar_numero(valor_txt)
        except Exception as e:
            logger.debug(f"[campofrio] Error extrayendo nutricional: {e}")

        # También intentar con ingredientes el % de carne desde el mismo bloque
        return nutri

    def _extraer_tabla_nutricional_legacy(self, page: Page) -> Dict:
        """Método legacy por tabla HTML — fallback."""
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
            filas = page.query_selector_all("table tr, .nutrition tr, .nutritional-table tr")
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
            logger.debug(f"[campofrio] Error tabla nutricional: {e}")
        return nutri

    def _extraer_claims_detallados(self, page: Page, ingredientes: str) -> Dict:
        try:
            todo = page.inner_text("body")
        except Exception:
            todo = ""
        return self.extraer_claims_completos(todo, ingredientes)

    def _extraer_foto(self, page: Page) -> Optional[str]:
        try:
            el = page.query_selector("img.product-image, .product-photo img, img[class*='product']")
            return el.get_attribute("src") if el else None
        except Exception:
            return None

    def _extraer_tipo_carne(self, nombre: str, ingredientes: str) -> Optional[str]:
        texto = (nombre + " " + ingredientes).lower()
        if "ibérico" in texto or "iberico" in texto: return "Cerdo Ibérico"
        if "pavo" in texto: return "Pavo"
        if "pollo" in texto: return "Pollo"
        if "vacuno" in texto or "ternera" in texto: return "Vacuno"
        if "cerdo" in texto or "jamón" in texto: return "Cerdo"
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
