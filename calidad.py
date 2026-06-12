# =============================================================================
# calidad.py — Motor de clasificación de calidad para cambios en etiquetado
# Fuentes: RD 474/2014, Reg. 1924/2006, AESAN, OCU, RD 142/2026
# =============================================================================

from typing import Optional


# ---------------------------------------------------------------------------
# UMBRALES NUMÉRICOS (por 100g)
# Fuente: Reg. 1924/2006, AESAN, OCU, RD 474/2014
# ---------------------------------------------------------------------------

# Sal (g/100g) — AESAN considera "alto en sal" > 1.25 g/100g
SAL_EXCELENTE  = 1.0
SAL_BUENA      = 1.25
SAL_ESTANDAR   = 2.0

# Grasa total (g/100g)
GRASA_BAJO_EN_GRASA = 3.0   # Reg. 1924/2006: "bajo en grasa" ≤ 3g
GRASA_BUENA         = 5.0
GRASA_ESTANDAR      = 10.0

# Proteínas (g/100g) — "alto en proteínas" si ≥ 20% del valor energético
# En jamón cocido (~105 kcal/100g): ≥ 17g proteína ≈ 20% energía
PROTEINA_ALTO = 17.0
PROTEINA_BUENA = 14.0

# % carne declarado — referencia OCU y RD 474/2014
PCT_CARNE_PREMIUM   = 90.0
PCT_CARNE_BUENA     = 85.0
PCT_CARNE_ESTANDAR  = 70.0

# Sal (umbral "reducido en sal" Reg. 1924/2006): reducción ≥ 25% vs comparable
SAL_REDUCIDO_THRESHOLD = 0.25   # 25% de reducción


# ---------------------------------------------------------------------------
# ADITIVOS que penalizan la calidad (presencia = peor calidad)
# ---------------------------------------------------------------------------
ADITIVOS_NEGATIVOS = {
    # Nitritos/nitratos (precursores de nitrosaminas — IARC Grupo 1)
    "E-249": "nitrito potásico",
    "E-250": "nitrito sódico",
    "E-251": "nitrato sódico",
    "E-252": "nitrato potásico",
    # Carragenina (agente ligante/relleno)
    "E-407": "carragenina",
    # Fosfatos (retención de agua)
    "E-450": "difosfatos",
    "E-451": "trifosfatos",
    "E-452": "polifosfatos",
    # Colorantes artificiales
    "E-120": "carmín",
    "E-124": "rojo cochinilla",
    "E-129": "rojo allura",
    # Potenciadores de sabor (enmascaran baja calidad)
    "E-621": "glutamato monosódico",
    "E-627": "guanilato disódico",
    "E-631": "inosinato disódico",
}

# Ingredientes de relleno que penalizan la calidad
INGREDIENTES_RELLENO = [
    "almidón", "fécula", "almidón modificado",
    "proteína de soja", "proteína de leche", "proteínas lácteas",
    "proteína vegetal", "caseinato", "suero de leche",
    "carragenina", "konjac", "goma guar", "goma xantana",
]

# Claims que indican MEJORA de calidad
CLAIMS_MEJORA = [
    "sin nitritos", "sin nitritos añadidos",
    "sin fosfatos", "sin fosfatos añadidos",
    "reducido en sal", "bajo en sal",
    "bajo en grasa", "sin grasa",
    "alto en proteínas", "fuente de proteínas",
    "sin conservantes", "sin colorantes",
    "natural", "elaboración artesana",
    "extra",   # categoría legal más exigente
]

# Claims que indican EMPEORAMIENTO o son señales de alerta
CLAIMS_SOSPECHOSOS = [
    "sin nitritos añadidos",   # puede ser greenwashing (nitratos naturales)
]


# ---------------------------------------------------------------------------
# Función principal: evalúa si un cambio es mejora, empeoramiento o neutro
# ---------------------------------------------------------------------------

def clasificar_cambio(campo: str,
                      valor_anterior,
                      valor_nuevo,
                      nombre_producto: str = "") -> dict:
    """
    Devuelve un dict con:
      - direccion: 'mejora' | 'empeoramiento' | 'neutro'
      - prioridad: 'critica' | 'alta' | 'media' | 'baja'
      - motivo: str explicando el razonamiento
    """
    campo = campo.lower()

    # --- CAMPOS NUMÉRICOS ---

    if campo == "sal_g":
        return _evaluar_sal(valor_anterior, valor_nuevo)

    if campo == "grasas_g":
        return _evaluar_grasa(valor_anterior, valor_nuevo)

    if campo == "grasas_saturadas_g":
        return _evaluar_numerico_inverso(
            valor_anterior, valor_nuevo,
            nombre="grasas saturadas",
            umbral_mejora_significativa=1.0
        )

    if campo == "proteinas_g":
        return _evaluar_proteinas(valor_anterior, valor_nuevo)

    if campo == "porcentaje_carne":
        return _evaluar_porcentaje_carne(valor_anterior, valor_nuevo)

    if campo == "kcal":
        # Reducción de kcal en productos magros es mejora; en cárnicos curados es neutra
        return _evaluar_numerico_inverso(
            valor_anterior, valor_nuevo,
            nombre="calorías",
            umbral_mejora_significativa=20
        )

    if campo == "azucares_g":
        return _evaluar_numerico_inverso(
            valor_anterior, valor_nuevo,
            nombre="azúcares",
            umbral_mejora_significativa=0.5
        )

    if campo == "fibra_g":
        return _evaluar_numerico_directo(
            valor_anterior, valor_nuevo,
            nombre="fibra",
            umbral_mejora_significativa=0.5
        )

    # --- INGREDIENTES ---
    if campo == "ingredientes":
        return _evaluar_ingredientes(valor_anterior, valor_nuevo)

    # --- ALÉRGENOS ---
    if campo == "alergenos":
        return _evaluar_alergenos(valor_anterior, valor_nuevo)

    # --- CLAIMS ---
    if campo == "claims":
        return _evaluar_claims(valor_anterior, valor_nuevo)

    # --- NUEVO PRODUCTO ---
    if campo == "nuevo_producto":
        return {
            "direccion": "neutro",
            "prioridad": "media",
            "motivo": "Nuevo producto detectado en catálogo"
        }

    return {
        "direccion": "neutro",
        "prioridad": "baja",
        "motivo": f"Cambio en {campo}"
    }


# ---------------------------------------------------------------------------
# Evaluadores específicos
# ---------------------------------------------------------------------------

def _evaluar_sal(antes, ahora) -> dict:
    try:
        a, n = float(antes), float(ahora)
    except (TypeError, ValueError):
        return {"direccion": "neutro", "prioridad": "baja", "motivo": "Cambio en sal"}

    diff = n - a
    pct_cambio = abs(diff) / a if a else 0

    if diff < 0:  # Bajada de sal → MEJORA
        if n <= SAL_EXCELENTE:
            return {"direccion": "mejora", "prioridad": "alta",
                    "motivo": f"Sal reducida a {n}g/100g (excelente, ≤{SAL_EXCELENTE}g)"}
        elif n <= SAL_BUENA:
            return {"direccion": "mejora", "prioridad": "alta",
                    "motivo": f"Sal reducida a {n}g/100g (por debajo umbral AESAN {SAL_BUENA}g)"}
        elif pct_cambio >= SAL_REDUCIDO_THRESHOLD:
            return {"direccion": "mejora", "prioridad": "media",
                    "motivo": f"Sal reducida {pct_cambio:.0%}: de {a}g a {n}g/100g (cumple 'reducido en sal')"}
        else:
            return {"direccion": "mejora", "prioridad": "baja",
                    "motivo": f"Sal ligeramente reducida: {a}g → {n}g/100g"}
    else:  # Subida de sal → EMPEORAMIENTO
        if n > SAL_ESTANDAR:
            return {"direccion": "empeoramiento", "prioridad": "critica",
                    "motivo": f"Sal aumentada a {n}g/100g (zona muy alta, >{SAL_ESTANDAR}g)"}
        elif n > SAL_BUENA and a <= SAL_BUENA:
            return {"direccion": "empeoramiento", "prioridad": "critica",
                    "motivo": f"Sal supera umbral AESAN: {a}g → {n}g/100g (>{SAL_BUENA}g)"}
        else:
            return {"direccion": "empeoramiento", "prioridad": "alta",
                    "motivo": f"Sal aumentada: {a}g → {n}g/100g"}


def _evaluar_grasa(antes, ahora) -> dict:
    try:
        a, n = float(antes), float(ahora)
    except (TypeError, ValueError):
        return {"direccion": "neutro", "prioridad": "baja", "motivo": "Cambio en grasa"}

    diff = n - a
    if diff < 0:
        if n <= GRASA_BAJO_EN_GRASA:
            return {"direccion": "mejora", "prioridad": "alta",
                    "motivo": f"Grasa reducida a {n}g/100g (cumple 'bajo en grasa' Reg.1924/2006)"}
        return {"direccion": "mejora", "prioridad": "media",
                "motivo": f"Grasa reducida: {a}g → {n}g/100g"}
    else:
        if n > GRASA_ESTANDAR:
            return {"direccion": "empeoramiento", "prioridad": "critica",
                    "motivo": f"Grasa muy elevada: {a}g → {n}g/100g (>{GRASA_ESTANDAR}g)"}
        return {"direccion": "empeoramiento", "prioridad": "alta",
                "motivo": f"Grasa aumentada: {a}g → {n}g/100g"}


def _evaluar_proteinas(antes, ahora) -> dict:
    try:
        a, n = float(antes), float(ahora)
    except (TypeError, ValueError):
        return {"direccion": "neutro", "prioridad": "baja", "motivo": "Cambio en proteínas"}

    diff = n - a
    if diff > 0:
        if n >= PROTEINA_ALTO:
            return {"direccion": "mejora", "prioridad": "alta",
                    "motivo": f"Proteínas aumentadas a {n}g/100g (cumple 'alto en proteínas')"}
        return {"direccion": "mejora", "prioridad": "media",
                "motivo": f"Proteínas aumentadas: {a}g → {n}g/100g"}
    else:
        if n < PROTEINA_BUENA:
            return {"direccion": "empeoramiento", "prioridad": "critica",
                    "motivo": f"Proteínas muy bajas: {a}g → {n}g/100g (<{PROTEINA_BUENA}g indica dilución con relleno)"}
        return {"direccion": "empeoramiento", "prioridad": "alta",
                "motivo": f"Proteínas reducidas: {a}g → {n}g/100g"}


def _evaluar_porcentaje_carne(antes, ahora) -> dict:
    try:
        a, n = float(antes), float(ahora)
    except (TypeError, ValueError):
        return {"direccion": "neutro", "prioridad": "baja", "motivo": "Cambio en % carne"}

    diff = n - a
    if diff > 0:
        if n >= PCT_CARNE_PREMIUM:
            return {"direccion": "mejora", "prioridad": "critica",
                    "motivo": f"% carne aumentado a {n}% (premium ≥{PCT_CARNE_PREMIUM}%)"}
        if n >= PCT_CARNE_BUENA:
            return {"direccion": "mejora", "prioridad": "alta",
                    "motivo": f"% carne aumentado a {n}% (buena calidad ≥{PCT_CARNE_BUENA}%)"}
        return {"direccion": "mejora", "prioridad": "media",
                "motivo": f"% carne aumentado: {a}% → {n}%"}
    else:
        if n < PCT_CARNE_ESTANDAR:
            return {"direccion": "empeoramiento", "prioridad": "critica",
                    "motivo": f"% carne muy bajo: {a}% → {n}% (fiambre territory <{PCT_CARNE_ESTANDAR}%)"}
        if a >= PCT_CARNE_BUENA and n < PCT_CARNE_BUENA:
            return {"direccion": "empeoramiento", "prioridad": "critica",
                    "motivo": f"% carne cae de calidad extra: {a}% → {n}%"}
        return {"direccion": "empeoramiento", "prioridad": "critica",
                "motivo": f"% carne reducido: {a}% → {n}% — posible reformulación"}


def _evaluar_numerico_inverso(antes, ahora, nombre, umbral_mejora_significativa=1.0) -> dict:
    """Para campos donde bajar = mejora (grasas saturadas, azúcares, kcal)."""
    try:
        a, n = float(antes), float(ahora)
    except (TypeError, ValueError):
        return {"direccion": "neutro", "prioridad": "baja", "motivo": f"Cambio en {nombre}"}
    diff = n - a
    if diff < 0:
        prioridad = "alta" if abs(diff) >= umbral_mejora_significativa else "media"
        return {"direccion": "mejora", "prioridad": prioridad,
                "motivo": f"{nombre.capitalize()} reducido: {a} → {n}/100g"}
    else:
        prioridad = "alta" if abs(diff) >= umbral_mejora_significativa else "media"
        return {"direccion": "empeoramiento", "prioridad": prioridad,
                "motivo": f"{nombre.capitalize()} aumentado: {a} → {n}/100g"}


def _evaluar_numerico_directo(antes, ahora, nombre, umbral_mejora_significativa=0.5) -> dict:
    """Para campos donde subir = mejora (proteínas, fibra)."""
    try:
        a, n = float(antes), float(ahora)
    except (TypeError, ValueError):
        return {"direccion": "neutro", "prioridad": "baja", "motivo": f"Cambio en {nombre}"}
    diff = n - a
    if diff > 0:
        prioridad = "media" if abs(diff) >= umbral_mejora_significativa else "baja"
        return {"direccion": "mejora", "prioridad": prioridad,
                "motivo": f"{nombre.capitalize()} aumentado: {a} → {n}/100g"}
    else:
        prioridad = "media" if abs(diff) >= umbral_mejora_significativa else "baja"
        return {"direccion": "empeoramiento", "prioridad": prioridad,
                "motivo": f"{nombre.capitalize()} reducido: {a} → {n}/100g"}


def _evaluar_ingredientes(antes: Optional[str], ahora: Optional[str]) -> dict:
    antes = (antes or "").lower()
    ahora = (ahora or "").lower()

    mejoras = []
    empeoramientos = []

    # Comprobar aditivos negativos añadidos o eliminados
    for codigo, nombre in ADITIVOS_NEGATIVOS.items():
        codigo_l = codigo.lower()
        estaba = codigo_l in antes
        esta   = codigo_l in ahora
        if estaba and not esta:
            mejoras.append(f"Eliminado {codigo} ({nombre})")
        elif not estaba and esta:
            empeoramientos.append(f"Añadido {codigo} ({nombre})")

    # Comprobar ingredientes de relleno
    for relleno in INGREDIENTES_RELLENO:
        estaba = relleno in antes
        esta   = relleno in ahora
        if estaba and not esta:
            mejoras.append(f"Eliminado relleno: '{relleno}'")
        elif not estaba and esta:
            empeoramientos.append(f"Añadido relleno: '{relleno}'")

    if empeoramientos:
        prioridad = "critica" if any("nitrit" in e.lower() or "carragen" in e.lower() for e in empeoramientos) else "alta"
        return {
            "direccion": "empeoramiento",
            "prioridad": prioridad,
            "motivo": "Ingredientes: " + "; ".join(empeoramientos)
        }
    if mejoras:
        prioridad = "critica" if any("nitrit" in m.lower() for m in mejoras) else "alta"
        return {
            "direccion": "mejora",
            "prioridad": prioridad,
            "motivo": "Ingredientes: " + "; ".join(mejoras)
        }

    return {
        "direccion": "neutro",
        "prioridad": "media",
        "motivo": "Reformulación de ingredientes sin cambios de aditivos clave detectados"
    }


def _evaluar_alergenos(antes, ahora) -> dict:
    """Cualquier cambio en alérgenos es CRÍTICO por implicaciones legales."""
    antes_set = set(antes) if isinstance(antes, list) else set()
    ahora_set = set(ahora)  if isinstance(ahora,  list) else set()

    nuevos   = ahora_set - antes_set
    quitados = antes_set - ahora_set

    if nuevos:
        return {
            "direccion": "empeoramiento",
            "prioridad": "critica",
            "motivo": f"ALÉRGENOS AÑADIDOS: {', '.join(nuevos)} — revisión legal inmediata"
        }
    if quitados:
        return {
            "direccion": "mejora",
            "prioridad": "critica",
            "motivo": f"Alérgenos eliminados: {', '.join(quitados)} — verificar cambio real vs error de etiquetado"
        }
    return {"direccion": "neutro", "prioridad": "baja", "motivo": "Sin cambios en alérgenos declarados"}


def _evaluar_claims(antes, ahora) -> dict:
    antes_l = [c.lower() for c in (antes if isinstance(antes, list) else [])]
    ahora_l = [c.lower() for c in (ahora  if isinstance(ahora,  list) else [])]

    claims_ganados  = [c for c in ahora_l if c not in antes_l]
    claims_perdidos = [c for c in antes_l if c not in ahora_l]

    mejoras       = [c for c in claims_ganados  if any(m in c for m in CLAIMS_MEJORA)]
    empeoramientos = [c for c in claims_perdidos if any(m in c for m in CLAIMS_MEJORA)]

    if empeoramientos:
        return {
            "direccion": "empeoramiento",
            "prioridad": "alta",
            "motivo": f"Claims de calidad eliminados: {', '.join(empeoramientos)}"
        }
    if mejoras:
        prioridad = "critica" if any("nitrit" in m or "sal" in m or "carne" in m for m in mejoras) else "alta"
        return {
            "direccion": "mejora",
            "prioridad": prioridad,
            "motivo": f"Nuevos claims de calidad: {', '.join(mejoras)}"
        }
    if claims_ganados or claims_perdidos:
        return {
            "direccion": "neutro",
            "prioridad": "baja",
            "motivo": f"Cambio en claims: +[{', '.join(claims_ganados)}] -[{', '.join(claims_perdidos)}]"
        }
    return {"direccion": "neutro", "prioridad": "baja", "motivo": "Sin cambios relevantes en claims"}
