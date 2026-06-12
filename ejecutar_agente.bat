@echo off
cd /d "C:\Users\temp03\Desktop\INÉS_PRÁCTICAS\TRABAJO_JUNIO_INÉS\Agente de análisis competencia"
python main.py --competidor noel --sin-alertas >> agente_etiquetado.log 2>&1
python main.py --competidor campofrio --sin-alertas >> agente_etiquetado.log 2>&1
python main.py --competidor elpozo --sin-alertas >> agente_etiquetado.log 2>&1
python main.py --competidor argal --sin-alertas >> agente_etiquetado.log 2>&1
