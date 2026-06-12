# Agente de Inteligencia Competitiva — Guía de Instalación
**Tello · Etiquetado · v1.0**

---

## Arquitectura del proyecto

```
agente-competencia/
├── main.py                    ← Orquestador principal
├── config.py                  ← Configuración centralizada
├── alertas.py                 ← Sistema de alertas por email
├── requirements.txt
├── .env.example               ← Plantilla de variables de entorno
├── scrapers/
│   ├── __init__.py
│   ├── base_scraper.py        ← Clase base (Playwright + Claude Vision)
│   ├── noel_scraper.py
│   ├── campofrio_scraper.py
│   ├── elpozo_scraper.py      ← Usa Claude Vision para tablas en imagen
│   └── argal_scraper.py
└── database/
    ├── schema.sql             ← DDL PostgreSQL (ejecutar una sola vez)
    └── db.py                  ← Capa de acceso a datos (upsert + historial)
```

---

## Prerrequisitos

- Python 3.11+
- PostgreSQL 14+ (o cuenta en Supabase — gratuita)
- API Key de Anthropic (claude.ai → Settings → API Keys)
- Email corporativo con SMTP habilitado (Office 365)

---

## Instalación paso a paso

### 1. Clonar / descargar el proyecto

```bash
cd tu-carpeta-de-proyectos
```

### 2. Crear entorno virtual e instalar dependencias

```bash
python -m venv venv
# Windows:
venv\Scripts\activate
# Mac/Linux:
source venv/bin/activate

pip install -r requirements.txt
playwright install chromium   # descarga el navegador headless (~120 MB)
```

### 3. Configurar variables de entorno

```bash
cp .env.example .env
# Editar .env con las credenciales reales
```

Rellenar en `.env`:
- `ANTHROPIC_API_KEY` → tu clave de Anthropic
- `DATABASE_URL` → conexión a PostgreSQL/Supabase
- `SMTP_*` → credenciales del correo corporativo
- `EMAIL_TO` → destinatario(s) de las alertas (separados por coma)

### 4. Crear la base de datos

En psql o Supabase SQL Editor:

```sql
\i database/schema.sql
```

O copiar y pegar el contenido de `database/schema.sql` en el editor de Supabase.

### 5. Probar con un solo competidor

```bash
python main.py --competidor noel --sin-alertas
```

Esto ejecuta el scraping de Noel sin enviar emails, para verificar que todo funciona.

---

## Uso habitual

```bash
# Ciclo completo (todos los competidores) con alertas
python main.py

# Solo un competidor
python main.py --competidor campofrio

# Enviar resumen diario de novedades
python main.py --resumen-diario
```

---

## Automatización con Cron (Linux/Mac) o Task Scheduler (Windows)

### Cron — cada 6 horas

```bash
crontab -e
# Añadir:
0 */6 * * *  cd /ruta/proyecto && venv/bin/python main.py >> logs/cron.log 2>&1

# Resumen diario a las 8:00
0 8 * * *    cd /ruta/proyecto && venv/bin/python main.py --resumen-diario >> logs/cron.log 2>&1
```

### Windows Task Scheduler

1. Abrir "Programador de tareas" → Crear tarea básica
2. Desencadenador: Diariamente, repetir cada 6 horas
3. Acción: Iniciar programa → `python.exe`  
   Argumentos: `main.py`  
   Carpeta: ruta del proyecto

### n8n (si se prefiere orquestación visual)

Crear un workflow con:
- **Cron Trigger** → cada 6 horas
- **Execute Command** → `python main.py`
- El propio `main.py` gestiona el envío de alertas

---

## Consultas útiles en PostgreSQL

```sql
-- Ver últimos cambios detectados
SELECT * FROM historial_cambios ORDER BY fecha_cambio DESC LIMIT 20;

-- Cambios críticos pendientes de revisar
SELECT * FROM v_alertas_pendientes;

-- Comparativa nutricional por categoría
SELECT * FROM v_comparativa_nutricional WHERE categoria = 'Jamón Cocido';

-- Productos nuevos esta semana
SELECT competidor, nombre_producto, fecha_primera_deteccion
FROM productos_competencia
WHERE fecha_primera_deteccion >= NOW() - INTERVAL '7 days'
ORDER BY fecha_primera_deteccion DESC;
```

---

## Ajustar selectores CSS cuando cambia una web

Los scrapers usan selectores CSS para localizar el contenido. Si una web cambia su estructura:

1. Abrir la web en Chrome → F12 → Inspector
2. Localizar el elemento (ingredientes, tabla nutricional, etc.)
3. Copiar el selector CSS
4. Actualizar el selector en el scraper correspondiente (`scrapers/MARCA_scraper.py`)

Los scrapers tienen selectores múltiples separados por coma como fallback, lo que reduce la frecuencia de roturas.

---

## Notas sobre El Pozo (Claude Vision)

El Pozo muestra la tabla nutricional como imagen. El scraper captura un screenshot del elemento y lo envía a la API de Claude Vision para extraer los valores. Esto consume tokens de la API (aprox. 0,01 € por producto). Con ~200 productos de El Pozo, el coste por ciclo es de ~2 €.

---

## Soporte

Para dudas técnicas sobre el proyecto: bgonzalez@tello.es
