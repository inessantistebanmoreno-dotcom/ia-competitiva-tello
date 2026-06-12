# =============================================================================
# config.py — Configuración central del Agente de Inteligencia Competitiva
# Tello · Etiquetado · v1.0
# =============================================================================

import os
from dotenv import load_dotenv

load_dotenv()
from dataclasses import dataclass, field
from typing import List
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# API Keys (carga desde variables de entorno — NO hardcodear)
# ---------------------------------------------------------------------------
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MISTRAL_API_KEY   = os.environ.get("MISTRAL_API_KEY", "")
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://usuario:contraseña@localhost:5432/inteligencia_competitiva"
)

# Para envío de alertas por email (SMTP)
SMTP_HOST     = os.environ.get("SMTP_HOST", "smtp.office365.com")
SMTP_PORT     = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER     = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
EMAIL_FROM    = os.environ.get("EMAIL_FROM", "agente-etiquetado@tello.es")
EMAIL_TO      = os.environ.get("EMAIL_TO", "marketing1@tello.es")   # puede ser lista separada por comas

# ---------------------------------------------------------------------------
# URLs de catálogo por competidor
# ---------------------------------------------------------------------------
COMPETIDORES = {
    "noel": {
        "nombre": "Noel",
        "catalogo_urls": [
            "https://www.noel.es/productos/",
        ],
        "tipo": "html",   # "html" | "vision"
        "delay_entre_paginas": 2.0,   # segundos
    },
    "campofrio": {
        "nombre": "Campofrío",
        "catalogo_urls": [
            "https://www.campofrio.es/productos/",
        ],
        "tipo": "html",
        "delay_entre_paginas": 2.5,
    },
    "elpozo": {
        "nombre": "El Pozo",
        "catalogo_urls": [
            "https://www.elpozo.com/productos/",
        ],
        "tipo": "vision",   # tabla nutricional en imagen
        "delay_entre_paginas": 3.0,
    },
    "argal": {
        "nombre": "Argal",
        "catalogo_urls": [
            "https://www.argal.es/productos/",
        ],
        "tipo": "html",
        "delay_entre_paginas": 3.5,   # scraper más lento
    },
}

# ---------------------------------------------------------------------------
# Modelo Claude para extracción por visión
# ---------------------------------------------------------------------------
CLAUDE_MODEL = "claude-opus-4-6"   # modelo con visión

# Prompt base que recibe Claude Vision al analizar una imagen de etiqueta
CLAUDE_VISION_PROMPT = """
Eres un experto en etiquetado alimentario. Analiza la imagen de la etiqueta/ficha nutricional
y extrae TODOS los datos que encuentres en formato JSON estricto con esta estructura:

{
  "kcal": <número o null>,
  "proteinas_g": <número o null>,
  "grasas_g": <número o null>,
  "grasas_saturadas_g": <número o null>,
  "carbohidratos_g": <número o null>,
  "azucares_g": <número o null>,
  "fibra_g": <número o null>,
  "sal_g": <número o null>,
  "ingredientes": "<texto completo de la lista de ingredientes o null>",
  "alergenos": ["<alergeno1>", "<alergeno2>", ...],
  "claims": ["<claim1>", "<claim2>", ...],
  "porcentaje_carne": <número o null>
}

- Para alérgenos, usa SIEMPRE nombres normalizados: gluten, lactosa, huevo, soja, frutos_secos, apio, mostaza, sesamo, sulfitos, moluscos, crustaceos, pescado, nitrites_added
- Para claims, extrae EXACTAMENTE el texto del packaging (p.ej. "Sin nitritos añadidos", "Alto en proteínas", "Reducido en sal", "Ibérico", "Elaborado en España")
- Si un campo no aparece en la imagen, devuelve null
- Devuelve SOLO el JSON, sin texto adicional
"""

# ---------------------------------------------------------------------------
# Configuración del ciclo de scraping
# ---------------------------------------------------------------------------
CICLO_HORAS = 6          # ejecutar cada N horas
TIMEOUT_PAGINA_SEG = 30  # timeout por página en Playwright
MAX_REINTENTOS = 3       # reintentos ante error de red

# ---------------------------------------------------------------------------
# Fecha de baseline — cambios ANTES de esta fecha son de calibración/setup
# y se ignoran en alertas y en los KPIs del dashboard.
# ACTUALIZAR cuando el sistema esté estable y en producción real.
# Formato: "YYYY-MM-DD" (se interpreta como medianoche UTC)
# ---------------------------------------------------------------------------
FECHA_BASELINE = "2026-06-12"   # ← cambiar a la fecha de go-live

# ---------------------------------------------------------------------------
# Severidad de cambios para el sistema de alertas
# ---------------------------------------------------------------------------
CAMBIOS_CRITICOS = ["ingredientes", "alergenos"]
CAMBIOS_ALTOS    = ["kcal", "proteinas_g", "grasas_g", "sal_g",
                    "grasas_saturadas_g", "carbohidratos_g", "azucares_g"]
CAMBIOS_MEDIOS   = ["claims", "porcentaje_carne", "descripcion"]
CAMBIOS_BAJOS    = ["categoria", "subcategoria", "formato", "gramaje_g"]
