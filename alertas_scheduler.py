#!/usr/bin/env python3
# =============================================================================
# alertas_scheduler.py — Gestor de alertas programadas
# Uso:
#   python alertas_scheduler.py --tipo nuevos    → alerta de nuevos productos
#   python alertas_scheduler.py --tipo informe   → informe diario de cambios
# =============================================================================

import argparse
import logging
import os
import smtplib
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from dotenv import load_dotenv
load_dotenv()

from config import SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, EMAIL_FROM, EMAIL_TO, FECHA_BASELINE
from database.db import get_connection

SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY", "")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

ESTILO = {
    "critico": {"color": "#DC2626", "bg": "#FEE2E2", "etiqueta": "⛔ CRÍTICO"},
    "alto":    {"color": "#D97706", "bg": "#FEF3C7", "etiqueta": "🔶 ALTO"},
    "medio":   {"color": "#2563EB", "bg": "#DBEAFE", "etiqueta": "🔵 NUEVO"},
    "bajo":    {"color": "#6B7280", "bg": "#F3F4F6", "etiqueta": "⚪ BAJO"},
}

NOMBRE_CAMPO = {
    "ingredientes":       "Ingredientes",
    "alergenos":          "Alérgenos",
    "kcal":               "Calorías (kcal)",
    "proteinas_g":        "Proteínas (g)",
    "grasas_g":           "Grasas totales (g)",
    "grasas_saturadas_g": "Grasas saturadas (g)",
    "carbohidratos_g":    "Carbohidratos (g)",
    "azucares_g":         "Azúcares (g)",
    "fibra_g":            "Fibra (g)",
    "sal_g":              "Sal (g)",
    "claims":             "Claims packaging",
    "claim_nutricional":  "Claim nutricional",
    "claim_proteinas":    "Claim proteínas",
    "claim_grasa":        "Claim grasa",
    "claim_sellos":       "Sellos / Certificaciones",
    "claim_gama":         "Gama / Línea",
    "claim_seleccion":    "Selección / Calidad",
    "porcentaje_carne":   "% carne",
    "nuevo_producto":     "Nuevo producto",
}

# ─────────────────────────────────────────────────────────────────────────────
# Contexto estratégico por tipo de claim
# ─────────────────────────────────────────────────────────────────────────────
CONTEXTO_CLAIM = {
    "Sin nitritos añadidos": (
        "Tendencia 'clean label' en alza. La EFSA revisó los límites de nitratos/nitritos "
        "en 2023. El competidor posiciona el producto como más saludable y moderno. "
        "<strong>Valorar si Tello tiene un equivalente o puede lanzarlo.</strong>"
    ),
    "Sin nitritos": (
        "Eliminación de nitritos — diferenciador premium. "
        "Implica cambio de formulación (uso de extracto de apio o remolacha como fuente natural). "
        "Mayor coste de producción pero mayor precio de venta."
    ),
    "Sin fosfatos añadidos": (
        "Claim 'clean label'. Los fosfatos (E450-E452) son vistos negativamente por "
        "consumidores informados. Reformulación que puede afectar textura del producto."
    ),
    "Sin fosfatos": (
        "Reformulación libre de fosfatos. Requiere ajuste técnico de la formulación "
        "para mantener textura y capacidad de retención de agua."
    ),
    "Sin conservantes": (
        "Reformulación clean label. Puede necesitar ajuste de vida útil o cambio de envase "
        "(atmósfera protectora, envase al vacío). Tendencia impulsada por distribuidores líderes."
    ),
    "Sin colorantes": (
        "Eliminación de colorantes artificiales. Requerido cada vez más por distribuidores "
        "(Mercadona, Lidl). Mejora la percepción de naturalidad del producto."
    ),
    "Sin aditivos": (
        "Reformulación 'limpia' integral. Posicionamiento premium de máxima naturalidad. "
        "Implica revisión completa de ingredientes y puede afectar la formulación."
    ),
    "Bienestar Animal (AENOR)": (
        "Certificación AENOR en crecimiento, impulsada por Mercadona y Carrefour como requisito "
        "de compra. Implica auditoría externa y cambio de condiciones del proveedor de carne. "
        "<strong>¿Tiene Tello algún proveedor certificado?</strong>"
    ),
    "Bienestar Animal": (
        "Certificación de bienestar animal en alza. Impulsada por consumidores conscientes "
        "y cada vez más exigida por la distribución. Puede ser paso previo a AENOR."
    ),
    "50% Raza Duroc": (
        "Diferenciador de calidad de carne (mayor infiltración de grasa, mejor sabor y jugosidad). "
        "Permite subir el precio de venta y competir en el segmento premium de jamón cocido."
    ),
    "100% Raza Duroc": (
        "Máxima diferenciación por raza. Posicionamiento gourmet. "
        "Muy ligado a la tendencia de trazabilidad y transparencia sobre el origen."
    ),
    "Raza Duroc": (
        "Claim de calidad de raza porcina. Asociado a mayor calidad organoléptica. "
        "Creciente interés del consumidor por el origen y la raza del animal."
    ),
    "Rico en colágeno": (
        "Tendencia de productos funcionales para articulaciones y piel. "
        "Mercado en crecimiento, especialmente en target 40+. "
        "Puede ser claim emergente en charcutería — pionero tiene ventaja."
    ),
    "Alto en proteínas": (
        "Respuesta a dietas proteicas (keto, paleo, fitness). Segmento joven y activo. "
        "Permite comunicar en canales de deporte y bienestar."
    ),
    "Fuente de proteínas": (
        "Versión más conservadora de claim proteico (Reg. 1924/2006: ≥12% energía de proteínas). "
        "Más fácil de cumplir que 'Alto en proteínas' (≥20% energía)."
    ),
    "Reducido en sal": (
        "Respuesta a recomendaciones OMS/AESAN de reducción de sodio. "
        "Reg. 1924/2006 permite claim oficial si sal ≤1,25g/100g (-25% vs referencia). "
        "<strong>Revisar si Tello puede reclamar lo mismo.</strong>"
    ),
    "Ecológico": (
        "Reposicionamiento hacia gama premium. Implica certificación CCPAE/CAAE costosa "
        "y cambio de proveedores. Señal de que el competidor está explorando canales premium."
    ),
    "Gran Reserva": (
        "Posicionamiento premium por tiempo de maduración. Permite precio más alto. "
        "Asociado a calidad artesanal y tradición."
    ),
    "Artesano": (
        "Posicionamiento premium frente a productos industriales. "
        "Muy valorado por el consumidor aunque no tiene definición legal estricta."
    ),
    "Calidad Extra": (
        "Categoría oficial según RD 474/2014 (≥85% carne en jamón cocido). "
        "Importante diferenciador de calidad con respaldo legal."
    ),
    "Sin gluten": (
        "Mercado celíaco y sin gluten (aprox. 1% celíacos + 10% sensibilidad no celíaca). "
        "Puede abrir canales de distribución especializados."
    ),
    "Sin lactosa": (
        "Aprox. 15% de la población española con intolerancia a la lactosa. "
        "Claim cada vez más valorado también por consumidores sin intolerancia."
    ),
    "Ibérico": (
        "Denominación de alta calidad con regulación específica (Norma de Calidad del Ibérico). "
        "Máxima valoración en el mercado español y exterior."
    ),
    "Denominación de Origen": (
        "Protección legal europea. Señal de calidad diferenciada con respaldo institucional. "
        "Muy valorado en canales gourmet y exportación."
    ),
    "Criado en libertad": (
        "Tendencia de bienestar animal y ganadería extensiva. "
        "Impulsada por consumidores conscientes y medios de comunicación."
    ),
    "Cocinado a baja temperatura": (
        "Técnica premium (sous vide) que mejora textura y jugosidad. "
        "Diferenciador técnico de calidad con buena percepción de consumidor."
    ),
    "100% natural": (
        "Claim genérico de naturalidad sin definición legal estricta. "
        "Muy usado por competidores — riesgo de confusión con el consumidor."
    ),
}


def _enviar_email(asunto: str, html: str):
    destinatarios = [e.strip() for e in EMAIL_TO.split(",")]

    # Usar SendGrid si está disponible (funciona desde la nube)
    if SENDGRID_API_KEY and SENDGRID_API_KEY != "sin-api-por-ahora":
        import urllib.request, json
        payload = json.dumps({
            "personalizations": [{"to": [{"email": d} for d in destinatarios]}],
            "from": {"email": EMAIL_FROM},
            "subject": asunto,
            "content": [{"type": "text/html", "value": html}]
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://api.sendgrid.com/v3/mail/send",
            data=payload,
            headers={
                "Authorization": f"Bearer {SENDGRID_API_KEY}",
                "Content-Type": "application/json"
            },
            method="POST"
        )
        import ssl
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, context=ctx) as resp:
            if resp.status in (200, 202):
                logger.info(f"Email enviado via SendGrid: {asunto}")
                return
        raise Exception(f"SendGrid error: {resp.status}")

    # Fallback: SMTP (para uso local)
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
    logger.info(f"Email enviado via SMTP: {asunto}")


# Colores por marca
MARCA_COLOR = {
    "campofrio": {"bg": "#FEF2F2", "border": "#DC2626", "label": "Campofrío"},
    "elpozo":    {"bg": "#EFF6FF", "border": "#2563EB", "label": "El Pozo"},
    "noel":      {"bg": "#F5F3FF", "border": "#7C3AED", "label": "Noel"},
    "argal":     {"bg": "#F0FDF4", "border": "#16A34A", "label": "Argal"},
}

# Umbrales de referencia (Reg. 1924/2006 + AESAN)
SAL_AESAN        = 1.25   # g/100g — "alto en sal" a partir de aquí
SAL_REDUCIDO     = 1.10   # g/100g — puede reclamar "reducido en sal"
PCT_CARNE_EXTRA  = 85.0   # % — calidad extra (RD 474/2014)
PCT_CARNE_MEDIA  = 84.0   # % — media del sector jamón cocido

def _parsear_claims_lista(valor) -> list:
    """Convierte el valor almacenado en BD (string o lista) a una lista de claims."""
    if not valor:
        return []
    if isinstance(valor, list):
        return [str(x).strip() for x in valor if x]
    # Puede venir como '{claim1,claim2}' (PostgreSQL array serializado)
    s = str(valor).strip()
    if s.startswith("{") and s.endswith("}"):
        s = s[1:-1]
        return [x.strip().strip('"') for x in s.split(",") if x.strip()]
    # Fallback: separado por " / " o coma
    if " / " in s:
        return [x.strip() for x in s.split(" / ") if x.strip()]
    return [s] if s else []


def _diff_claims(antes, ahora) -> tuple:
    """
    Devuelve (añadidos, eliminados) comparando dos listas de claims.
    """
    set_antes = set(_parsear_claims_lista(antes))
    set_ahora  = set(_parsear_claims_lista(ahora))
    añadidos   = sorted(set_ahora - set_antes)
    eliminados = sorted(set_antes - set_ahora)
    return añadidos, eliminados


def _pill(texto: str, color: str, bg: str, prefijo: str = "") -> str:
    return (
        f'<span style="display:inline-block;background:{bg};color:{color};'
        f'border:1px solid {color}40;border-radius:20px;'
        f'padding:4px 10px;font-size:11px;font-weight:700;margin:3px 4px 3px 0">'
        f'{prefijo}{texto}</span>'
    )


def _tarjeta_claim(c: dict) -> str:
    """
    Tarjeta especializada para cambios en claims.
    Muestra pills de claims añadidos (verde) y eliminados (rojo)
    junto con contexto estratégico de por qué lo hace el competidor.
    """
    marca    = _get_marca_style(c.get("competidor", ""))
    producto = c.get("nombre_producto", "—")
    añadidos, eliminados = _diff_claims(c.get("valor_anterior"), c.get("valor_nuevo"))

    if not añadidos and not eliminados:
        return ""  # No hay diff real — omitir

    # Pills de claims añadidos
    pills_add = "".join(_pill(cl, "#16A34A", "#F0FDF4", "+ ") for cl in añadidos)
    # Pills de claims eliminados
    pills_del = "".join(_pill(cl, "#DC2626", "#FEF2F2", "− ") for cl in eliminados)

    # Contexto estratégico: buscar el claim más relevante en CONTEXTO_CLAIM
    contexto_html = ""
    for cl in (añadidos + eliminados):
        if cl in CONTEXTO_CLAIM:
            accion = "ha <strong>añadido</strong>" if cl in añadidos else "ha <strong>retirado</strong>"
            contexto_html = (
                f'<div style="background:#FFFBEB;border-left:3px solid #F59E0B;'
                f'border-radius:6px;padding:10px 14px;margin-top:10px;font-size:12px;color:#78350F">'
                f'<span style="font-weight:800;font-size:11px;text-transform:uppercase;'
                f'letter-spacing:.06em;color:#B45309">💡 ¿Por qué?</span><br>'
                f'<b>{marca["label"]}</b> {accion} «{cl}»: {CONTEXTO_CLAIM[cl]}'
                f'</div>'
            )
            break  # Solo el contexto más relevante

    # Bloque de antes/ahora en pills
    antes_lista = _parsear_claims_lista(c.get("valor_anterior"))
    ahora_lista = _parsear_claims_lista(c.get("valor_nuevo"))
    pills_antes = "".join(_pill(cl, "#94A3B8", "#F1F5F9") for cl in antes_lista) or \
                  '<span style="color:#94A3B8;font-size:12px;font-style:italic">Sin claims</span>'
    pills_ahora = "".join(_pill(cl, "#475569", "#F8FAFC") for cl in ahora_lista) or \
                  '<span style="color:#94A3B8;font-size:12px;font-style:italic">Sin claims</span>'

    # Resumen del diff
    resumen_parts = []
    if añadidos:
        resumen_parts.append(f'<b style="color:#16A34A">+{len(añadidos)} añadido(s)</b>')
    if eliminados:
        resumen_parts.append(f'<b style="color:#DC2626">−{len(eliminados)} retirado(s)</b>')
    resumen = " · ".join(resumen_parts)

    return f"""
<div style="border:1px solid {marca['border']};border-left:4px solid {marca['border']};
     border-radius:8px;margin-bottom:12px;background:#fff;overflow:hidden">
  <!-- Cabecera -->
  <div style="background:{marca['bg']};padding:10px 16px;
       display:flex;align-items:center;justify-content:space-between">
    <div>
      <span style="font-size:10px;font-weight:800;text-transform:uppercase;
            letter-spacing:.08em;color:{marca['border']}">{marca['label']}</span>
      <span style="font-size:13px;font-weight:700;color:#0F172A;margin-left:8px">{producto}</span>
    </div>
    <span style="font-size:11px;font-weight:700;color:#475569;
          background:#F1F5F9;padding:3px 10px;border-radius:20px">🏷️ Claims · {resumen}</span>
  </div>
  <!-- Diff visual de claims -->
  <div style="padding:14px 16px">
    {"<div style='margin-bottom:10px'><span style='font-size:10px;font-weight:700;color:#16A34A;text-transform:uppercase;letter-spacing:.06em'>✅ Añadidos</span><br>" + pills_add + "</div>" if añadidos else ""}
    {"<div style='margin-bottom:10px'><span style='font-size:10px;font-weight:700;color:#DC2626;text-transform:uppercase;letter-spacing:.06em'>❌ Retirados</span><br>" + pills_del + "</div>" if eliminados else ""}
    <!-- Estado completo anterior → nuevo -->
    <div style="border-top:1px solid #F1F5F9;padding-top:10px;margin-top:4px">
      <div style="display:flex;gap:10px;flex-wrap:wrap">
        <div style="flex:1;min-width:120px">
          <div style="font-size:9px;font-weight:700;color:#DC2626;text-transform:uppercase;
               margin-bottom:4px">Antes</div>
          <div>{pills_antes}</div>
        </div>
        <div style="font-size:16px;color:#CBD5E1;padding-top:14px">→</div>
        <div style="flex:1;min-width:120px">
          <div style="font-size:9px;font-weight:700;color:#16A34A;text-transform:uppercase;
               margin-bottom:4px">Ahora</div>
          <div>{pills_ahora}</div>
        </div>
      </div>
    </div>
    {contexto_html}
  </div>
</div>"""


def _contexto_cambio(c: dict) -> str:
    """
    Genera una explicación accionable del cambio en lenguaje natural.
    Responde a '¿por qué importa esto?'
    """
    campo = c.get("campo_modificado", "")
    antes_str = str(c.get("valor_anterior") or "")
    ahora_str = str(c.get("valor_nuevo") or "")
    marca = _get_marca_style(c.get("competidor",""))["label"]

    try:
        antes_f = float(antes_str.replace(",","."))
        ahora_f = float(ahora_str.replace(",","."))
        diff_pct = round(abs(ahora_f - antes_f) / antes_f * 100, 1) if antes_f else 0
    except (ValueError, TypeError):
        antes_f = ahora_f = diff_pct = None

    # --- % CARNE ---
    if campo == "porcentaje_carne" and antes_f is not None:
        if ahora_f < antes_f:
            ctx = f"{marca} ha reducido el % de carne un {diff_pct}%."
            if ahora_f < PCT_CARNE_MEDIA:
                ctx += f" Ahora está <strong>por debajo de la media del sector ({PCT_CARNE_MEDIA}%)</strong>."
            elif ahora_f < PCT_CARNE_EXTRA:
                ctx += " Ya no cumple el umbral de calidad extra (85%)."
            return ctx
        else:
            ctx = f"{marca} ha aumentado el % de carne un {diff_pct}%."
            if ahora_f >= PCT_CARNE_EXTRA:
                ctx += " <strong>Cumple ahora el umbral de calidad extra (≥85%)</strong>."
            return ctx

    # --- SAL ---
    if campo == "sal_g" and antes_f is not None:
        if ahora_f < antes_f:
            ctx = f"{marca} ha reducido la sal un {diff_pct}%."
            if ahora_f <= SAL_REDUCIDO:
                ctx += " <strong>Podría reclamar 'Reducido en sal' (Reg. 1924/2006)</strong>."
            elif ahora_f <= SAL_AESAN:
                ctx += " Ya está por debajo del umbral AESAN de 'alto en sal' (1,25g)."
            return ctx
        else:
            ctx = f"{marca} ha aumentado la sal un {diff_pct}%."
            if ahora_f > SAL_AESAN:
                ctx += " <strong>Supera el umbral AESAN de 'alto en sal' (>1,25g/100g)</strong>."
            return ctx

    # --- ALERGENOS ---
    if campo == "alergenos":
        return f"<strong>Cambio en declaración de alérgenos de {marca}.</strong> Revisar implicaciones legales y de etiquetado obligatorio."

    # --- INGREDIENTES ---
    if campo == "ingredientes":
        ahora_l = ahora_str.lower()
        if any(x in ahora_l for x in ["nitrito", "e-250", "e250"]):
            return f"{marca} mantiene o ha añadido nitritos en la formulación."
        if any(x in ahora_l for x in ["sin nitritos", "sin nitritos añadidos"]):
            return f"<strong>{marca} ha eliminado los nitritos.</strong> Diferenciador clave que Tello podría valorar."
        if any(x in ahora_l for x in ["fécula","almidón","almidon"]):
            return f"{marca} ha modificado los almidones/espesantes en la formulación."
        return f"{marca} ha reformulado los ingredientes. Revisar si afecta a alérgenos o declaraciones."

    # --- CLAIMS ---
    if campo in ("claims", "claim_nutricional", "claim_proteinas", "claim_sellos",
                 "claim_grasa", "claim_gama", "claim_seleccion"):
        añadidos, eliminados = _diff_claims(antes_str, ahora_str)
        partes = []
        if añadidos:
            partes.append(f"{marca} añade: <strong>{', '.join(añadidos[:3])}</strong>.")
        if eliminados:
            partes.append(f"Retira: <strong>{', '.join(eliminados[:3])}</strong>.")
        # Buscar contexto específico
        for cl in (añadidos + eliminados):
            if cl in CONTEXTO_CLAIM:
                partes.append(CONTEXTO_CLAIM[cl])
                break
        return " ".join(partes) if partes else f"{marca} ha actualizado claims de packaging."

    # --- PROTEÍNAS ---
    if campo == "proteinas_g" and antes_f is not None:
        if ahora_f > antes_f:
            return f"{marca} ha aumentado las proteínas. Podría reclamar 'Alto en proteínas' si supera el 20% del valor energético."
        return f"{marca} ha reducido el contenido proteico un {diff_pct}%."

    # --- GRASAS ---
    if campo in ("grasas_g","grasas_saturadas_g") and antes_f is not None:
        if ahora_f < antes_f:
            return f"{marca} ha reducido las grasas{'saturadas' if 'sat' in campo else ''} un {diff_pct}%."
        return f"{marca} ha aumentado las grasas{'saturadas' if 'sat' in campo else ''} un {diff_pct}%."

    return ""


def _asunto_dinamico(cambios: list) -> str:
    """Genera un asunto de email que cuenta la noticia principal."""
    empeoramientos = [c for c in cambios if c.get("direccion_calidad") == "empeoramiento"
                      and c.get("severidad") in ("critico","alto")]
    mejoras = [c for c in cambios if c.get("direccion_calidad") == "mejora"
               and c.get("severidad") in ("critico","alto")]
    nuevos = [c for c in cambios if c.get("tipo_cambio") == "nuevo_producto"]
    CAMPOS_CLAIMS = {"claims", "claim_nutricional", "claim_proteinas", "claim_grasa",
                     "claim_sellos", "claim_gama", "claim_seleccion"}
    claims_cambios = [c for c in cambios if c.get("campo_modificado") in CAMPOS_CLAIMS
                      and c.get("tipo_cambio") != "nuevo_producto"]

    partes = []
    # Claims primero — es la prioridad de la jefa
    if claims_cambios:
        c = claims_cambios[0]
        marca = _get_marca_style(c.get("competidor",""))["label"]
        añ, el = _diff_claims(c.get("valor_anterior"), c.get("valor_nuevo"))
        if añ:
            partes.append(f"🏷️ {marca} añade claim: {añ[0]}")
        elif el:
            partes.append(f"🏷️ {marca} retira claim: {el[0]}")
        else:
            partes.append(f"🏷️ {marca} modifica claims")
    if empeoramientos:
        c = empeoramientos[0]
        marca = _get_marca_style(c.get("competidor",""))["label"]
        campo = NOMBRE_CAMPO.get(c.get("campo_modificado",""), c.get("campo_modificado",""))
        partes.append(f"⚠️ {marca} modifica {campo}")
    if mejoras:
        c = mejoras[0]
        marca = _get_marca_style(c.get("competidor",""))["label"]
        partes.append(f"✅ {marca} mejora formulación")
    if nuevos:
        partes.append(f"✨ {len(nuevos)} producto(s) nuevo(s)")

    if not partes:
        return f"[TELLO] Informe diario · {len(cambios)} cambios detectados"

    resumen = " · ".join(partes[:2])
    return f"[TELLO] {resumen}"

def _get_marca_style(competidor: str) -> dict:
    key = (competidor or "").lower().replace("í","i").replace("ó","o")
    for k, v in MARCA_COLOR.items():
        if k in key:
            return v
    return {"bg": "#F8FAFC", "border": "#94A3B8", "label": competidor or "—"}

def _tarjeta_cambio(c: dict) -> str:
    """Genera una tarjeta visual para un cambio importante."""
    campo   = NOMBRE_CAMPO.get(c.get("campo_modificado",""), c.get("campo_modificado",""))
    antes   = str(c.get("valor_anterior") or "—")[:150]
    ahora   = str(c.get("valor_nuevo")    or "—")[:150]
    sev     = c.get("severidad", "bajo")
    dir_cal = c.get("direccion_calidad", "neutro")
    motivo  = c.get("motivo_calidad", "")
    marca   = _get_marca_style(c.get("competidor",""))
    producto = c.get("nombre_producto", "—")

    # Colores según dirección de calidad
    if dir_cal == "empeoramiento":
        cal_icon = "⚠️"; cal_color = "#DC2626"; cal_bg = "#FEF2F2"; cal_label = "EMPEORA"
    elif dir_cal == "mejora":
        cal_icon = "✅"; cal_color = "#16A34A"; cal_bg = "#F0FDF4"; cal_label = "MEJORA"
    else:
        cal_icon = "➡️"; cal_color = "#6B7280"; cal_bg = "#F8FAFC"; cal_label = "NEUTRO"

    sev_data = ESTILO.get(sev, ESTILO["bajo"])

    return f"""
<div style="border:1px solid {marca['border']};border-left:4px solid {marca['border']};
     border-radius:8px;margin-bottom:12px;background:#fff;overflow:hidden;">
  <!-- Cabecera tarjeta -->
  <div style="background:{marca['bg']};padding:10px 16px;display:flex;align-items:center;
       justify-content:space-between;border-bottom:1px solid #E2E8F0;">
    <div>
      <span style="font-size:11px;font-weight:800;text-transform:uppercase;
            letter-spacing:.06em;color:{marca['border']}">{marca['label']}</span>
      <span style="font-size:13px;font-weight:600;color:#0F172A;margin-left:10px">{producto}</span>
    </div>
    <div style="display:flex;gap:6px;align-items:center">
      <span style="padding:3px 8px;border-radius:4px;font-size:10px;font-weight:700;
            text-transform:uppercase;color:{sev_data['color']};background:{sev_data['bg']}">
        {sev_data['etiqueta']}
      </span>
      <span style="padding:3px 8px;border-radius:4px;font-size:10px;font-weight:700;
            text-transform:uppercase;color:{cal_color};background:{cal_bg}">
        {cal_icon} {cal_label}
      </span>
    </div>
  </div>
  <!-- Cuerpo tarjeta -->
  <div style="padding:12px 16px;">
    <div style="font-size:11px;font-weight:700;text-transform:uppercase;
         letter-spacing:.06em;color:#94A3B8;margin-bottom:8px">{campo}</div>
    <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
      <div style="flex:1;min-width:120px;background:#FEF2F2;border-radius:6px;
           padding:8px 12px;border-left:3px solid #DC2626">
        <div style="font-size:10px;color:#DC2626;font-weight:700;margin-bottom:3px">ANTES</div>
        <div style="font-size:13px;color:#7F1D1D;font-family:monospace;text-decoration:line-through">
          {antes}
        </div>
      </div>
      <div style="font-size:20px;color:#94A3B8;flex-shrink:0">→</div>
      <div style="flex:1;min-width:120px;background:#F0FDF4;border-radius:6px;
           padding:8px 12px;border-left:3px solid #16A34A">
        <div style="font-size:10px;color:#16A34A;font-weight:700;margin-bottom:3px">AHORA</div>
        <div style="font-size:13px;color:#14532D;font-family:monospace;font-weight:600">
          {ahora}
        </div>
      </div>
    </div>
    {f'<div style="margin-top:8px;font-size:11px;color:#64748B;font-style:italic">{motivo}</div>' if motivo else ''}
  </div>
</div>"""


def _tarjeta_nuevo(c: dict) -> str:
    """Tarjeta para nuevo producto detectado."""
    marca   = _get_marca_style(c.get("competidor",""))
    producto = c.get("nombre_producto", "—")
    fecha = c.get("fecha_cambio","")
    if fecha:
        try:
            from datetime import datetime as dt
            fecha = dt.fromisoformat(str(fecha)).strftime("%d/%m/%Y %H:%M")
        except Exception:
            pass
    return f"""
<div style="border:1px solid {marca['border']};border-left:4px solid {marca['border']};
     border-radius:8px;margin-bottom:8px;background:#fff;padding:12px 16px;
     display:flex;align-items:center;justify-content:space-between">
  <div>
    <span style="font-size:11px;font-weight:800;text-transform:uppercase;
          color:{marca['border']}">{marca['label']}</span>
    <span style="font-size:13px;font-weight:600;color:#0F172A;margin-left:10px">
      ✨ {producto}
    </span>
  </div>
  <span style="font-size:11px;color:#94A3B8;font-family:monospace">{fecha}</span>
</div>"""


def _kpi_box(valor: str, label: str, color: str, bg: str) -> str:
    return f"""<div style="flex:1;min-width:100px;background:{bg};border-radius:8px;
     padding:14px 16px;text-align:center;border:1px solid {color}20">
  <div style="font-size:28px;font-weight:800;color:{color};line-height:1">{valor}</div>
  <div style="font-size:11px;color:{color};margin-top:4px;font-weight:600;
       text-transform:uppercase;letter-spacing:.05em">{label}</div>
</div>"""


def _tarjeta_accionable(c: dict) -> str:
    """Tarjeta con contexto accionable para cambios importantes."""
    campo   = NOMBRE_CAMPO.get(c.get("campo_modificado",""), c.get("campo_modificado",""))
    antes   = str(c.get("valor_anterior") or "—")[:120]
    ahora   = str(c.get("valor_nuevo")    or "—")[:120]
    dir_cal = c.get("direccion_calidad", "neutro")
    marca   = _get_marca_style(c.get("competidor",""))
    producto = c.get("nombre_producto", "—")
    contexto = _contexto_cambio(c)

    if dir_cal == "empeoramiento":
        accent = "#DC2626"; accent_bg = "#FEF2F2"; icon = "⚠️"
    elif dir_cal == "mejora":
        accent = "#16A34A"; accent_bg = "#F0FDF4"; icon = "✅"
    else:
        accent = "#64748B"; accent_bg = "#F8FAFC"; icon = "➡️"

    return f"""
<div style="border-radius:10px;margin-bottom:12px;overflow:hidden;
     border:1px solid #E2E8F0;border-left:4px solid {marca['border']}">
  <!-- Cabecera -->
  <div style="background:{marca['bg']};padding:10px 16px;
       display:flex;justify-content:space-between;align-items:center">
    <div>
      <span style="font-size:10px;font-weight:800;text-transform:uppercase;
            letter-spacing:.08em;color:{marca['border']}">{marca['label']}</span>
      <span style="font-size:13px;font-weight:700;color:#0F172A;margin-left:8px">{producto}</span>
    </div>
    <span style="font-size:11px;font-weight:700;color:{accent};background:{accent_bg};
          padding:3px 10px;border-radius:20px">{icon} {campo}</span>
  </div>
  <!-- Antes / Ahora -->
  <div style="background:#fff;padding:12px 16px">
    <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:10px">
      <div style="flex:1;min-width:100px;background:#FEF2F2;border-radius:6px;padding:8px 12px">
        <div style="font-size:9px;font-weight:700;color:#DC2626;text-transform:uppercase;margin-bottom:2px">Antes</div>
        <div style="font-size:13px;color:#7F1D1D;font-family:monospace;text-decoration:line-through">{antes}</div>
      </div>
      <div style="font-size:18px;color:#CBD5E1">→</div>
      <div style="flex:1;min-width:100px;background:#F0FDF4;border-radius:6px;padding:8px 12px">
        <div style="font-size:9px;font-weight:700;color:#16A34A;text-transform:uppercase;margin-bottom:2px">Ahora</div>
        <div style="font-size:13px;color:#14532D;font-family:monospace;font-weight:700">{ahora}</div>
      </div>
    </div>
    {f'<div style="background:{accent_bg};border-radius:6px;padding:8px 12px;font-size:12px;color:{accent};font-weight:500;border-left:3px solid {accent}">{contexto}</div>' if contexto else ''}
  </div>
</div>"""


def _html(cambios: list, titulo: str, subtitulo: str) -> str:
    """
    Email con 3 secciones accionables:
    1. Requiere revisión (empeoramientos con contexto)
    2. A tener en cuenta (mejoras de la competencia)
    3. Nuevos productos
    """
    fecha = datetime.now().strftime("%d/%m/%Y · %H:%M")

    # Clasificar — solo lo que importa
    empeoramientos = [c for c in cambios if c.get("direccion_calidad") == "empeoramiento"
                      and c.get("severidad") in ("critico","alto")]
    mejoras        = [c for c in cambios if c.get("direccion_calidad") == "mejora"
                      and c.get("severidad") in ("critico","alto")]
    nuevos         = [c for c in cambios if c.get("tipo_cambio") == "nuevo_producto"]
    # Claims: cambios donde el campo es claims o cualquier campo de claims
    CAMPOS_CLAIMS = {"claims", "claim_nutricional", "claim_proteinas", "claim_grasa",
                     "claim_sellos", "claim_gama", "claim_seleccion"}
    cambios_claims = [
        c for c in cambios
        if c.get("campo_modificado") in CAMPOS_CLAIMS
        and c.get("tipo_cambio") != "nuevo_producto"
    ]
    # Para claims de campo "claims", solo mostrar si hay diff real de pills
    cambios_claims_con_diff = []
    for c in cambios_claims:
        if c.get("campo_modificado") == "claims":
            añ, el = _diff_claims(c.get("valor_anterior"), c.get("valor_nuevo"))
            if añ or el:
                cambios_claims_con_diff.append(c)
        else:
            # Para campos individuales (claim_sellos, etc.), mostrar si hay cambio real
            if str(c.get("valor_anterior","")) != str(c.get("valor_nuevo","")):
                cambios_claims_con_diff.append(c)

    n_crit = sum(1 for c in cambios if c.get("severidad") == "critico")
    n_alto = sum(1 for c in cambios if c.get("severidad") == "alto")

    # KPIs
    kpis = f"""
<div style="display:flex;gap:10px;flex-wrap:wrap;padding:20px 28px;
     border-bottom:1px solid #E2E8F0;background:#FAFAFA">
  {_kpi_box(str(n_crit),                       "Críticos",       "#DC2626", "#FEF2F2")}
  {_kpi_box(str(n_alto),                        "Altos",          "#D97706", "#FFFBEB")}
  {_kpi_box(str(len(cambios_claims_con_diff)),  "Claims cambiados","#0891B2", "#ECFEFF")}
  {_kpi_box(str(len(mejoras)),                  "Mejoras",        "#16A34A", "#F0FDF4")}
  {_kpi_box(str(len(nuevos)),                   "Nuevos prods",   "#7C3AED", "#F5F3FF")}
</div>"""

    # ── SECCIÓN 0: Cambios en Claims (PRIORIDAD ALTA para tu jefa) ──
    sec_claims = ""
    if cambios_claims_con_diff:
        tarjetas_c = "".join(
            _tarjeta_claim(c) if c.get("campo_modificado") == "claims"
            else _tarjeta_accionable(c)
            for c in cambios_claims_con_diff[:10]
        )
        sec_claims = f"""
<div style="padding:20px 28px 12px;border-bottom:1px solid #A5F3FC">
  <div style="font-size:13px;font-weight:800;color:#0891B2;margin-bottom:6px;
       display:flex;align-items:center;gap:8px;text-transform:uppercase;letter-spacing:.04em">
    🏷️ Cambios en Claims de Packaging
    <span style="font-size:11px;background:#ECFEFF;color:#0891B2;padding:2px 8px;
          border-radius:10px;font-weight:700">{len(cambios_claims_con_diff)}</span>
  </div>
  <p style="margin:0 0 14px;font-size:12px;color:#475569">
    Claims añadidos, retirados o modificados en el packaging de la competencia.
    Se indica el posible motivo estratégico.
  </p>
  {tarjetas_c}
</div>"""

    # ── SECCIÓN 1: Requiere revisión ──
    sec_empeora = ""
    if empeoramientos:
        tarjetas = "".join(_tarjeta_accionable(c) for c in empeoramientos[:8])
        sec_empeora = f"""
<div style="padding:20px 28px 12px;border-bottom:1px solid #FEE2E2">
  <div style="font-size:13px;font-weight:800;color:#DC2626;margin-bottom:14px;
       display:flex;align-items:center;gap:8px;text-transform:uppercase;letter-spacing:.04em">
    ⚠️ Requiere revisión
    <span style="font-size:11px;background:#FEE2E2;color:#DC2626;padding:2px 8px;
          border-radius:10px;font-weight:700">{len(empeoramientos)}</span>
  </div>
  {tarjetas}
</div>"""

    # ── SECCIÓN 2: A tener en cuenta ──
    sec_mejora = ""
    if mejoras:
        tarjetas = "".join(_tarjeta_accionable(c) for c in mejoras[:6])
        sec_mejora = f"""
<div style="padding:20px 28px 12px;border-bottom:1px solid #DCFCE7">
  <div style="font-size:13px;font-weight:800;color:#16A34A;margin-bottom:14px;
       display:flex;align-items:center;gap:8px;text-transform:uppercase;letter-spacing:.04em">
    👀 A tener en cuenta
    <span style="font-size:11px;background:#DCFCE7;color:#16A34A;padding:2px 8px;
          border-radius:10px;font-weight:700">{len(mejoras)}</span>
  </div>
  {tarjetas}
</div>"""

    # ── SECCIÓN 3: Nuevos productos ──
    sec_nuevos = ""
    if nuevos:
        lista = "".join(_tarjeta_nuevo(c) for c in nuevos[:10])
        sec_nuevos = f"""
<div style="padding:20px 28px 12px">
  <div style="font-size:13px;font-weight:800;color:#7C3AED;margin-bottom:14px;
       display:flex;align-items:center;gap:8px;text-transform:uppercase;letter-spacing:.04em">
    ✨ Nuevos productos detectados
    <span style="font-size:11px;background:#EDE9FE;color:#7C3AED;padding:2px 8px;
          border-radius:10px;font-weight:700">{len(nuevos)}</span>
  </div>
  {lista}
</div>"""

    aviso_vacio = ""
    if not empeoramientos and not mejoras and not nuevos and not cambios_claims_con_diff:
        aviso_vacio = """
<div style="padding:48px;text-align:center">
  <div style="font-size:32px;margin-bottom:8px">✅</div>
  <div style="font-size:15px;font-weight:700;color:#0F172A;margin-bottom:4px">Sin novedades relevantes</div>
  <div style="font-size:13px;color:#94A3B8">No se detectaron cambios que requieran atención hoy.</div>
</div>"""

    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
</head>
<body style="font-family:Arial,sans-serif;background:#F1F5F9;margin:0;padding:20px 0">
<div style="max-width:680px;margin:0 auto">

  <!-- HEADER -->
  <div style="background:#0F172A;border-radius:10px 10px 0 0;padding:20px 28px;
       display:flex;align-items:center;justify-content:space-between">
    <div>
      <div style="color:#fff;font-size:11px;font-weight:700;text-transform:uppercase;
           letter-spacing:.1em;color:#BA0C2F;margin-bottom:4px">Tello · Intel Competitiva</div>
      <div style="color:#fff;font-size:18px;font-weight:800">{titulo}</div>
    </div>
    <div style="text-align:right">
      <div style="color:rgba(255,255,255,.4);font-size:11px;font-family:monospace">{fecha}</div>
      <div style="color:rgba(255,255,255,.3);font-size:10px;margin-top:2px">{len(cambios)} cambios totales</div>
    </div>
  </div>

  <!-- BODY -->
  <div style="background:#fff;border-radius:0 0 10px 10px;
       box-shadow:0 4px 20px rgba(0,0,0,.08);overflow:hidden">

    <!-- Subtítulo -->
    <div style="padding:14px 28px;background:#FFFBEB;border-bottom:1px solid #FDE68A">
      <p style="margin:0;font-size:13px;color:#92400E;font-weight:500">{subtitulo}</p>
    </div>

    {kpis}
    {sec_claims}
    {sec_empeora}
    {sec_mejora}
    {sec_nuevos}
    {aviso_vacio}

    <!-- CTA + FOOTER -->
    <div style="padding:20px 28px;background:#F8FAFC;border-top:1px solid #E2E8F0;text-align:center">
      <div style="background:#fff;border:1px solid #E2E8F0;border-radius:8px;
           padding:12px 16px;margin-bottom:12px;display:inline-block;text-align:left">
        <div style="font-size:11px;font-weight:700;color:#64748B;text-transform:uppercase;
             letter-spacing:.06em;margin-bottom:4px">📊 Ver análisis completo</div>
        <div style="font-size:12px;color:#475569;font-family:monospace">
          Abre el archivo <strong>dashboard_conectado.html</strong> en tu navegador
        </div>
      </div>
      <p style="margin:0;font-size:10px;color:#94A3B8">
        Generado automáticamente · Agente de Inteligencia Competitiva · Tello · Etiquetado
      </p>
    </div>
  </div>
</div>
</body></html>"""


# ---------------------------------------------------------------------------
# ALERTA: Nuevos productos detectados en la última hora
# ---------------------------------------------------------------------------
def alerta_nuevos_productos():
    hace_una_hora = datetime.now() - timedelta(hours=1)
    # Ignorar cambios anteriores a FECHA_BASELINE (período de calibración/setup)
    desde = max(hace_una_hora, datetime.fromisoformat(FECHA_BASELINE))
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM historial_cambios
                WHERE tipo_cambio = 'nuevo_producto'
                  AND fecha_cambio >= %s
                  AND alerta_enviada = FALSE
                ORDER BY competidor, fecha_cambio DESC
            """, (desde,))
            nuevos = [dict(r) for r in cur.fetchall()]

    if not nuevos:
        logger.info("Sin nuevos productos en la última hora")
        return

    asunto = f"[TELLO] {len(nuevos)} nuevo(s) producto(s) detectado(s) en competencia"
    subtitulo = f"Se han detectado <strong>{len(nuevos)} producto(s) nuevo(s)</strong> en el catálogo de la competencia en la última hora."
    html = _html(nuevos, "🆕 Nuevos Productos Detectados", subtitulo)
    _enviar_email(asunto, html)

    # Marcar como enviadas
    ids = [c["id"] for c in nuevos]
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE historial_cambios SET alerta_enviada=TRUE, alerta_enviada_at=NOW() WHERE id=ANY(%s)", (ids,))
            conn.commit()

    logger.info(f"Alerta nuevos productos enviada: {len(nuevos)} productos")


# ---------------------------------------------------------------------------
# INFORME: Resumen diario de todos los cambios de las últimas 24h
# ---------------------------------------------------------------------------
def _es_cambio_real(c: dict) -> bool:
    """
    Devuelve False si el cambio es un falso positivo numérico
    (ej. 6.10 → 6.1, 1.90 → 1.9 son el mismo valor).
    """
    antes = c.get("valor_anterior")
    ahora = c.get("valor_nuevo")
    if antes is None or ahora is None:
        return True
    try:
        return round(float(str(antes).replace(",",".")), 3) != round(float(str(ahora).replace(",",".")), 3)
    except (ValueError, TypeError):
        return True  # Si no son números, asumir que es cambio real


def informe_diario():
    hace_24h = datetime.now() - timedelta(hours=24)
    # Ignorar cambios anteriores a FECHA_BASELINE (período de calibración/setup)
    desde = max(hace_24h, datetime.fromisoformat(FECHA_BASELINE))
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM historial_cambios
                WHERE fecha_cambio >= %s
                ORDER BY
                    CASE direccion_calidad WHEN 'empeoramiento' THEN 1 WHEN 'mejora' THEN 2 ELSE 3 END,
                    CASE severidad WHEN 'critico' THEN 1 WHEN 'alto' THEN 2 WHEN 'medio' THEN 3 ELSE 4 END,
                    competidor, fecha_cambio DESC
            """, (desde,))
            todos = [dict(r) for r in cur.fetchall()]

    # Filtrar falsos positivos numéricos (6.10 = 6.1, etc.)
    cambios = [c for c in todos if _es_cambio_real(c)]

    if not cambios:
        logger.info("Sin cambios reales en las últimas 24h — no se envía informe")
        return

    n_crit  = sum(1 for c in cambios if c["severidad"] == "critico")
    n_alto  = sum(1 for c in cambios if c["severidad"] == "alto")
    n_nuevo = sum(1 for c in cambios if c["tipo_cambio"] == "nuevo_producto")

    # Asunto dinámico que cuenta la noticia principal
    asunto = _asunto_dinamico(cambios)
    subtitulo = (
        f"Resumen de las últimas 24 horas: "
        f"<strong>{n_crit} críticos</strong>, "
        f"<strong>{n_alto} altos</strong>, "
        f"<strong>{n_nuevo} productos nuevos</strong>. "
        f"Solo se muestran los cambios que requieren atención."
    )
    html = _html(cambios, "📋 Informe Diario · Intel Competitiva", subtitulo)
    _enviar_email(asunto, html)
    logger.info(f"Informe diario enviado: {len(cambios)} cambios")


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--tipo", choices=["nuevos", "informe"], required=True)
    args = parser.parse_args()

    if args.tipo == "nuevos":
        alerta_nuevos_productos()
    elif args.tipo == "informe":
        informe_diario()
