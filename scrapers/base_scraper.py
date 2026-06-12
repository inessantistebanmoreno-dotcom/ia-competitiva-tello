# =============================================================================
# scrapers/base_scraper.py — Clase base para todos los scrapers
# =============================================================================

import base64
import json
import logging
import re
import time
from abc import ABC, abstractmethod
from typing import Dict, List, Optional

import anthropic
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

from config import (
    ANTHROPIC_API_KEY, CLAUDE_MODEL, CLAUDE_VISION_PROMPT,
    TIMEOUT_PAGINA_SEG, MAX_REINTENTOS,
)

logger = logging.getLogger(__name__)


class BaseScraper(ABC):
    """
    Clase base que proporciona:
    - Navegación con Playwright (modo headless)
    - Extracción por visión (Claude Vision API) para tablas en imagen
    - Normalización del JSON al esquema unificado
    """

    competidor_id: str  # "noel" | "campofrio" | "elpozo" | "argal"
    delay_entre_paginas: float = 2.0

    def __init__(self):
        self.claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # -----------------------------------------------------------------------
    # Métodos que DEBEN implementar las subclases
    # -----------------------------------------------------------------------

    @abstractmethod
    def obtener_urls_productos(self, page: Page) -> List[str]:
        """Navega el catálogo y devuelve la lista de URLs de producto."""
        ...

    @abstractmethod
    def extraer_producto(self, page: Page, url: str) -> Optional[Dict]:
        """
        Extrae los datos de una ficha de producto.
        Debe devolver un dict normalizado o None si hay error.
        """
        ...

    # -----------------------------------------------------------------------
    # Métodos compartidos
    # -----------------------------------------------------------------------

    def scrape(self) -> List[Dict]:
        """Ejecuta el ciclo completo: catálogo → fichas → lista de dicts normalizados."""
        resultados = []
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
            page.set_default_timeout(15000)  # 15 segundos máximo por página

            # 1. Obtener lista de URLs
            urls = self._con_reintentos(self.obtener_urls_productos, page)
            logger.info(f"[{self.competidor_id}] {len(urls)} URLs de producto encontradas")

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

        logger.info(f"[{self.competidor_id}] Scraping completado: {len(resultados)} productos")
        return resultados

    # -----------------------------------------------------------------------
    # Mistral Vision — enriquecimiento condicional
    # forzar=True  → siempre llama a Vision (scrapers tipo "vision", p.ej. El Pozo)
    # forzar=False → solo llama a Vision si el HTML no extrajo kcal
    #                (scrapers tipo "html" ya tienen tabla nutricional del DOM)
    # -----------------------------------------------------------------------

    def enriquecer_con_vision(self, page: "Page", datos: Dict, forzar: bool = False) -> Dict:
        """
        Ejecuta Mistral Vision sobre la imagen del packaging y fusiona con HTML.

        Estrategia de captura (en orden de prioridad):
        1. Imagen principal del producto (elemento img del packaging) — mayor detalle
        2. Screenshot de página completa — fallback si no hay imagen

        Reglas de fusión:
        - Nutricional: HTML tiene prioridad; Vision rellena nulls.
        - ingredientes / porcentaje_carne: Vision tiene prioridad (info del packaging).
        - claims: unión HTML + Vision (sin duplicados).
        - sin_gluten/sin_lactosa/sin_colorantes/sin_conservantes: derivados tanto de
          Vision como de la lista de claims fusionada.
        """
        # Para scrapers HTML (forzar=False), saltamos Vision si el HTML ya extrajo
        # los campos nutricionales básicos. Esto evita llamadas innecesarias a la API
        # que multiplican el tiempo de scraping por 10-20x.
        if not forzar:
            campos_nutri = ['kcal', 'proteinas_g', 'grasas_g', 'sal_g']
            if all(datos.get(c) is not None for c in campos_nutri):
                logger.debug(f"[vision] Omitido — datos nutricionales completos en HTML")
                return datos

        # Selectores comunes para la imagen principal de producto en las 4 webs
        SELECTORES_IMG = [
            ".product-image img", "img.product-main-image",
            ".product-img img", ".wp-post-image",
            "img[class*='product']", "img[class*='hero']",
            ".product-gallery img:first-child", "figure img",
        ]
        # Keywords para derivar booleanos desde la lista de claims de Vision
        # "sin aditivos" implica tanto sin colorantes como sin conservantes
        BOOL_CLAIMS = {
            'sin_gluten':      ['sin gluten', 'gluten free', 'apto celíac'],
            'sin_lactosa':     ['sin lactosa', 'lactose free'],
            'sin_colorantes':  ['sin colorante', 'sin aditivo'],
            'sin_conservantes':['sin conservante', 'sin aditivo'],
        }

        try:
            from scrapers.mistral_vision import extraer_nutricional_con_mistral, extraer_nutricional_de_screenshot

            vision = {}

            # Intento 1: descargar la URL de la foto del producto directamente
            # (máxima calidad — Mistral ve el packaging real, no un screenshot de web)
            url_foto = datos.get('url_foto')
            if url_foto:
                try:
                    response = page.request.get(url_foto)
                    if response.ok:
                        img_bytes = response.body()
                        if img_bytes and len(img_bytes) > 5000:
                            vision = extraer_nutricional_con_mistral(img_bytes) or {}
                            if vision:
                                logger.debug(f"[vision] Captura por url_foto: {url_foto[:60]}")
                except Exception as e:
                    logger.debug(f"[vision] url_foto fetch falló: {e}")

            # Intento 2: screenshot del elemento img del producto en la página
            if not vision:
                for sel in SELECTORES_IMG:
                    try:
                        el = page.query_selector(sel)
                        if el:
                            img_bytes = el.screenshot()
                            if img_bytes and len(img_bytes) > 5000:
                                vision = extraer_nutricional_con_mistral(img_bytes) or {}
                                if vision:
                                    logger.debug(f"[vision] Captura por selector: {sel}")
                                    break
                    except Exception:
                        continue

            # Intento 3: screenshot de página completa (último recurso)
            if not vision:
                vision = extraer_nutricional_de_screenshot(page) or {}

            if not vision:
                return datos

            # ── Nutricional: rellenar nulls con Vision ──
            for campo in ('kcal', 'proteinas_g', 'grasas_g', 'grasas_saturadas_g',
                          'carbohidratos_g', 'azucares_g', 'fibra_g', 'sal_g'):
                if datos.get(campo) is None and vision.get(campo) is not None:
                    datos[campo] = vision[campo]

            # ── Ingredientes ──
            if not datos.get('ingredientes') and vision.get('ingredientes'):
                datos['ingredientes'] = vision['ingredientes']
                datos['alergenos'] = self.normalizar_alergenos(datos['ingredientes'])

            # ── % carne: Vision tiene prioridad (claim visual del packaging) ──
            if vision.get('porcentaje_carne'):
                datos['porcentaje_carne'] = vision['porcentaje_carne']

            # ── Claims: unión HTML + Vision (dedup case-insensitive) ──
            claims_html   = datos.get('claims') or []
            claims_vision = vision.get('claims') or []
            if claims_vision:
                seen_lc = set()
                merged = []
                for c in claims_html + claims_vision:
                    k = (c or '').lower().strip()
                    if k and k not in seen_lc:
                        seen_lc.add(k)
                        merged.append(c)
                datos['claims'] = merged

            # ── Booleanos: derivar de Vision directo O de la lista de claims ──
            claims_texto = ' '.join(c.lower() for c in (datos.get('claims') or []))
            for campo, palabras in BOOL_CLAIMS.items():
                if not datos.get(campo):
                    # Primero: campo booleano devuelto directamente por Vision
                    if vision.get(campo):
                        datos[campo] = True
                    # Segundo: buscar keywords en la lista de claims de Vision
                    elif any(p in claims_texto for p in palabras):
                        datos[campo] = True

            logger.debug(f"[vision] Enriquecido: %carne={datos.get('porcentaje_carne')} "
                         f"sin_gluten={datos.get('sin_gluten')} "
                         f"claims={len(datos.get('claims', []))}")
        except Exception as e:
            logger.debug(f"[vision] enriquecer_con_vision falló: {e}")

        return datos

    # -----------------------------------------------------------------------
    # Claude Vision: extrae datos cuando la tabla nutricional es una imagen
    # -----------------------------------------------------------------------

    def extraer_por_vision(self, page: Page, selector_imagen: Optional[str] = None) -> Dict:
        """
        Captura screenshot del elemento (o página completa) y lo manda a Claude Vision.
        Devuelve el dict con los campos nutricionales extraídos.
        """
        if selector_imagen:
            elemento = page.query_selector(selector_imagen)
            if elemento:
                img_bytes = elemento.screenshot()
            else:
                logger.warning(f"Selector '{selector_imagen}' no encontrado, capturando página completa")
                img_bytes = page.screenshot(full_page=True)
        else:
            img_bytes = page.screenshot(full_page=True)

        img_b64 = base64.standard_b64encode(img_bytes).decode("utf-8")

        respuesta = self.claude.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": img_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": CLAUDE_VISION_PROMPT,
                    },
                ],
            }],
        )

        texto = respuesta.content[0].text.strip()
        # Limpiar posible markdown de Claude
        texto = re.sub(r"^```(?:json)?\s*", "", texto)
        texto = re.sub(r"\s*```$", "", texto)

        try:
            return json.loads(texto)
        except json.JSONDecodeError:
            logger.error(f"Claude Vision devolvió JSON inválido: {texto[:200]}")
            return {}

    # -----------------------------------------------------------------------
    # Helpers de normalización
    # -----------------------------------------------------------------------

    @staticmethod
    def normalizar_numero(texto: str) -> Optional[float]:
        """Convierte '18,4 g' → 18.4, '<0,5g' → 0.5, '1.900 kJ' → ignora kJ"""
        if not texto:
            return None
        texto = str(texto).strip()
        # Eliminar prefijo "<" o ">" (menos/más de X → usar X como aproximación)
        texto = re.sub(r"^[<>≤≥]\s*", "", texto)
        # Reemplazar coma decimal europea por punto
        texto = texto.replace(",", ".")
        match = re.search(r"\d[\d\.]*", texto)
        return float(match.group()) if match else None

    @staticmethod
    def _inferir_categoria_por_nombre(nombre: str) -> Optional[str]:
        """
        Clasifica un producto de charcutería en una de las categorías estándar
        a partir de su nombre. Normaliza texto (sin tildes, minúsculas) antes de comparar.

        Categorías: Chorizo y salchichón | Cocidos | Fuet y longaniza | Ibéricos |
                    Jamón cocido | Jamón y Lomo Curado | Mortadela y chopped |
                    Patés | Pavo y pollo | Platos preparados | Salchichas | Snacks
        """
        if not nombre:
            return None

        import unicodedata
        def norm(s):
            s = s.lower()
            return ''.join(c for c in unicodedata.normalize('NFD', s)
                           if unicodedata.category(c) != 'Mn')

        n = norm(nombre)

        # 0a. PATÉS — antes que ibéricos (un "paté ibérico" es un paté, no un ibérico)
        if any(x in n for x in ["pate","paté","sobrasada"]):
            return "Patés"

        # 0b. SNACKS — antes que embutidos (un "snack de chorizo" es un snack, no chorizo)
        if any(x in n for x in ["snack","bocadito","tapas fuet","tapas chorizo",
                                  "fuet & bread","mini fuet","mini chorizo","cubo mini fuets",
                                  "pintxo","tabla de"]):
            return "Snacks"

        # 1. IBÉRICOS — antes que jamón/lomo para capturar "jamón ibérico", "lomo ibérico"
        if any(x in n for x in ["iberico","jamon de cebo de campo","paleta de cebo","paleta cebo",
                                  "jamon de bellota","cebo de campo iberico","50% raza iberica",
                                  "100% iberica","lomo iberico","chorizo iberico","salchichon iberico",
                                  "fuet iberico"]):
            return "Ibéricos"

        # 2. JAMÓN COCIDO — jamón cocido específicamente
        if any(x in n for x in ["jamon cocido","paleta cocida","fiambre de jamon","fiambre york",
                                  "jamon moldeado","jamon asado al horno","jamon extra","jamon reserva",
                                  "jamon gran reserva","lacón"]):
            return "Jamón cocido"

        # 3. PAVO Y POLLO — pechuga de pavo/pollo, fiambres de ave
        if any(x in n for x in ["pechuga de pavo","pechuga de pollo","fiambre de pavo",
                                  "fiambre de pollo","jamon de pavo","jamon curado de pavo",
                                  "centros de pavo","pechuguita","superpavo","ragut pavo",
                                  "chuleta de pavo","filete pechuga de pavo","canal de pavo",
                                  "pollo asado","pechuguita de pollo","canal de pollo",
                                  "tiras de pechuga","alitas","cuartos traseros","muslo"]):
            return "Pavo y pollo"

        # 4. JAMÓN Y LOMO CURADO — jamón serrano, lomo curado, paleta curada
        if any(x in n for x in ["jamon serrano","jamón serrano","lomo curado","lomo embuchado",
                                  "lomo de extremadura","cabeza de lomo curado","paleta curada",
                                  "jamon estirpe","jamon gran estirpe","pernil","jamon premier",
                                  "jamon reserva","center jamon","jamon deshuesado extratierno"]):
            return "Jamón y Lomo Curado"

        # 5. CHORIZO Y SALCHICHÓN — chorizo y salchichón no ibérico
        if any(x in n for x in ["chorizo","salchichon","salchichón"]):
            return "Chorizo y salchichón"

        # 6. FUET Y LONGANIZA
        if any(x in n for x in ["fuet","longaniza","espetec","chistorra"]):
            return "Fuet y longaniza"

        # 7. MORTADELA Y CHOPPED
        if any(x in n for x in ["mortadela","chopped"]):
            return "Mortadela y chopped"

        # 8. SALCHICHAS — frankfurt, viena, bratwurst, hot dog
        if any(x in n for x in ["frankfurt","salchicha","hot dog","hotdog","bratwurst",
                                  "bockwurst","viena","king upp","bocata club","burger con pechuga",
                                  "tripack frankfurt"]):
            return "Salchichas"

        # 9. BOCATA CLUB — formato bocata (salchicha/snack)
        if "bocata club" in n:
            return "Snacks"

        # 11. PLATOS PREPARADOS
        if any(x in n for x in ["tortilla","ensalada","gazpacho","salmorejo","paella","macarrones",
                                  "lasana","risotto","arroz tres delicias","espagheti","espagueti",
                                  "fideuá","fideuà","hummus","yakisoba","caldo","pasta box",
                                  "tallarines","berenjenas rellenas","cocktail de gambas",
                                  "pollo asado relleno","costillas de cerdo con salsa",
                                  "puntas de costilla","codillo","roulada","secreto marinado",
                                  "pluma marinada","pastel de carne","pulled pork",
                                  "croquetas","nuggets","rolling","bocata club"]):
            return "Platos preparados"

        # 12. COCIDOS — resto de cocidos (paleta, fiambres genéricos, bacon cocido)
        if any(x in n for x in ["bacon","panceta","fiambre","paleta","lacón",
                                  "codillo","roti","rotí","rôti","burger","hamburguesa",
                                  "albondigas","albóndigas","picada"]):
            return "Cocidos"

        return None

    @staticmethod
    def extraer_porcentaje_carne_de_ingredientes(ingredientes: str) -> Optional[float]:
        """
        Extrae el % de carne real de la lista de ingredientes.

        REGLA: El porcentaje entre paréntesis inmediatamente después del ingrediente
        cárnico representa el % real de carne en el producto.
        Si hay múltiples carnes, suma sus porcentajes.

        Ejemplos:
          "Jamón de cerdo (93%), agua, sal..."          → 93.0
          "Pechuga de pollo (99%), sal..."              → 99.0
          "Carne de cerdo (50%), carne de vacuno (35%)" → 85.0  (suma)
          "Pechuga de pavo (60%), agua (20%), almidón (5%)" → 60.0  (solo la carne)
        """
        if not ingredientes:
            return None

        # ── Patrón front-of-pack: "92% CARNE" o "CARNE 92%" ──
        # Aparece como claim visual, no en la lista de ingredientes
        fop = re.search(
            r'(\d+[\.,]?\d*)\s*%\s*carne\b|carne\s*(\d+[\.,]?\d*)\s*%',
            ingredientes.lower()
        )
        if fop:
            pct = fop.group(1) or fop.group(2)
            try:
                val = float(pct.replace(',', '.'))
                if 0 < val <= 100:
                    return round(val, 1)
            except ValueError:
                pass

        # Palabras que identifican ingredientes CÁRNICOS
        CARNES = [
            'jamón', 'jamon', 'pechuga', 'paleta', 'lomo', 'lacón', 'lacon',
            'carne de cerdo', 'carne de vacuno', 'carne de pollo', 'carne de pavo',
            'carne de cordero', 'carne ibérica', 'carne de cebo',
            'cerdo ibérico', 'cerdo', 'pollo', 'pavo', 'vacuno', 'ternera',
            'cordero', 'ibérico', 'iberico', 'bacon', 'panceta', 'costilla',
            'magro', 'solomillo', 'secreto', 'pluma', 'presa', 'carrillada',
            'morcillo', 'aguja', 'contramuslo', 'muslo', 'ragout', 'ragút',
            'pernil', 'filete', 'escalopín', 'butifarra', 'longaniza',
        ]

        # Palabras que NO son carne aunque lleven porcentaje
        NO_CARNE = [
            'agua', 'sal', 'azúcar', 'azucar', 'almidón', 'almidon',
            'fécula', 'fecula', 'proteína vegetal', 'proteina vegetal',
            'fibra vegetal', 'fibra', 'glucosa', 'dextrosa', 'lactosa',
            'leche', 'aceite', 'especias', 'aroma', 'extracto', 'vinagre',
            'vino', 'ajo', 'cebolla', 'tomate', 'pimentón', 'pimenton',
            'gelatina', 'carragenano', 'carragenina', 'trufa', 'queso',
            'mantequilla', 'nata', 'huevo', 'harina', 'pan',
        ]

        texto = ingredientes.lower()
        total_carne = 0.0
        encontrado = False

        # Buscar pares: nombre_ingrediente (XX%)
        # El nombre puede contener porcentajes intermedios como "50% raza duroc"
        patron = re.finditer(
            r'([a-záéíóúüñ\s\-\/\d%]+?)\s*\(\s*(\d+[\.,]?\d*)\s*%\s*\)',
            texto
        )

        for match in patron:
            nombre = match.group(1).strip()
            pct_str = match.group(2).replace(',', '.')

            # Descartar si es un no-cárnico conocido
            if any(nc in nombre for nc in NO_CARNE):
                continue

            # Aceptar si contiene alguna palabra cárnica
            if any(c in nombre for c in CARNES):
                try:
                    total_carne += float(pct_str)
                    encontrado = True
                except ValueError:
                    pass

        if encontrado and 0 < total_carne <= 100:
            return round(total_carne, 1)

        return None

    @staticmethod
    def analizar_ingredientes(ingredientes: str) -> Optional[dict]:
        """
        Clasifica los ingredientes de un producto cárnico por función real.
        Devuelve un dict con las categorías detectadas y los términos encontrados.
        Útil para detectar azúcares ocultos, rellenos, lácteos, etc.
        """
        if not ingredientes:
            return None

        texto = ingredientes.lower()

        MAPA = {
            "agua": [
                "agua", "agua de cocción", "caldo", "caldo de cocción",
                "salmuera", "caldo vegetal", "caldo de carne",
            ],
            "grasas": [
                "tocino", "grasa de cerdo", "grasa de pollo", "grasa de pavo",
                "grasa vegetal", "corteza", "manteca", "aceite de girasol",
                "aceite de oliva", "aceite vegetal", "grasa hidrogenada",
                "grasa de vacuno",
            ],
            "almidon_relleno": [
                "fécula de patata", "fécula de maíz", "fécula", "almidón",
                "almidón de patata", "almidón de maíz", "almidón modificado",
                "harina de arroz", "harina de trigo", "harina", "maltodextrina",
                "dextrina",
            ],
            "azucares": [
                "dextrosa", "glucosa", "jarabe de glucosa", "sacarosa",
                "azúcar", "azucar", "lactosa", "fructosa", "azúcar invertido",
                "azúcar de caña", "miel", "jarabe de maíz",
            ],
            "sal_sodio": [
                "sal", "cloruro sódico", "sal marina", "sal de potasio",
                "cloruro potásico", "nitrito sódico", "nitrato sódico",
                "nitrito potásico", "nitrato potásico",
            ],
            "lacteos": [
                "lactosa", "leche en polvo", "proteínas de la leche",
                "caseinato sódico", "caseinato", "suero de leche",
                "nata", "mantequilla", "queso", "proteína láctea",
            ],
            "conservadores": [
                "nitrito sódico", "nitrato sódico", "nitrito potásico",
                "nitrato potásico", "lactato potásico", "lactato sódico",
                "acetato sódico", "ácido láctico", "ácido acético",
                "eritorbato sódico", "ascorbato sódico", "ácido ascórbico",
                "etil lauroil arginato",
            ],
            "estabilizantes_ligantes": [
                "tripolifosfato sódico", "trifosfato", "difosfato",
                "polifosfato", "carragenano", "carragenanos", "carragenina",
                "goma xantana", "goma guar", "goma garrofín",
                "konjac", "gelatina", "sorbitol",
            ],
            "potenciadores_sabor": [
                "glutamato monosódico", "e-621", "e621",
                "guanilato disódico", "inosinato disódico",
                "extracto de levadura", "levadura",
            ],
            "aromas": [
                "aroma", "aroma natural", "aromas naturales",
                "aroma de humo", "humo líquido", "extracto de humo",
            ],
        }

        resultado = {}
        for categoria, terminos in MAPA.items():
            encontrados = [t for t in terminos if t in texto]
            if encontrados:
                # Eliminar substrings redundantes (ej. "fécula" si ya está "fécula de patata")
                sin_duplicados = []
                for t in encontrados:
                    if not any(t != t2 and t in t2 for t2 in encontrados):
                        sin_duplicados.append(t)
                if sin_duplicados:
                    resultado[categoria] = sin_duplicados

        return resultado if resultado else None

    # -----------------------------------------------------------------------
    # Extractor universal de claims de packaging (50+ claims, 5 categorías)
    # -----------------------------------------------------------------------

    @staticmethod
    def extraer_claims_completos(texto_pagina: str, ingredientes: str = "") -> Dict:
        """
        Extrae TODOS los claims de packaging de una página de producto.
        Cubre 5 categorías: nutrición, proceso, certificaciones/sellos,
        ingredientes, gama/posicionamiento.

        Uso en scrapers:
            def _extraer_claims_detallados(self, page, ingredientes):
                try: todo = page.inner_text("body")
                except: todo = ""
                return self.extraer_claims_completos(todo, ingredientes)
        """
        todo = texto_pagina.lower() if texto_pagina else ""
        ingr = ingredientes.lower() if ingredientes else ""

        # ── Catálogo de claims: etiqueta → lista de keywords (minúsculas, sin tildes aceptadas) ──
        # Para cada entry: si CUALQUIER keyword aparece en el texto, se detecta el claim.

        CLAIMS_NUTRICION = {
            "Alto en proteínas":        ["alto en proteínas", "alto en proteinas",
                                         "alto contenido en proteínas", "rico en proteínas"],
            "Fuente de proteínas":      ["fuente de proteínas", "fuente de proteinas"],
            "Rico en colágeno":         ["rico en colágeno", "rico en colageno",
                                         "fuente de colágeno", "colágeno natural", "colageno natural"],
            "Bajo en calorías":         ["bajo en calorías", "bajo en calorias",
                                         "light", "ligero", "reducido en calorías"],
            "Alto en fibra":            ["alto en fibra", "rico en fibra", "fuente de fibra"],
            "Bajo en grasas":           ["bajo en grasa", "bajo en grasas",
                                         "bajo contenido en grasa", "reducido en grasas"],
            "Bajo en grasas saturadas": ["bajo en grasas saturadas", "reducido en grasas saturadas"],
            "Sin azúcares añadidos":    ["sin azúcares añadidos", "sin azucares añadidos",
                                         "sin azúcar añadida", "sin azucar añadida"],
            "Reducido en sal":          ["reducido en sal", "reducida en sal",
                                         "bajo en sal", "bajo contenido en sal", "menos sal"],
            "Sin sodio":                ["sin sodio", "muy bajo en sodio"],
            "Fuente de calcio":         ["fuente de calcio", "rico en calcio"],
            "Fuente de hierro":         ["fuente de hierro", "rico en hierro"],
            "Fuente de vitaminas":      ["fuente de vitamina", "rico en vitaminas",
                                         "vitaminas naturales", "fuente de vitaminas"],
            "Sin grasas trans":         ["sin grasas trans", "0% grasas trans", "0 grasas trans"],
        }

        CLAIMS_PROCESO = {
            "Sin nitritos añadidos":    ["sin nitritos añadidos", "sin nitratos añadidos",
                                         "sin nitritos ni nitratos añadidos"],
            "Sin nitritos":             ["sin nitritos", "libre de nitritos", "nitritos: no"],
            "Sin fosfatos añadidos":    ["sin fosfatos añadidos"],
            "Sin fosfatos":             ["sin fosfatos"],
            "Sin conservantes":         ["sin conservantes", "sin conservantes añadidos",
                                         "sin conservantes artificiales", "0 conservantes"],
            "Sin colorantes":           ["sin colorantes", "sin colorantes añadidos",
                                         "sin colorantes artificiales", "0 colorantes"],
            "Sin aditivos":             ["sin aditivos", "sin aditivos artificiales",
                                         "0 aditivos", "sin e-"],
            "Sin gluten":               ["sin gluten", "apto celíacos", "apto para celíacos",
                                         "libre de gluten"],
            "Sin lactosa":              ["sin lactosa", "libre de lactosa", "apto intolerantes lactosa"],
            "Sin sal añadida":          ["sin sal añadida", "sin sal añadida", "sin sal adicional"],
            "Sin azúcar añadida":       ["sin azúcar añadida", "sin azucar añadido"],
            "Asado al horno":           ["asado al horno", "horneado"],
            "Braseado":                 ["braseado", "a la brasa"],
            "Cocido al vapor":          ["cocido al vapor", "al vapor"],
            "Cocinado a baja temperatura": ["cocinado a baja temperatura", "baja temperatura",
                                            "cocción lenta", "slow cooking"],
            "Curación natural":         ["curación natural", "maduración natural",
                                         "curado naturalmente", "curación lenta"],
            "Receta tradicional":       ["receta tradicional", "elaboración tradicional",
                                         "método tradicional", "receta artesana"],
            "Cocido en su jugo":        ["cocido en su jugo", "en su propio jugo"],
            "Ahumado natural":          ["ahumado natural", "ahumado con leña", "humo natural"],
        }

        CLAIMS_CERTIFICACIONES = {
            "Bienestar Animal (AENOR)": ["bienestar animal (aenor)"],
            "Bienestar Animal":         ["bienestar animal"],
            "100% Raza Duroc":          ["100% raza duroc"],
            "50% Raza Duroc":           ["50% raza duroc"],
            "Cruce Duroc":              ["cruce duroc"],
            "Raza Duroc":               ["raza duroc"],
            "Ibérico":                  ["ibérico", "iberico", "raza ibérica", "raza iberica"],
            "Denominación de Origen":   ["denominación de origen", "denominacion de origen",
                                         "d.o.p.", "d.o. protegida", "igp", "i.g.p."],
            "Ecológico":                ["ecológico", "ecologico", "producto ecológico",
                                         "certificado ecológico", "orgánico"],
            "Bio":                      [" bio ", "100% bio", "agricultura ecológica"],
            "Halal":                    ["halal"],
            "Kosher":                   ["kosher"],
            "Criado en libertad":       ["criado en libertad", "en libertad", "pasto libre",
                                         "free range", "vida en libertad"],
            "Sin OGM":                  ["sin ogm", "sin transgénicos", "no ogm",
                                         "libre de ogm"],
            "Elaborado en España":      ["elaborado en españa", "made in spain",
                                         "producto español", "industria española"],
            "Gran Reserva":             ["gran reserva"],
            "Reserva":                  ["reserva"],
            "IFS / BRC":                ["ifs food", "brc food"],
            "Km 0 / Producto local":    ["km 0", "km0", "producto local", "de origen local"],
        }

        CLAIMS_GAMA = {
            "BonNatur":          ["bonnatur", "bon natur"],
            "Oliving":           ["oliving"],
            "Premier":           ["premier"],
            "Delizias":          ["delizias"],
            "Grand Bouquet":     ["grand bouquet"],
            "Delipro":           ["delipro"],
            "Naturarte":         ["naturarte"],
            "Vegalia":           ["vegalia"],
            "Cuida-T":           ["cuida-t", "cuidat"],
            "Finissimas":        ["finissimas"],
            "SnackIn":           ["snackin"],
            "Calidad Extra":     ["calidad extra"],
            "Premium":           ["premium"],
            "Gourmet":           ["gourmet"],
            "Artesano":          ["artesano", "artesanal"],
            "Selección":         ["selección", "seleccion", "gran selección",
                                  "selección especial", "selección del maestro"],
            "100% natural":      ["100% natural", "100 % natural"],
            "1954":              ["desde 1954", "1954"],
        }

        # ── Detectar todos los claims activos ──
        claims_detectados: list = []

        for catalogo in [CLAIMS_NUTRICION, CLAIMS_PROCESO, CLAIMS_CERTIFICACIONES, CLAIMS_GAMA]:
            for etiqueta, keywords in catalogo.items():
                if any(kw in todo for kw in keywords):
                    # Evitar añadir versiones redundantes: si ya está "Bienestar Animal (AENOR)"
                    # no añadir también "Bienestar Animal"
                    redundante = False
                    if etiqueta == "Bienestar Animal" and "Bienestar Animal (AENOR)" in claims_detectados:
                        redundante = True
                    if etiqueta == "Sin nitritos" and "Sin nitritos añadidos" in claims_detectados:
                        redundante = True
                    if etiqueta == "Raza Duroc" and any(
                            x in claims_detectados for x in ["50% Raza Duroc", "100% Raza Duroc", "Cruce Duroc"]):
                        redundante = True
                    if etiqueta == "Reserva" and "Gran Reserva" in claims_detectados:
                        redundante = True
                    if not redundante:
                        claims_detectados.append(etiqueta)

        # ── Campos estructurados derivados ──
        # "Sin aditivos" es más amplio: implica también sin colorantes y sin conservantes
        sin_aditivos     = "Sin aditivos" in claims_detectados
        sin_gluten       = "Sin gluten" in claims_detectados
        sin_lactosa      = "Sin lactosa" in claims_detectados
        sin_colorantes   = "Sin colorantes" in claims_detectados or sin_aditivos
        sin_conservantes = "Sin conservantes" in claims_detectados or sin_aditivos

        # % de carne en texto
        claim_pct_carne = None
        m = re.search(r"(\d+[\.,]?\d*)\s*%\s*(?:de\s+)?carne", todo)
        if m:
            claim_pct_carne = m.group(0).strip().title()

        # Claim nutricional consolidado
        nutri_claims = [c for c in claims_detectados
                        if c in ("Reducido en sal", "Sin sodio", "Sin azúcares añadidos",
                                 "Bajo en grasas", "Bajo en grasas saturadas",
                                 "Sin grasas trans", "Bajo en calorías")]
        claim_nutricional = " / ".join(nutri_claims) if nutri_claims else None

        # Claim proteínas
        prot_claims = [c for c in claims_detectados
                       if c in ("Alto en proteínas", "Fuente de proteínas", "Rico en colágeno",
                                "Bajo en calorías", "Alto en fibra", "Fuente de vitaminas")]
        claim_proteinas = prot_claims[0] if prot_claims else None

        # Claim grasa
        grasa_claims = [c for c in claims_detectados
                        if c in ("Bajo en grasas", "Bajo en grasas saturadas", "Sin grasas trans")]
        claim_grasa = grasa_claims[0] if grasa_claims else None

        # Claim sellos
        sello_claims = [c for c in claims_detectados
                        if c in ("Bienestar Animal (AENOR)", "Bienestar Animal", "Raza Duroc",
                                 "50% Raza Duroc", "100% Raza Duroc", "Ibérico",
                                 "Denominación de Origen", "Ecológico", "Bio", "Halal", "Kosher",
                                 "Gran Reserva", "Reserva", "Criado en libertad", "Sin OGM",
                                 "Elaborado en España", "IFS / BRC")]
        claim_sellos = " / ".join(sello_claims) if sello_claims else None

        # Claim gama
        gama_claims = [c for c in claims_detectados
                       if c in ("BonNatur", "Oliving", "Premier", "Delizias", "Grand Bouquet",
                                "Delipro", "Naturarte", "Vegalia", "Cuida-T", "Finissimas",
                                "SnackIn", "1954")]
        claim_gama = gama_claims[0] if gama_claims else None

        # Claim selección
        sel_claims = [c for c in claims_detectados
                      if c in ("Calidad Extra", "Premium", "Gourmet", "Artesano",
                               "Selección", "100% natural")]
        claim_seleccion = sel_claims[0] if sel_claims else None

        # Conveniencia
        conv_parts = []
        m_min = re.search(r"listo en\s+(\d+)\s*min", todo)
        if m_min:
            conv_parts.append(f"Listo en {m_min.group(1)} min")
        for kw, label in [("fácil apertura", "Fácil Apertura"),
                          ("facil apertura", "Fácil Apertura"),
                          ("resellable", "Resellable"),
                          ("listo para comer", "Listo Para Comer"),
                          ("para llevar", "Para Llevar")]:
            if kw in todo:
                conv_parts.append(label)
        claim_conveniencia = " / ".join(dict.fromkeys(conv_parts)) if conv_parts else None

        # Raciones
        claim_raciones = None
        m2 = re.search(r"(\d+)\s*raci[oó]n(?:es)?", todo)
        if m2:
            claim_raciones = m2.group(0).strip()

        # Modo cocción
        coccion_parts = []
        for kw, label in [
            ("cocina fácil como en casa", "Cocina Fácil Como en Casa"),
            ("cocina facil como en casa", "Cocina Fácil Como en Casa"),
            ("cocinado a baja temperatura", "Cocinado a Baja Temperatura"),
            ("asado al horno",   "Asado al Horno"),
            ("braseado",         "Braseado"),
            ("a la plancha",     "A la Plancha"),
            ("a la parrilla",    "A la Parrilla"),
            ("cocido al vapor",  "Cocido al Vapor"),
            ("al horno",         "Al Horno"),
            ("frío o caliente",  "Frío o Caliente"),
            ("frio o caliente",  "Frío o Caliente"),
        ]:
            if kw in todo and label not in coccion_parts:
                coccion_parts.append(label)
                if len(coccion_parts) >= 2:
                    break
        claim_modo_coccion = " / ".join(coccion_parts) if coccion_parts else None

        return {
            "sin_gluten":          sin_gluten,
            "sin_lactosa":         sin_lactosa,
            "sin_colorantes":      sin_colorantes,
            "sin_conservantes":    sin_conservantes,
            "claim_pct_carne":     claim_pct_carne,
            "claim_nutricional":   claim_nutricional,
            "claim_proteinas":     claim_proteinas,
            "claim_grasa":         claim_grasa,
            "claim_sellos":        claim_sellos,
            "claim_gama":          claim_gama,
            "claim_seleccion":     claim_seleccion,
            "claim_conveniencia":  claim_conveniencia,
            "claim_raciones":      claim_raciones,
            "claim_modo_coccion":  claim_modo_coccion,
            "claims_lista":        claims_detectados,
        }

    @staticmethod
    def normalizar_alergenos(texto: str) -> List[str]:
        """
        Detecta alérgenos mencionados en el texto de ingredientes
        y los devuelve como lista normalizada.
        """
        mapa = {
            "gluten":       ["gluten", "trigo", "centeno", "cebada", "avena", "espelta"],
            "lactosa":      ["leche", "lactosa", "suero de leche", "caseína"],
            "huevo":        ["huevo"],
            "soja":         ["soja", "soya"],
            "frutos_secos": ["frutos de cáscara", "almendra", "avellana", "nuez", "cacahuete"],
            "apio":         ["apio"],
            "mostaza":      ["mostaza"],
            "sesamo":       ["sésamo", "sesamo"],
            "sulfitos":     ["sulfitos", "dióxido de azufre"],
            "moluscos":     ["moluscos"],
            "crustaceos":   ["crustáceos"],
            "pescado":      ["pescado"],
        }
        texto_lower = texto.lower()
        encontrados = []
        for alergeno, palabras in mapa.items():
            if any(p in texto_lower for p in palabras):
                encontrados.append(alergeno)
        return encontrados

    # -----------------------------------------------------------------------
    # Reintento ante errores de red
    # -----------------------------------------------------------------------

    def _con_reintentos(self, fn, *args, **kwargs):
        for intento in range(1, MAX_REINTENTOS + 1):
            try:
                return fn(*args, **kwargs)
            except (PlaywrightTimeoutError, Exception) as e:
                if intento == MAX_REINTENTOS:
                    raise
                espera = intento * 5
                logger.warning(f"Reintento {intento}/{MAX_REINTENTOS} tras error: {e}. Esperando {espera}s")
                time.sleep(espera)
