import os
import json
import requests
from flask import Flask, request
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

app = Flask(__name__)

# ============================================================
# CONFIGURACIÓN - Completá estos datos
# ============================================================
GEMINI_API_KEY = "AQ.Ab8RN6KX6OwfAMwZE8sveZH2dHkVzzHgwnswPDbFug_Tc6mbvg"
TWILIO_ACCOUNT_SID = "AC874fae42c93cc8ae5c1cab13576de6c0"
TWILIO_AUTH_TOKEN = "619e308f13603ee7c9c85f4c57a2ce84"
GOOGLE_SHEET_ID = "1om_6E7m6KB63oKGlnxwCsr4Q9812i5b_t79fmigFh9k"
CREDENTIALS_FILE = "credenciales.json"  # El archivo JSON que descargaste
# ============================================================

def conectar_sheets():
    """Conecta con Google Sheets"""
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scopes)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(GOOGLE_SHEET_ID).sheet1
    return sheet

def analizar_mensaje_con_gemini(mensaje):
    """Usa Gemini para analizar el mensaje y extraer datos financieros"""
    
    prompt = f"""Eres un asistente que analiza mensajes de gastos e ingresos personales.
    
Analizá este mensaje: "{mensaje}"

Extraé la información y respondé ÚNICAMENTE con un JSON válido con este formato exacto:
{{
  "es_financiero": true/false,
  "tipo": "gasto" o "ingreso",
  "monto": número (solo el número, sin símbolos),
  "categoria": "una de estas: alimentación, transporte, servicios, salud, entretenimiento, ropa, trabajo, transferencia, otro",
  "metodo": "efectivo" o "transferencia" o "tarjeta" o "desconocido",
  "descripcion": "descripción breve en 3-5 palabras"
}}

Si el mensaje NO es sobre gastos o ingresos, respondé:
{{"es_financiero": false}}

Ejemplos:
- "pagué 500 de luz" → gasto, 500, servicios, desconocido
- "me depositaron 3000 de sueldo" → ingreso, 3000, trabajo, transferencia  
- "gasté 200 en tacos en efectivo" → gasto, 200, alimentación, efectivo
- "hola como estás" → no financiero"""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1}
    }
    
    response = requests.post(url, json=payload)
    result = response.json()
    
    texto = result["candidates"][0]["content"]["parts"][0]["text"]
    
    # Limpiar el texto por si tiene markdown
    texto = texto.strip()
    if texto.startswith("```"):
        texto = texto.split("```")[1]
        if texto.startswith("json"):
            texto = texto[4:]
    texto = texto.strip()
    
    return json.loads(texto)

def guardar_en_sheets(datos):
    """Guarda el registro en Google Sheets"""
    sheet = conectar_sheets()
    
    fecha = datetime.now().strftime("%d/%m/%Y %H:%M")
    
    fila = [
        fecha,
        datos["tipo"].upper(),
        datos["monto"],
        datos["categoria"],
        datos["metodo"],
        datos["descripcion"]
    ]
    
    sheet.append_row(fila)

def obtener_resumen():
    """Obtiene un resumen de los gastos e ingresos"""
    sheet = conectar_sheets()
    registros = sheet.get_all_records()
    
    if not registros:
        return "No hay registros aún."
    
    total_gastos = sum(float(r["Monto"]) for r in registros if r["Tipo"] == "GASTO")
    total_ingresos = sum(float(r["Monto"]) for r in registros if r["Tipo"] == "INGRESO")
    balance = total_ingresos - total_gastos
    
    resumen = f"""📊 *Resumen de tus finanzas:*
    
💸 Total gastos: ${total_gastos:,.0f}
💰 Total ingresos: ${total_ingresos:,.0f}
📈 Balance: ${balance:,.0f}
📝 Registros totales: {len(registros)}"""
    
    return resumen

@app.route("/webhook", methods=["POST"])
def webhook():
    """Recibe los mensajes de WhatsApp via Twilio"""
    mensaje = request.form.get("Body", "").strip()
    numero_origen = request.form.get("From", "")
    
    resp = MessagingResponse()
    
    # Comando especial para ver resumen
    if mensaje.lower() in ["resumen", "balance", "total"]:
        respuesta = obtener_resumen()
        resp.message(respuesta)
        return str(resp)
    
    try:
        # Analizar el mensaje con Gemini
        datos = analizar_mensaje_con_gemini(mensaje)
        
        if not datos.get("es_financiero"):
            resp.message("No entendí eso como un gasto o ingreso. Contame algo como:\n'gasté 500 en comida'\n'me depositaron 3000 de sueldo'\n\nO escribí *resumen* para ver tu balance 📊")
            return str(resp)
        
        # Guardar en Google Sheets
        guardar_en_sheets(datos)
        
        # Responder confirmación
        emoji = "💸" if datos["tipo"] == "gasto" else "💰"
        tipo_texto = "Gasto" if datos["tipo"] == "gasto" else "Ingreso"
        
        respuesta = f"""{emoji} *{tipo_texto} registrado!*
        
💵 Monto: ${datos['monto']:,}
📂 Categoría: {datos['categoria'].capitalize()}
💳 Método: {datos['metodo'].capitalize()}
📝 {datos['descripcion'].capitalize()}

Escribí *resumen* para ver tu balance 📊"""
        
        resp.message(respuesta)
        
    except Exception as e:
        print(f"Error: {e}")
        resp.message("Hubo un error procesando tu mensaje. Intentá de nuevo 🙏")
    
    return str(resp)

@app.route("/", methods=["GET"])
def home():
    return "Bot de finanzas activo! ✅"

if __name__ == "__main__":
    app.run(debug=True, port=5000)
