-- =============================================================================
-- Migración: añadir columnas del Excel de Noel a productos_competencia
-- Ejecutar en Supabase SQL Editor
-- =============================================================================

ALTER TABLE productos_competencia

  -- Tipo de carne (cerdo, pavo, pollo, mixto, ibérico...)
  ADD COLUMN IF NOT EXISTS tipo_carne         VARCHAR(100),

  -- Foto del producto (URL de la imagen en la web)
  ADD COLUMN IF NOT EXISTS url_foto           TEXT,

  -- Alérgenos como booleanos independientes (además del array genérico)
  ADD COLUMN IF NOT EXISTS sin_gluten         BOOLEAN DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS sin_lactosa        BOOLEAN DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS sin_colorantes     BOOLEAN DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS sin_conservantes   BOOLEAN DEFAULT NULL,

  -- Claims individuales (texto libre extraído del packaging)
  ADD COLUMN IF NOT EXISTS claim_pct_carne       TEXT,   -- "82% de carne", "Alto % carne"
  ADD COLUMN IF NOT EXISTS claim_nutricional      TEXT,   -- "Reducido en sal", "Bajo en grasa"
  ADD COLUMN IF NOT EXISTS claim_proteinas        TEXT,   -- "Alto en proteínas", "Fuente de proteínas"
  ADD COLUMN IF NOT EXISTS claim_grasa            TEXT,   -- "Bajo en grasas saturadas"
  ADD COLUMN IF NOT EXISTS claim_sellos           TEXT,   -- "Sin nitritos", "Bienestar animal", ISO...
  ADD COLUMN IF NOT EXISTS claim_gama             TEXT,   -- "Gama Premium", "Selección", "Extra"
  ADD COLUMN IF NOT EXISTS claim_seleccion        TEXT,   -- "Gran Selección", "Producto selecto"
  ADD COLUMN IF NOT EXISTS claim_conveniencia     TEXT,   -- "Listo para comer", "Sin conservar en frío"
  ADD COLUMN IF NOT EXISTS claim_raciones         TEXT,   -- "4 raciones", "Para 2 personas"
  ADD COLUMN IF NOT EXISTS claim_modo_coccion     TEXT;   -- "A la plancha", "Al horno", "Frío o caliente"

-- Dar permisos de lectura al rol anon (para el dashboard)
GRANT SELECT ON productos_competencia TO anon;
GRANT SELECT ON historial_cambios TO anon;
GRANT SELECT ON log_ejecuciones TO anon;
GRANT SELECT ON v_alertas_pendientes TO anon;
GRANT SELECT ON v_comparativa_nutricional TO anon;
