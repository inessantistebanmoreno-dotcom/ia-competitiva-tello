@echo off
cd /d "C:\Users\temp03\Desktop\INÉS_PRÁCTICAS\TRABAJO_JUNIO_INÉS\Agente de análisis competencia"
python alertas_scheduler.py --tipo nuevos >> agente_etiquetado.log 2>&1
