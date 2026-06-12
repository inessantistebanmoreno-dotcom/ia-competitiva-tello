# =============================================================================
# database/db.py — Capa de acceso a datos (PostgreSQL)
# =============================================================================

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import psycopg2
import psycopg2.extras
from psycopg2.extras import RealDictCursor

from config import DATABASE_URL, CAMBIOS_CRITICOS, CAMBIOS_ALTOS, CAMBIOS_MEDIOS
from calidad import clasificar_cambio

logger = logging.getLogger(__name__)


def get_connection():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NUEVOS_CAMPOS = [
    "tipo_carne", "url_foto",
    "sin_gluten", "sin_lactosa", "sin_colorantes", "sin_conservantes",
    "claim_pct_carne", "claim_nutricional", "claim_proteinas", "claim_grasa",
    "claim_sellos", "claim_gama", "claim_seleccion", "claim_conveniencia",
    "claim_raciones", "claim_modo_coccion",
    "fibra_g", "analisis_ingredientes",
]

def _defaults_nuevos_campos(datos: Dict) -> Dict:
    """Asegura que todos los campos nuevos existen en el dict (con None si no vienen del scraper)."""
    resultado = dict(datos)
    for campo in NUEVOS_CAMPOS:
        resultado.setdefault(campo, None)
    return resultado

def _hash_producto(datos: Dict) -> str:
    """Genera un hash SHA-256 del contenido relevante del producto."""
    campos = [
        "ingredientes", "kcal", "proteinas_g", "grasas_g", "grasas_saturadas_g",
        "carbohidratos_g", "azucares_g", "fibra_g", "sal_g",
        "alergenos", "claims", "porcentaje_carne",
    ]
    contenido = {k: datos.get(k) for k in campos}
    return hashlib.sha256(json.dumps(contenido, sort_keys=True, default=str).encode()).hexdigest()


def _severidad(campo: str) -> str:
    if campo in CAMBIOS_CRITICOS:
        return "critico"
    if campo in CAMBIOS_ALTOS:
        return "alto"
    if campo in CAMBIOS_MEDIOS:
        return "medio"
    return "bajo"


def _tipo_cambio(campo: str) -> str:
    if campo in ("ingredientes",):
        return "ingredientes"
    if campo in ("alergenos",):
        return "alergenos"
    if campo in ("kcal", "proteinas_g", "grasas_g", "grasas_saturadas_g",
                 "carbohidratos_g", "azucares_g", "fibra_g", "sal_g"):
        return "nutricional"
    if campo in ("claims", "porcentaje_carne"):
        return "claims"
    return "otros"


# ---------------------------------------------------------------------------
# Leer estado actual
# ---------------------------------------------------------------------------

def obtener_producto(url: str) -> Optional[Dict]:
    """Devuelve el registro actual de un producto por URL, o None si no existe."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM productos_competencia WHERE url_producto = %s",
                (url,)
            )
            row = cur.fetchone()
            return dict(row) if row else None


# ---------------------------------------------------------------------------
# Guardar / actualizar producto y detectar cambios
# ---------------------------------------------------------------------------

def upsert_producto(datos: Dict) -> List[Dict]:
    """
    Inserta o actualiza un producto. Devuelve lista de cambios detectados
    (dicts con campo, valor_anterior, valor_nuevo, severidad, tipo_cambio).
    """
    url = datos["url_producto"]
    nuevo_hash = _hash_producto(datos)
    existente = obtener_producto(url)
    cambios = []

    with get_connection() as conn:
        with conn.cursor() as cur:

            if existente is None:
                # --- Nuevo producto ---
                cur.execute("""
                    INSERT INTO productos_competencia
                        (competidor, nombre_producto, url_producto, categoria, subcategoria,
                         formato, gramaje_g, tipo_carne, url_foto,
                         ingredientes, kcal, proteinas_g, grasas_g,
                         grasas_saturadas_g, carbohidratos_g, azucares_g, fibra_g, sal_g,
                         alergenos, sin_gluten, sin_lactosa, sin_colorantes, sin_conservantes,
                         claims, porcentaje_carne,
                         claim_pct_carne, claim_nutricional, claim_proteinas, claim_grasa,
                         claim_sellos, claim_gama, claim_seleccion, claim_conveniencia,
                         claim_raciones, claim_modo_coccion,
                         analisis_ingredientes, descripcion, hash_contenido)
                    VALUES
                        (%(competidor)s, %(nombre_producto)s, %(url_producto)s, %(categoria)s,
                         %(subcategoria)s, %(formato)s, %(gramaje_g)s, %(tipo_carne)s, %(url_foto)s,
                         %(ingredientes)s,
                         %(kcal)s, %(proteinas_g)s, %(grasas_g)s, %(grasas_saturadas_g)s,
                         %(carbohidratos_g)s, %(azucares_g)s, %(fibra_g)s, %(sal_g)s,
                         %(alergenos)s, %(sin_gluten)s, %(sin_lactosa)s, %(sin_colorantes)s, %(sin_conservantes)s,
                         %(claims)s, %(porcentaje_carne)s,
                         %(claim_pct_carne)s, %(claim_nutricional)s, %(claim_proteinas)s, %(claim_grasa)s,
                         %(claim_sellos)s, %(claim_gama)s, %(claim_seleccion)s, %(claim_conveniencia)s,
                         %(claim_raciones)s, %(claim_modo_coccion)s,
                         %(analisis_ingredientes)s, %(descripcion)s, %(hash_contenido)s)
                """, {**_defaults_nuevos_campos(datos),
                      "alergenos": datos.get("alergenos", []),
                      "claims": datos.get("claims", []),
                      "analisis_ingredientes": json.dumps(datos.get("analisis_ingredientes")) if datos.get("analisis_ingredientes") else None,
                      "hash_contenido": nuevo_hash})
                conn.commit()

                cambios.append({
                    "campo_modificado": "nuevo_producto",
                    "valor_anterior": None,
                    "valor_nuevo": datos.get("nombre_producto"),
                    "severidad": "medio",
                    "tipo_cambio": "nuevo_producto",
                })
                logger.info(f"[DB] Nuevo producto insertado: {datos.get('nombre_producto')}")

            elif existente["hash_contenido"] != nuevo_hash:
                # --- Producto existente con cambios ---
                campos_comparables = [
                    "ingredientes", "kcal", "proteinas_g", "grasas_g", "grasas_saturadas_g",
                    "carbohidratos_g", "azucares_g", "fibra_g", "sal_g",
                    "alergenos", "sin_gluten", "sin_lactosa", "sin_colorantes", "sin_conservantes",
                    "claims", "porcentaje_carne",
                    "claim_pct_carne", "claim_nutricional", "claim_proteinas", "claim_grasa",
                    "claim_sellos", "claim_gama", "claim_seleccion", "claim_conveniencia",
                    "claim_raciones", "claim_modo_coccion",
                    "tipo_carne", "descripcion",
                ]
                # Campos numéricos — comparar como float redondeado (2.10 == 2.1)
                CAMPOS_NUMERICOS = {
                    "kcal", "proteinas_g", "grasas_g", "grasas_saturadas_g",
                    "carbohidratos_g", "azucares_g", "fibra_g", "sal_g", "porcentaje_carne"
                }
                # Campos de texto con claims — normalizar para evitar falsos positivos
                CAMPOS_CLAIMS = {
                    "claim_pct_carne", "claim_nutricional", "claim_proteinas", "claim_grasa",
                    "claim_sellos", "claim_gama", "claim_seleccion", "claim_conveniencia",
                    "claim_raciones", "claim_modo_coccion", "claims"
                }

                def _norm_texto(t):
                    """
                    Normaliza texto de claim para comparación:
                    - minúsculas, sin tildes, espacios limpios
                    - divide por " / " y deduplica sub-claims
                    - unifica variantes de género (reducida=reducido)
                    """
                    if t is None:
                        return None
                    import unicodedata
                    # Dividir por " / ", normalizar cada parte y deduplicar
                    partes = str(t).split(' / ')
                    norm_partes = set()
                    for p in partes:
                        s = p.lower().strip()
                        s = ''.join(c for c in unicodedata.normalize('NFD', s)
                                    if unicodedata.category(c) != 'Mn')
                        s = ' '.join(s.split())
                        s = s.replace('reducida ', 'reducido ')
                        s = s.replace('braseada', 'braseado')
                        norm_partes.add(s)
                    return ' / '.join(sorted(norm_partes))

                def _norm_lista(lst):
                    """Normaliza lista de claims para comparación."""
                    if not lst:
                        return []
                    items = lst if isinstance(lst, list) else [lst]
                    result = set()
                    for item in items:
                        for sub in str(item).split(' / '):
                            result.add(_norm_texto(sub.strip()))
                    return sorted(result)

                for campo in campos_comparables:
                    v_ant = existente.get(campo)
                    v_nue = datos.get(campo)
                    # Normalizar listas para comparación
                    if isinstance(v_ant, list):
                        v_ant = sorted(v_ant or [])
                    if isinstance(v_nue, list):
                        v_nue = sorted(v_nue or [])
                    # Normalizar números: 2.10 == 2.1
                    if campo in CAMPOS_NUMERICOS:
                        try:
                            v_ant_norm = round(float(v_ant), 3) if v_ant is not None else None
                            v_nue_norm = round(float(v_nue), 3) if v_nue is not None else None
                            if v_ant_norm == v_nue_norm:
                                continue
                        except (TypeError, ValueError):
                            pass
                    # Normalizar claims de texto: "Reducida en Sal" == "Reducido en Sal"
                    if campo in CAMPOS_CLAIMS:
                        if campo == "claims":
                            if _norm_lista(v_ant) == _norm_lista(v_nue):
                                continue
                        else:
                            if _norm_texto(v_ant) == _norm_texto(v_nue):
                                continue
                    if v_ant != v_nue:
                        # Clasificar si el cambio es mejora o empeoramiento de calidad
                        calidad = clasificar_cambio(
                            campo, v_ant, v_nue,
                            nombre_producto=datos.get("nombre_producto", "")
                        )
                        cambios.append({
                            "campo_modificado": campo,
                            "valor_anterior": str(v_ant) if v_ant is not None else None,
                            "valor_nuevo": str(v_nue) if v_nue is not None else None,
                            "severidad": _severidad(campo),
                            "tipo_cambio": _tipo_cambio(campo),
                            "direccion_calidad": calidad["direccion"],   # mejora | empeoramiento | neutro
                            "prioridad_calidad": calidad["prioridad"],   # critica | alta | media | baja
                            "motivo_calidad": calidad["motivo"],
                        })

                # Actualizar tabla principal
                cur.execute("""
                    UPDATE productos_competencia SET
                        ingredientes = %(ingredientes)s,
                        kcal = %(kcal)s, proteinas_g = %(proteinas_g)s,
                        grasas_g = %(grasas_g)s, grasas_saturadas_g = %(grasas_saturadas_g)s,
                        carbohidratos_g = %(carbohidratos_g)s, azucares_g = %(azucares_g)s,
                        fibra_g = %(fibra_g)s, sal_g = %(sal_g)s,
                        alergenos = %(alergenos)s,
                        sin_gluten = %(sin_gluten)s, sin_lactosa = %(sin_lactosa)s,
                        sin_colorantes = %(sin_colorantes)s, sin_conservantes = %(sin_conservantes)s,
                        claims = %(claims)s,
                        claim_pct_carne = %(claim_pct_carne)s, claim_nutricional = %(claim_nutricional)s,
                        claim_proteinas = %(claim_proteinas)s, claim_grasa = %(claim_grasa)s,
                        claim_sellos = %(claim_sellos)s, claim_gama = %(claim_gama)s,
                        claim_seleccion = %(claim_seleccion)s, claim_conveniencia = %(claim_conveniencia)s,
                        claim_raciones = %(claim_raciones)s, claim_modo_coccion = %(claim_modo_coccion)s,
                        tipo_carne = %(tipo_carne)s, url_foto = %(url_foto)s,
                        porcentaje_carne = %(porcentaje_carne)s,
                        analisis_ingredientes = %(analisis_ingredientes)s,
                        descripcion = %(descripcion)s,
                        categoria = %(categoria)s, subcategoria = %(subcategoria)s,
                        formato = %(formato)s, gramaje_g = %(gramaje_g)s,
                        fecha_ultima_actualizacion = NOW(),
                        hash_contenido = %(hash_contenido)s
                    WHERE url_producto = %(url_producto)s
                """, {**_defaults_nuevos_campos(datos),
                      "alergenos": datos.get("alergenos", []),
                      "claims": datos.get("claims", []),
                      "analisis_ingredientes": json.dumps(datos.get("analisis_ingredientes")) if datos.get("analisis_ingredientes") else None,
                      "hash_contenido": nuevo_hash})
                conn.commit()
                logger.info(f"[DB] Actualizado: {datos.get('nombre_producto')} — {len(cambios)} cambios")

            # Insertar cambios en historial
            if cambios:
                for c in cambios:
                    cur.execute("""
                        INSERT INTO historial_cambios
                            (competidor, nombre_producto, url_producto, campo_modificado,
                             valor_anterior, valor_nuevo, tipo_cambio, severidad)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """, (datos["competidor"], datos["nombre_producto"], url,
                          c["campo_modificado"], c["valor_anterior"], c["valor_nuevo"],
                          c["tipo_cambio"], c["severidad"]))
                conn.commit()

    return cambios


def marcar_alertas_enviadas(ids: List[int]):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE historial_cambios
                SET alerta_enviada = TRUE, alerta_enviada_at = NOW()
                WHERE id = ANY(%s)
            """, (ids,))
            conn.commit()


def obtener_alertas_pendientes() -> List[Dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM v_alertas_pendientes")
            return [dict(r) for r in cur.fetchall()]
