# =============================================================================
# alertas.py — Sistema de alertas por email
# Tello · Etiquetado · v1.0
# =============================================================================

import logging
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict, List

from config import (
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD,
    EMAIL_FROM, EMAIL_TO,
)
from database.db import marcar_alertas_enviadas, obtener_alertas_pendientes

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Colores y etiquetas por severidad
# ---------------------------------------------------------------------------
ESTILO = {
    "critico": {"color": "#DC2626", "bg": "#FEE2E2", "etiqueta": "⛔ CRÍTICO"},
    "alto":    {"color": "#D97706", "bg": "#FEF3C7", "etiqueta": "🔶 ALTO"},
    "medio":   {"color": "#2563EB", "bg": "#DBEAFE", "etiqueta": "🔵 MEDIO"},
    "bajo":    {"color": "#6B7280", "bg": "#F3F4F6", "etiqueta": "⚪ BAJO"},
}

NOMBRE_CAMPO = {
    "ingredientes":        "Ingredientes",
    "alergenos":           "Alérgenos",
    "kcal":                "Calorías (kcal)",
    "proteinas_g":         "Proteínas (g)",
    "grasas_g":            "Grasas totales (g)",
    "grasas_saturadas_g":  "Grasas saturadas (g)",
    "carbohidratos_g":     "Carbohidratos (g)",
    "azucares_g":          "Azúcares (g)",
    "fibra_g":             "Fibra (g)",
    "sal_g":               "Sal (g)",
    "claims":              "Claims packaging",
    "porcentaje_carne":    "% carne",
    "nuevo_producto":      "Nuevo producto detectado",
    "descripcion":         "Descripción web",
}


# ---------------------------------------------------------------------------
# Construcción del HTML del email
# ---------------------------------------------------------------------------

def _fila_cambio(c: Dict) -> str:
    estilo = ESTILO.get(c["severidad"], ESTILO["bajo"])
    campo  = NOMBRE_CAMPO.get(c["campo_modificado"], c["campo_modificado"])
    antes  = c.get("valor_anterior") or "—"
    ahora  = c.get("valor_nuevo")    or "—"
    return f"""
    <tr>
      <td style="padding:10px 14px;border-bottom:1px solid #F1F5F9;">
        <span style="
          display:inline-block;padding:2px 8px;border-radius:4px;
          font-size:11px;font-weight:700;text-transform:uppercase;
          color:{estilo['color']};background:{estilo['bg']};
        ">{estilo['etiqueta']}</span>
      </td>
      <td style="padding:10px 14px;border-bottom:1px solid #F1F5F9;font-weight:600;color:#0F2240;">{c.get('competidor','').upper()}</td>
      <td style="padding:10px 14px;border-bottom:1px solid #F1F5F9;">{c.get('nombre_producto','')}</td>
      <td style="padding:10px 14px;border-bottom:1px solid #F1F5F9;color:#6B7280;">{campo}</td>
      <td style="padding:10px 14px;border-bottom:1px solid #F1F5F9;color:#DC2626;text-decoration:line-through;">{antes[:120]}</td>
      <td style="padding:10px 14px;border-bottom:1px solid #F1F5F9;color:#16A34A;font-weight:500;">{ahora[:120]}</td>
    </tr>"""


def _construir_html(cambios: List[Dict], asunto: str) -> str:
    filas = "".join(_fila_cambio(c) for c in cambios)
    fecha = datetime.now().strftime("%d/%m/%Y %H:%M")
    return f"""
<!DOCTYPE html>
<html lang="es">
<head><meta charset="UTF-8"><title>{asunto}</title></head>
<body style="font-family:Arial,sans-serif;background:#F8FAFC;margin:0;padding:24px;">
  <div style="max-width:900px;margin:0 auto;background:#fff;border-radius:10px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.08);">

    <!-- Header -->
    <div style="background:#0F2240;padding:20px 28px;display:flex;justify-content:space-between;align-items:center;">
      <div>
        <div style="color:#fff;font-size:18px;font-weight:700;">Agente Intel Competitiva · Etiquetado</div>
        <div style="color:rgba(255,255,255,.5);font-size:12px;margin-top:4px;">{fecha}</div>
      </div>
      <div style="color:#fff;font-size:28px;font-weight:800;letter-spacing:.05em;">Tello</div>
    </div>

    <!-- Resumen -->
    <div style="padding:20px 28px;border-bottom:1px solid #E2E8F0;">
      <p style="margin:0;font-size:14px;color:#475569;">
        Se han detectado <strong>{len(cambios)} cambio(s)</strong> en el catálogo de la competencia.
        Los cambios críticos y altos requieren revisión inmediata del equipo de etiquetado.
      </p>
    </div>

    <!-- Tabla de cambios -->
    <div style="padding:20px 28px;">
      <table style="width:100%;border-collapse:collapse;font-size:13px;">
        <thead>
          <tr style="background:#F8FAFC;">
            <th style="padding:10px 14px;text-align:left;font-size:11px;color:#94A3B8;text-transform:uppercase;border-bottom:2px solid #E2E8F0;">Severidad</th>
            <th style="padding:10px 14px;text-align:left;font-size:11px;color:#94A3B8;text-transform:uppercase;border-bottom:2px solid #E2E8F0;">Marca</th>
            <th style="padding:10px 14px;text-align:left;font-size:11px;color:#94A3B8;text-transform:uppercase;border-bottom:2px solid #E2E8F0;">Producto</th>
            <th style="padding:10px 14px;text-align:left;font-size:11px;color:#94A3B8;text-transform:uppercase;border-bottom:2px solid #E2E8F0;">Campo</th>
            <th style="padding:10px 14px;text-align:left;font-size:11px;color:#94A3B8;text-transform:uppercase;border-bottom:2px solid #E2E8F0;">Antes</th>
            <th style="padding:10px 14px;text-align:left;font-size:11px;color:#94A3B8;text-transform:uppercase;border-bottom:2px solid #E2E8F0;">Ahora</th>
          </tr>
        </thead>
        <tbody>{filas}</tbody>
      </table>
    </div>

    <!-- Footer -->
    <div style="padding:16px 28px;background:#F8FAFC;border-top:1px solid #E2E8F0;">
      <p style="margin:0;font-size:11px;color:#94A3B8;">
        Generado automáticamente por el Agente de Inteligencia Competitiva de Tello.
        Para revisar el historial completo, consulta el dashboard de etiquetado.
      </p>
    </div>
  </div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Envío de email
# ---------------------------------------------------------------------------

def _enviar_email(asunto: str, html: str, destinatarios: List[str]):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = asunto
    msg["From"]    = EMAIL_FROM
    msg["To"]      = ", ".join(destinatarios)
    msg.attach(MIMEText(html, "html", "utf-8"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.ehlo()
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(EMAIL_FROM, destinatarios, msg.as_string())

    logger.info(f"Email enviado a {destinatarios}: {asunto}")


# ---------------------------------------------------------------------------
# Lógica principal de alertas
# ---------------------------------------------------------------------------

def procesar_y_enviar_alertas():
    """
    Recupera alertas pendientes de la BD y las agrupa por severidad para enviar:
    - Inmediato: crítico + alto  → email al momento
    - Diario:    medio           → resumen (llamar desde cron diario)
    - Semanal:   bajo            → resumen (llamar desde cron semanal)
    """
    pendientes = obtener_alertas_pendientes()
    if not pendientes:
        logger.info("Sin alertas pendientes")
        return

    destinatarios = [e.strip() for e in EMAIL_TO.split(",")]

    # Agrupar por severidad
    criticos = [c for c in pendientes if c["severidad"] == "critico"]
    altos    = [c for c in pendientes if c["severidad"] == "alto"]
    urgentes = criticos + altos

    ids_enviados = []

    if urgentes:
        n_crit = len(criticos)
        n_alto = len(altos)
        asunto = f"[TELLO ETIQUETADO] {n_crit} cambio(s) CRÍTICO(S) y {n_alto} ALTO(S) detectados en competencia"
        html   = _construir_html(urgentes, asunto)
        try:
            _enviar_email(asunto, html, destinatarios)
            ids_enviados.extend(c["id"] for c in urgentes)
        except Exception as e:
            logger.error(f"Error enviando email urgente: {e}")

    if ids_enviados:
        marcar_alertas_enviadas(ids_enviados)

    return len(ids_enviados)


def enviar_resumen_diario():
    """Envía resumen de nuevos productos (severidad MEDIO) del día."""
    from database.db import get_connection
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM historial_cambios
                WHERE severidad = 'medio'
                  AND alerta_enviada = FALSE
                  AND fecha_cambio >= NOW() - INTERVAL '24 hours'
                ORDER BY fecha_cambio DESC
            """)
            cambios = [dict(r) for r in cur.fetchall()]

    if not cambios:
        return

    destinatarios = [e.strip() for e in EMAIL_TO.split(",")]
    asunto = f"[TELLO ETIQUETADO] Resumen diario: {len(cambios)} novedades en competencia"
    html   = _construir_html(cambios, asunto)
    try:
        _enviar_email(asunto, html, destinatarios)
        from database.db import marcar_alertas_enviadas
        marcar_alertas_enviadas([c["id"] for c in cambios])
    except Exception as e:
        logger.error(f"Error enviando resumen diario: {e}")
