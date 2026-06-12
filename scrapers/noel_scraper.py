# =============================================================================
# scrapers/noel_scraper.py — Scraper para noel.es
# Tipo: HTML (texto directo en el DOM)
# =============================================================================

import logging
import re
from typing import Dict, List, Optional

from playwright.sync_api import Page

from scrapers.base_scraper import BaseScraper

logger = logging.getLogger(__name__)


class NoelScraper(BaseScraper):
    competidor_id = "noel"
    delay_entre_paginas = 2.0

    # -----------------------------------------------------------------------
    # 1. Catálogo: obtener todas las URLs de producto
    # -----------------------------------------------------------------------

    def obtener_urls_productos(self, page: Page) -> List[str]:
        urls = set()

        categorias = [
            "https://www.noel.es/categorias/cocidos/",
            "https://www.noel.es/categorias/curados/",
            "https://www.noel.es/categorias/delizias-finas/",
            "https://www.noel.es/categorias/carne-fresca/",
            "https://www.noel.es/categorias/platos-preparados/",
            "https://www.noel.es/categorias/snacking/",
            "https://www.noel.es/categorias/productosasados/",
            "https://www.noel.es/categorias/delipro-2/",
        ]

        # Mapa URL de categoría → nombre de categoría legible
        CATEGORIA_MAP = {
            "cocidos":          "Cocidos",
            "curados":          "Curados",
            "delizias-finas":   "Cocidos",
            "carne-fresca":     "Carne Fresca",
            "platos-preparados":"Platos Preparados",
            "snacking":         "Snacking",
            "productosasados":  "Asados",
            "delipro-2":        "Cocidos",
        }

        # url → categoría para asignar al extraer cada producto
        self._url_categoria_map = {}

        for url_cat in categorias:
            # Determinar categoría desde la URL
            slug = url_cat.rstrip("/").split("/")[-1]
            categoria_nombre = CATEGORIA_MAP.get(slug, slug.replace("-", " ").title())

            try:
                page.goto(url_cat, wait_until="networkidle")
                page.wait_for_timeout(3000)

                try:
                    page.click('button:has-text("Aceptar"), button:has-text("Accept")', timeout=3000)
                    page.wait_for_timeout(1000)
                except Exception:
                    pass

                enlaces = page.query_selector_all("a[href]")
                nuevas = 0
                for el in enlaces:
                    href = el.get_attribute("href")
                    if href and "/productos/" in href and href.count("/") >= 4 and href not in urls:
                        urls.add(href)
                        self._url_categoria_map[href] = categoria_nombre
                        nuevas += 1

                logger.info(f"[noel] {url_cat}: {nuevas} productos nuevos (total: {len(urls)})")
            except Exception as e:
                logger.warning(f"[noel] Error en categoría {url_cat}: {e}")

        return list(urls)

    # -----------------------------------------------------------------------
    # 2. Ficha de producto
    # -----------------------------------------------------------------------

    def extraer_producto(self, page: Page, url: str) -> Optional[Dict]:
        page.goto(url, wait_until="domcontentloaded")

        nombre = self._texto(page, "h1.product-title, h1.entry-title, h1")
        if not nombre:
            return None

        descripcion  = self._texto(page, ".product-description, .entry-content p")
        # Prioridad: inferencia por nombre (específica) > breadcrumb > mapa de categorías del catálogo (genérico)
        # _inferir_categoria_por_nombre da "Jamón cocido", "Mortadela y chopped", etc.
        # El CATEGORIA_MAP de Noel es demasiado genérico ("Cocidos" para jamón, mortadela y salchichas)
        categoria    = self._inferir_categoria_por_nombre(nombre) or \
                       self._texto(page, ".breadcrumb li:nth-child(2), .product-category") or \
                       getattr(self, '_url_categoria_map', {}).get(url)
        subcategoria = self._texto(page, ".breadcrumb li:nth-child(3)")
        gramaje      = self._extraer_gramaje(nombre)

        ingredientes = self._texto(page, ".ingredientes, [class*='ingredient'], .tab-ingredientes")
        if not ingredientes:
            ingredientes = self._buscar_texto_con_etiqueta(page, "Ingredientes")

        nutricional      = self._extraer_tabla_nutricional_html(page)
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
                    logger.info(f"[noel] Mistral Vision extrajo nutricional de {url}")
            except Exception as e:
                logger.debug(f"[noel] Mistral Vision fallido: {e}")
        claims_dict      = self._extraer_claims_detallados(page, ingredientes or "")
        porcentaje_carne = self._extraer_porcentaje_carne(ingredientes or "")
        analisis         = self.analizar_ingredientes(ingredientes or "")
        alergenos        = self.normalizar_alergenos(ingredientes or "")
        alerg_texto      = self._texto(page, ".alergenos, [class*='allergen']")
        if alerg_texto:
            alergenos = list(set(alergenos + self.normalizar_alergenos(alerg_texto)))

        # Foto del producto
        url_foto = self._extraer_foto(page)

        # Tipo de carne detectado de ingredientes/nombre
        tipo_carne = self._extraer_tipo_carne(nombre, ingredientes or "")

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

    # -----------------------------------------------------------------------
    # Helpers privados
    # -----------------------------------------------------------------------

    def _texto(self, page: Page, selector: str) -> Optional[str]:
        try:
            el = page.query_selector(selector)
            return el.inner_text().strip() if el else None
        except Exception:
            return None

    def _buscar_texto_con_etiqueta(self, page: Page, etiqueta: str) -> Optional[str]:
        try:
            els = page.query_selector_all("p, li, div")
            for el in els:
                t = el.inner_text()
                if t.lower().startswith(etiqueta.lower()):
                    return t[len(etiqueta):].lstrip(":").strip()
        except Exception:
            pass
        return None

    def _extraer_tabla_nutricional_html(self, page: Page) -> Dict:
        nutri = {}
        mapa = {
            "kcal":               ["valor energético", "energía", "kcal", "kj"],
            "proteinas_g":        ["proteínas", "proteinas"],
            "grasas_g":           ["grasas totales", "lípidos", "grasas"],
            "grasas_saturadas_g": ["ácidos grasos saturados", "saturadas"],
            "carbohidratos_g":    ["hidratos de carbono", "carbohidratos"],
            "azucares_g":         ["azúcares", "azucares"],
            "fibra_g":            ["fibra"],
            "sal_g":              ["sal"],
        }
        try:
            filas = page.query_selector_all("table tr, .nutrition-row, .nutri-row")
            for fila in filas:
                celdas = fila.query_selector_all("td, th")
                if len(celdas) >= 2:
                    etiqueta  = celdas[0].inner_text().lower().strip()
                    valor_txt = celdas[1].inner_text().strip()
                    for campo, palabras in mapa.items():
                        if any(p in etiqueta for p in palabras) and campo not in nutri:
                            if campo == "kcal":
                                m = re.search(r"(\d[\d,\.]*)\s*kcal", valor_txt, re.IGNORECASE)
                                if m:
                                    nutri[campo] = self.normalizar_numero(m.group(1))
                            else:
                                nutri[campo] = self.normalizar_numero(valor_txt)
        except Exception as e:
            logger.debug(f"[noel] Error extrayendo tabla nutricional: {e}")
        return nutri

    def _extraer_claims_detallados(self, page: Page, ingredientes: str) -> Dict:
        """Extrae claims usando el catálogo completo del base scraper."""
        try:
            todo = page.inner_text("body")
        except Exception:
            todo = ""
        return self.extraer_claims_completos(todo, ingredientes)

    def _extraer_claims_detallados_legacy(self, page: Page, ingredientes: str) -> Dict:
        """[LEGACY - no usado] Implementación anterior específica de Noel."""
        try:
            todo = page.inner_text("body").lower()
            todo_orig = page.inner_text("body")
        except Exception:
            todo = ""
            todo_orig = ""

        # ── Sin Gluten / Lactosa / Colorantes / Conservantes ──
        # Solo True si está EXPLÍCITAMENTE declarado en el packaging
        sin_gluten       = "sin gluten" in todo
        sin_lactosa      = "sin lactosa" in todo
        sin_colorantes   = "sin colorantes" in todo
        sin_conservantes = "sin conservantes" in todo

        # ── Claim 1: % Carne ── Formato: "99% de carne", "93% de carne"
        claim_pct_carne = None
        m = re.search(r"(\d+[\.,]?\d*)\s*%\s*(?:de\s+)?carne", todo, re.IGNORECASE)
        if m:
            claim_pct_carne = m.group(0).strip().title()

        # ── Claim 2: Nutricional ── Puede incluir varios sub-claims separados por " / "
        # Formato Excel: "Rico en colágeno / Sin Fosfatos Añadidos", "Calidad Extra / Sin Fosfatos Añadidos"
        claim_nutricional = None
        nutri_claims = []
        NUTRI_KWS = [
            ("reducida en sal",          "Reducida en Sal"),
            ("reducido en sal",          "Reducido en Sal"),
            ("contenido reducido de sal", "Contenido Reducido de Sal"),
            ("bajo en sal",              "Bajo en Sal"),
            ("sin sal añadida",          "Sin Sal Añadida"),
            ("sin nitritos añadidos",    "Sin Nitritos Añadidos"),
            ("sin nitritos",             "Sin Nitritos"),
            ("sin conservantes añadidos","Sin Conservantes Añadidos"),
            ("sin fosfatos añadidos",    "Sin Fosfatos Añadidos"),
            ("sin fosfatos",             "Sin Fosfatos"),
            ("sin azúcares añadidos",    "Sin Azúcares Añadidos"),
            ("calidad extra",            "Calidad Extra"),
            ("braseada",                 "Braseada"),
            ("braseado",                 "Braseado"),
            ("rico en colágeno",         "Rico en Colágeno"),
            ("bajo en calorías",         "Bajo en Calorías"),
            ("receta mejorada",          "Receta Mejorada"),
            ("sabor auténtico",          "Sabor Auténtico"),
        ]
        seen = set()
        for kw, label in NUTRI_KWS:
            if kw in todo and label not in seen:
                nutri_claims.append(label)
                seen.add(label)
        if nutri_claims:
            claim_nutricional = " / ".join(nutri_claims)

        # ── Claim 3: Proteínas ── Formato Excel: "21,5g Alto en Proteínas"
        claim_proteinas = None
        for kw, label in [("alto en proteínas", "Alto en Proteínas"),
                           ("fuente de proteínas", "Fuente de Proteínas"),
                           ("rico en proteínas", "Rico en Proteínas")]:
            if kw in todo:
                # Intentar incluir el valor en gramos antes del claim
                m_prot = re.search(r"(\d+[\.,]\d+)\s*g\s*" + kw, todo)
                if m_prot:
                    claim_proteinas = f"{m_prot.group(1)}g {label}"
                else:
                    claim_proteinas = label
                break

        # ── Claim 4: Grasa ── Formato Excel: "Bajo en Grasa"
        claim_grasa = None
        for kw, label in [("bajo en grasa", "Bajo en Grasa"),
                           ("bajo en grasas saturadas", "Bajo en Grasas Saturadas"),
                           ("reducido en grasa", "Reducido en Grasa"),
                           ("sin grasa", "Sin Grasa")]:
            if kw in todo:
                claim_grasa = label
                break

        # ── Claim 5: Sellos / Certificaciones ──
        # Formato Excel: "Bienestar Animal (AENOR)", "50% Raza Duroc / Bienestar Animal (AENOR)", "Gran Reserva 15 meses"
        claim_sellos = None
        sellos = []
        if "gran reserva" in todo:
            # Detectar meses de curación si aparecen
            m_gr = re.search(r"gran reserva\s+(\d+)\s*meses", todo)
            sellos.append(f"Gran Reserva {m_gr.group(1)} meses" if m_gr else "Gran Reserva")
        if "50% raza duroc" in todo or "raza duroc" in todo:
            sellos.append("50% Raza Duroc")
        if "bienestar animal" in todo:
            sellos.append("Bienestar Animal (AENOR)" if "aenor" in todo else "Bienestar Animal")
        if "ifs" in todo:
            sellos.append("IFS")
        if "brc" in todo:
            sellos.append("BRC")
        if "elaborado en españa" in todo:
            sellos.append("Elaborado en España")
        if sellos:
            claim_sellos = " / ".join(sellos)

        # ── Claim 6: Gama ── Formato: "Delizias Asados", "Delizias Finas", "Grand Bouquet"
        claim_gama = None
        for kw, label in [("delizias asados", "Delizias Asados"), ("delizias finas", "Delizias Finas"),
                           ("delizias al corte", "Delizias Al Corte"), ("grand bouquet", "Grand Bouquet"),
                           ("delipro", "Delipro"), ("gama premium", "Premium")]:
            if kw in todo:
                claim_gama = label
                break

        # ── Claim 7: Selección ── (método preparación, raza, calidad)
        # Formato Excel: "Asado al Horno", "Premium", "50% Raza Ibérica", "Ibérico", "Selección Especial"
        claim_seleccion = None
        for kw, label in [
            ("selección especial",  "Selección Especial"),
            ("gran selección",      "Gran Selección"),
            ("50% raza ibérica",    "50% Raza Ibérica"),
            ("raza ibérica",        "Raza Ibérica"),
            ("ibérico",             "Ibérico"),
            ("asado al horno",      "Asado al Horno"),
            ("premium",             "Premium"),
            ("calidad extra",       "Calidad Extra"),
        ]:
            if kw in todo:
                claim_seleccion = label
                break

        # ── Claim 8: Conveniencia ──
        # Formato Excel: "Listo en 4 min"
        claim_conveniencia = None
        conv_parts = []
        m_min = re.search(r"listo en\s+(\d+)\s*min", todo)
        if m_min:
            conv_parts.append(f"Listo en {m_min.group(1)} min")
        for kw, label in [("fácil apertura", "Fácil Apertura"), ("resellable", "Resellable"),
                           ("para llevar", "Para Llevar"), ("listo para comer", "Listo Para Comer")]:
            if kw in todo:
                conv_parts.append(label)
        if conv_parts:
            claim_conveniencia = " / ".join(conv_parts)

        # ── Claim 9: Raciones ──
        # Formato Excel: "2 raciones"
        claim_raciones = None
        m2 = re.search(r"(\d+)\s*raci[oó]n(?:es)?", todo)
        if m2:
            claim_raciones = m2.group(0).strip()

        # ── Claim 10: Modo Cocción ──
        # Formato Excel: "Asado al Horno", "Cocina Fácil Como en Casa / Cocinado a Baja Temperatura"
        claim_modo_coccion = None
        coccion_parts = []
        for kw, label in [
            ("cocina fácil como en casa", "Cocina Fácil Como en Casa"),
            ("cocinado a baja temperatura", "Cocinado a Baja Temperatura"),
            ("asado al horno",          "Asado al Horno"),
            ("vuelta y vuelta",          "Vuelta y Vuelta"),
            ("a la plancha",             "A la Plancha"),
            ("a la parrilla",            "A la Parrilla"),
            ("frío o caliente",          "Frío o Caliente"),
            ("al horno",                 "Al Horno"),
        ]:
            if kw in todo:
                coccion_parts.append(label)
                if len(coccion_parts) >= 2:
                    break
        if coccion_parts:
            claim_modo_coccion = " / ".join(coccion_parts)

        # Lista completa de claims (para compatibilidad)
        claims_lista = [c for c in [
            "Sin Gluten" if sin_gluten else None,
            "Sin Lactosa" if sin_lactosa else None,
            "Sin Colorantes" if sin_colorantes else None,
            "Sin Conservantes" if sin_conservantes else None,
            claim_nutricional, claim_proteinas, claim_grasa,
        ] if c]

        return {
            "sin_gluten": sin_gluten,
            "sin_lactosa": sin_lactosa,
            "sin_colorantes": sin_colorantes,
            "sin_conservantes": sin_conservantes,
            "claim_pct_carne": claim_pct_carne,
            "claim_nutricional": claim_nutricional,
            "claim_proteinas": claim_proteinas,
            "claim_grasa": claim_grasa,
            "claim_sellos": claim_sellos,
            "claim_gama": claim_gama,
            "claim_seleccion": claim_seleccion,
            "claim_conveniencia": claim_conveniencia,
            "claim_raciones": claim_raciones,
            "claim_modo_coccion": claim_modo_coccion,
            "claims_lista": claims_lista,
        }

    def _extraer_foto(self, page: Page) -> Optional[str]:
        try:
            el = page.query_selector("img.product-image, .wp-post-image, img.attachment-full, .product-img img")
            if el:
                return el.get_attribute("src")
        except Exception:
            pass
        return None

    def _extraer_tipo_carne(self, nombre: str, ingredientes: str) -> Optional[str]:
        texto = (nombre + " " + ingredientes).lower()
        if "ibérico" in texto or "iberico" in texto:
            return "Cerdo Ibérico"
        if "pavo" in texto:
            return "Pavo"
        if "pollo" in texto:
            return "Pollo"
        if "vacuno" in texto or "ternera" in texto or "vaca" in texto:
            return "Vacuno"
        if "cordero" in texto:
            return "Cordero"
        if "cerdo" in texto or "jamón" in texto or "lomo" in texto:
            return "Cerdo"
        if "mixto" in texto or "mixta" in texto:
            return "Mixto"
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
        # Usar el método experto de base_scraper que suma múltiples carnes
        return self.extraer_porcentaje_carne_de_ingredientes(ingredientes)
