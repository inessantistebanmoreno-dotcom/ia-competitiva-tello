-- =============================================================================
-- schema.sql — Esquema PostgreSQL del Agente de Inteligencia Competitiva
-- Tello · Etiquetado · v1.0
-- =============================================================================

-- Extensión para UUID (opcional pero recomendada)
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- =============================================================================
-- TABLA PRINCIPAL: Estado actual de cada producto competidor
-- 1 fila por referencia, se actualiza (UPSERT) en cada ciclo
-- =============================================================================
CREATE TABLE IF NOT EXISTS productos_competencia (
    id                      SERIAL PRIMARY KEY,
    competidor              VARCHAR(50)  NOT NULL,  -- noel | campofrio | elpozo | argal
    nombre_producto         TEXT         NOT NULL,
    url_producto            TEXT         NOT NULL UNIQUE,
    categoria               VARCHAR(100),
    subcategoria            VARCHAR(100),
    formato                 VARCHAR(100),
    gramaje_g               NUMERIC(8,1),

    -- Ingredientes
    ingredientes            TEXT,

    -- Tabla nutricional (por 100g)
    kcal                    NUMERIC(6,1),
    proteinas_g             NUMERIC(5,2),
    grasas_g                NUMERIC(5,2),
    grasas_saturadas_g      NUMERIC(5,2),
    carbohidratos_g         NUMERIC(5,2),
    azucares_g              NUMERIC(5,2),
    fibra_g                 NUMERIC(5,2),
    sal_g                   NUMERIC(5,2),

    -- Alérgenos (array de texto normalizado)
    alergenos               TEXT[]       DEFAULT '{}',

    -- Claims del packaging
    claims                  TEXT[]       DEFAULT '{}',
    porcentaje_carne        NUMERIC(5,1),

    -- Descripción web
    descripcion             TEXT,

    -- Control
    fecha_primera_deteccion TIMESTAMPTZ  DEFAULT NOW(),
    fecha_ultima_actualizacion TIMESTAMPTZ DEFAULT NOW(),
    activo                  BOOLEAN      DEFAULT TRUE,

    -- Hash del contenido para detectar cambios rápidamente
    hash_contenido          VARCHAR(64)
);

CREATE INDEX IF NOT EXISTS idx_productos_competidor ON productos_competencia(competidor);
CREATE INDEX IF NOT EXISTS idx_productos_activo     ON productos_competencia(activo);

-- =============================================================================
-- TABLA HISTORIAL: Registro inmutable de cada cambio detectado
-- Nunca se sobreescribe, solo se inserta
-- =============================================================================
CREATE TABLE IF NOT EXISTS historial_cambios (
    id                  BIGSERIAL    PRIMARY KEY,
    competidor          VARCHAR(50)  NOT NULL,
    nombre_producto     TEXT         NOT NULL,
    url_producto        TEXT         NOT NULL,
    campo_modificado    VARCHAR(100) NOT NULL,
    valor_anterior      TEXT,
    valor_nuevo         TEXT,
    fecha_cambio        TIMESTAMPTZ  DEFAULT NOW(),
    tipo_cambio         VARCHAR(50)  NOT NULL,   -- ingredientes | nutricional | alergenos | claims | nuevo_producto | baja_producto
    severidad           VARCHAR(20)  NOT NULL,   -- critico | alto | medio | bajo
    alerta_enviada      BOOLEAN      DEFAULT FALSE,
    alerta_enviada_at   TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_historial_competidor ON historial_cambios(competidor);
CREATE INDEX IF NOT EXISTS idx_historial_fecha       ON historial_cambios(fecha_cambio DESC);
CREATE INDEX IF NOT EXISTS idx_historial_severidad   ON historial_cambios(severidad);
CREATE INDEX IF NOT EXISTS idx_historial_alerta      ON historial_cambios(alerta_enviada) WHERE alerta_enviada = FALSE;

-- =============================================================================
-- TABLA LOG: Registro de ejecuciones del scraper
-- =============================================================================
CREATE TABLE IF NOT EXISTS log_ejecuciones (
    id              SERIAL       PRIMARY KEY,
    inicio          TIMESTAMPTZ  DEFAULT NOW(),
    fin             TIMESTAMPTZ,
    competidor      VARCHAR(50),            -- NULL = ciclo completo
    productos_revisados INTEGER  DEFAULT 0,
    cambios_detectados  INTEGER  DEFAULT 0,
    errores         INTEGER      DEFAULT 0,
    estado          VARCHAR(20)  DEFAULT 'en_curso',  -- en_curso | completado | error
    detalle_error   TEXT
);

-- =============================================================================
-- VISTA: Últimos cambios críticos y altos (para el dashboard)
-- =============================================================================
CREATE OR REPLACE VIEW v_alertas_pendientes AS
SELECT
    h.id,
    h.competidor,
    h.nombre_producto,
    h.campo_modificado,
    h.valor_anterior,
    h.valor_nuevo,
    h.fecha_cambio,
    h.severidad,
    h.tipo_cambio
FROM historial_cambios h
WHERE h.alerta_enviada = FALSE
  AND h.severidad IN ('critico', 'alto')
ORDER BY
    CASE h.severidad WHEN 'critico' THEN 1 WHEN 'alto' THEN 2 END,
    h.fecha_cambio DESC;

-- =============================================================================
-- VISTA: Comparativa nutricional por categoría
-- =============================================================================
CREATE OR REPLACE VIEW v_comparativa_nutricional AS
SELECT
    categoria,
    competidor,
    COUNT(*)                        AS num_productos,
    ROUND(AVG(kcal), 1)             AS kcal_media,
    ROUND(AVG(proteinas_g), 2)      AS proteinas_media,
    ROUND(AVG(grasas_g), 2)         AS grasas_media,
    ROUND(AVG(sal_g), 3)            AS sal_media,
    ROUND(AVG(porcentaje_carne), 1) AS pct_carne_medio
FROM productos_competencia
WHERE activo = TRUE
GROUP BY categoria, competidor
ORDER BY categoria, competidor;
