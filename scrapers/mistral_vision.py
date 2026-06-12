# =============================================================================
# scrapers/mistral_vision.py — Extracción de tablas nutricionales con Mistral Vision
# Alternativa gratuita a Claude Vision para imágenes de etiquetas
# Modelo: pixtral-12b (visión nativa, gratuito con límites generosos)
# =============================================================================

import base64
import json
import logging
import os
import re
from typing import Dict, Optional

logger = logging.getLogger(__name__)

MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY", "")

PROMPT_NUTRICIONAL = """Eres un experto en etiquetado alimentario español. Analiza la imagen de este producto cárnico y extrae TODA la información visible.

Devuelve ÚNICAMENTE un JSON con esta estructura exacta (sin texto adicional):
{
  "kcal": <número o null>,
  "proteinas_g": <número o null>,
  "grasas_g": <número o null>,
  "grasas_saturadas_g": <número o null>,
  "carbohidratos_g": <número o null>,
  "azucares_g": <número o null>,
  "fibra_g": <número o null>,
  "sal_g": <número o null>,
  "porcentaje_carne": <número o null>,
  "ingredientes": "<texto completo de ingredientes o null>",
  "alergenos": ["<alergeno1>", ...],
  "claims": ["<claim1>", "<claim2>", ...]
}

Para el campo "claims", extrae TODOS los mensajes del packaging visibles en el envase o la web:
- Claims de NUTRICIÓN: "Rico en proteínas", "Fuente de proteínas", "Rico en colágeno", "Bajo en calorías", "Alto en fibra", "Bajo en grasas", "Reducido en sal", "Sin azúcares añadidos", "Sin grasas trans", "Fuente de calcio", "Fuente de hierro", "Fuente de vitaminas"
- Claims de PROCESO: "Sin nitritos añadidos", "Sin nitritos", "Sin fosfatos añadidos", "Sin fosfatos", "Sin conservantes", "Sin colorantes", "Sin aditivos", "Sin gluten", "Sin lactosa", "Asado al horno", "Braseado", "Curación natural", "Cocinado a baja temperatura", "Receta tradicional", "Ahumado natural"
- CERTIFICACIONES/SELLOS: "Bienestar Animal (AENOR)", "Bienestar Animal", "Raza Duroc", "50% Raza Duroc", "Ibérico", "Denominación de Origen", "Ecológico", "Bio", "Halal", "Kosher", "Criado en libertad", "Sin OGM", "Gran Reserva", "IFS", "BRC", "Elaborado en España"
- POSICIONAMIENTO/GAMA: "BonNatur", "Oliving", "Premier", "Delizias", "Grand Bouquet", "Naturarte", "Vegalia", "Cuida-T", "Calidad Extra", "Premium", "Gourmet", "Artesano", "Selección", "100% natural", "1954"
- CONVENIENCIA: "Listo en X min", "Fácil apertura", "Resellable", "Listo para comer"
- PORCENTAJE DE CARNE: si aparece "XX% de carne" o "XX% carne" inclúyelo tal cual

Reglas numéricas:
- Usa siempre punto decimal (no coma): 1.5 no 1,5
- Si un valor aparece como "<0,5g" usa 0.5
- Para kcal busca el número en kcal (no kJ)
- Si no aparece un campo, usa null
- Devuelve SOLO el JSON, sin explicaciones adicionales"""


_MISTRAL_TIMEOUT  = 90   # segundos — pixtral-12b con imagen grande puede tardar ~60s
_MISTRAL_RETRIES  = 3    # intentos totales antes de rendirse
_MISTRAL_BACKOFF  = 5    # segundos de espera entre reintentos


def _comprimir_imagen(img_bytes: bytes, max_kb: int = 800) -> bytes:
    """Reduce el tamaño de la imagen si supera max_kb para evitar timeouts."""
    try:
        import io
        from PIL import Image  # type: ignore

        if len(img_bytes) <= max_kb * 1024:
            return img_bytes

        img = Image.open(io.BytesIO(img_bytes))
        # Reducir dimensiones si es muy grande
        max_dim = 1400
        if max(img.size) > max_dim:
            img.thumbnail((max_dim, max_dim), Image.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=75, optimize=True)
        compressed = buf.getvalue()
        logger.debug(f"[Mistral Vision] Imagen comprimida: {len(img_bytes)//1024}KB → {len(compressed)//1024}KB")
        return compressed
    except Exception:
        return img_bytes  # si falla PIL, usar original


def extraer_nutricional_con_mistral(img_bytes: bytes) -> Dict:
    """
    Envía una imagen a Mistral Vision (pixtral-12b) y extrae los datos nutricionales.
    Reintenta hasta _MISTRAL_RETRIES veces ante timeout o error transitorio.

    Args:
        img_bytes: bytes de la imagen (screenshot de la tabla nutricional)

    Returns:
        Dict con los campos nutricionales extraídos
    """
    if not MISTRAL_API_KEY:
        logger.warning("[Mistral] API key no configurada — omitiendo extracción por visión")
        return {}

    import time
    import urllib.request
    import ssl

    # Comprimir si la imagen es muy pesada
    img_bytes = _comprimir_imagen(img_bytes)
    img_b64 = base64.standard_b64encode(img_bytes).decode("utf-8")

    payload = json.dumps({
        "model": "pixtral-12b-2409",
        "messages": [{
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": f"data:image/png;base64,{img_b64}"
                },
                {
                    "type": "text",
                    "text": PROMPT_NUTRICIONAL
                }
            ]
        }],
        "max_tokens": 1024,
        "temperature": 0.1,
    }).encode("utf-8")

    ctx = ssl.create_default_context()
    last_error = None

    for intento in range(1, _MISTRAL_RETRIES + 1):
        try:
            req = urllib.request.Request(
                "https://api.mistral.ai/v1/chat/completions",
                data=payload,
                headers={
                    "Authorization": f"Bearer {MISTRAL_API_KEY}",
                    "Content-Type": "application/json",
                },
                method="POST"
            )
            with urllib.request.urlopen(req, context=ctx, timeout=_MISTRAL_TIMEOUT) as resp:
                respuesta = json.loads(resp.read().decode("utf-8"))

            texto = respuesta["choices"][0]["message"]["content"].strip()
            texto = re.sub(r"^```(?:json)?\s*", "", texto)
            texto = re.sub(r"\s*```$", "", texto)

            datos = json.loads(texto)
            logger.info(f"[Mistral Vision] Extracción exitosa (intento {intento}): {list(k for k,v in datos.items() if v is not None)}")
            return datos

        except json.JSONDecodeError as e:
            logger.warning(f"[Mistral Vision] JSON inválido (intento {intento}): {e}")
            return {}  # no reintentar si es problema de parseo
        except Exception as e:
            last_error = e
            if intento < _MISTRAL_RETRIES:
                wait = _MISTRAL_BACKOFF * intento
                logger.warning(f"[Mistral Vision] Error (intento {intento}/{_MISTRAL_RETRIES}): {e} — reintentando en {wait}s")
                time.sleep(wait)
            else:
                logger.warning(f"[Mistral Vision] Error tras {_MISTRAL_RETRIES} intentos: {e}")

    return {}


def extraer_nutricional_de_screenshot(page, selector: Optional[str] = None) -> Dict:
    """
    Captura screenshot de un elemento de la página y lo procesa con Mistral Vision.

    Args:
        page: página de Playwright
        selector: selector CSS del elemento (None = página completa)

    Returns:
        Dict con datos nutricionales
    """
    try:
        if selector:
            el = page.query_selector(selector)
            if el:
                img_bytes = el.screenshot()
            else:
                logger.debug(f"[Mistral Vision] Selector '{selector}' no encontrado, capturando página")
                img_bytes = page.screenshot(full_page=False)
        else:
            img_bytes = page.screenshot(full_page=False)

        return extraer_nutricional_con_mistral(img_bytes)

    except Exception as e:
        logger.warning(f"[Mistral Vision] Error capturando screenshot: {e}")
        return {}
