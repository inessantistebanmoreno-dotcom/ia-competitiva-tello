# =============================================================================
# scrapers/ocr_extractor.py — Extracción de tablas nutricionales con EasyOCR
# Alternativa gratuita a Claude Vision para imágenes
# =============================================================================

import logging
import re
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# EasyOCR se inicializa una sola vez (carga el modelo ~500MB la primera vez)
_reader = None

def get_reader():
    global _reader
    if _reader is None:
        import ssl
        import easyocr
        # Desactivar verificación SSL para entornos corporativos
        ssl._create_default_https_context = ssl._create_unverified_context
        logger.info("[OCR] Inicializando EasyOCR...")
        _reader = easyocr.Reader(['es', 'en'], gpu=False)
        logger.info("[OCR] EasyOCR listo")
    return _reader


def extraer_nutricional_de_imagen(img_bytes: bytes) -> Dict:
    """
    Recibe bytes de una imagen (screenshot de tabla nutricional)
    y devuelve dict con los valores nutricionales extraídos.
    """
    try:
        reader = get_reader()
        resultados = reader.readtext(img_bytes, detail=0, paragraph=False)
        texto = " ".join(resultados)
        logger.debug(f"[OCR] Texto extraído: {texto[:200]}")
        return _parsear_nutricional(texto)
    except Exception as e:
        logger.warning(f"[OCR] Error extrayendo nutricional: {e}")
        return {}


def _normalizar_numero(texto: str) -> Optional[float]:
    """Convierte '18,4 g' → 18.4, '<0,5g' → 0.5"""
    if not texto:
        return None
    texto = re.sub(r"^[<>≤≥]\s*", "", str(texto).strip())
    texto = texto.replace(",", ".")
    match = re.search(r"\d[\d\.]*", texto)
    return float(match.group()) if match else None


def _parsear_nutricional(texto: str) -> Dict:
    """
    Parsea el texto OCR de una tabla nutricional estándar española.
    Busca patrones como "Energía 89 kcal", "Proteínas 18,4 g", "Sal 1,6 g", etc.
    """
    nutri = {}
    texto_lower = texto.lower()

    # ── Kcal ──
    # Busca "89 kcal" o "89kcal" o "Valor energético ... 89 kcal"
    m = re.search(r"(\d[\d,\.]+)\s*kcal", texto_lower)
    if m:
        nutri["kcal"] = _normalizar_numero(m.group(1))

    # ── Proteínas ──
    m = re.search(r"prote[ií]nas?\s*[:\-]?\s*([<>]?\d[\d,\.]*)\s*g", texto_lower)
    if m:
        nutri["proteinas_g"] = _normalizar_numero(m.group(1))

    # ── Grasas totales ──
    # Evitar confundir con grasas saturadas
    m = re.search(r"(?:grasas? totales?|l[ií]pidos?|materias? grasa)\s*[:\-]?\s*([<>]?\d[\d,\.]*)\s*g", texto_lower)
    if not m:
        # Fallback: "Grasas X g" donde X no viene precedido de "saturadas"
        m = re.search(r"\bgrasas?\s*[:\-]?\s*([<>]?\d[\d,\.]*)\s*g", texto_lower)
    if m:
        nutri["grasas_g"] = _normalizar_numero(m.group(1))

    # ── Grasas saturadas ──
    m = re.search(r"(?:saturadas?|[aá]cidos? grasos? saturados?)\s*[:\-]?\s*([<>]?\d[\d,\.]*)\s*g", texto_lower)
    if m:
        nutri["grasas_saturadas_g"] = _normalizar_numero(m.group(1))

    # ── Carbohidratos ──
    m = re.search(r"(?:hidratos? de carbono|carbohidratos?)\s*[:\-]?\s*([<>]?\d[\d,\.]*)\s*g", texto_lower)
    if m:
        nutri["carbohidratos_g"] = _normalizar_numero(m.group(1))

    # ── Azúcares ──
    m = re.search(r"az[uú]cares?\s*[:\-]?\s*([<>]?\d[\d,\.]*)\s*g", texto_lower)
    if m:
        nutri["azucares_g"] = _normalizar_numero(m.group(1))

    # ── Fibra ──
    m = re.search(r"fibra\s*(?:alimentaria|diet[eé]tica)?\s*[:\-]?\s*([<>]?\d[\d,\.]*)\s*g", texto_lower)
    if m:
        nutri["fibra_g"] = _normalizar_numero(m.group(1))

    # ── Sal ──
    m = re.search(r"\bsal\b\s*[:\-]?\s*([<>]?\d[\d,\.]*)\s*g", texto_lower)
    if m:
        nutri["sal_g"] = _normalizar_numero(m.group(1))

    logger.debug(f"[OCR] Nutricional parseado: {nutri}")
    return nutri
