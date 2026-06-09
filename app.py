import os
import json
import requests
import threading
from flask import Flask, request
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

app = Flask(__name__)

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
GOOGLE_SHEET_ID = "1om_6E7m6KB63oKGlnxwCsr4Q9812i5b_t79fmigFh9k"
GOOGLE_CREDENTIALS_JSON = os.environ.get("GOOGLE_CREDENTIALS")

def conectar_sheets():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(GOOGLE_SHEET_ID).sheet1
    return sheet

def analizar_mensaje(mensaje):
    prompt = f"""Analizá este mensaje de finanzas personales en español: "{mensaje}"

Respondé ÚNICAMENTE con JSON válido, sin markdown ni explicaciones extra.
Ejemplo de respuesta correcta:
{{"es_financiero": true, "tipo": "gasto", "monto": 500, "categoria": "alimentación", "metodo": "efectivo", "descripcion": "empanadas"}}

Reglas:
- tipo: "gasto" o "ingreso"
- monto: solo el número sin símbolos
- categoria: alimentación/transporte/servicios/salud/entretenimiento/ropa/trabajo/otro
- metodo: efectivo/transferencia/tarjeta/desconocido
- descripcion: 1-3 palabras describiendo QUÉ se compró o de dónde viene el dinero (ej: "empanadas", "sueldo", "uber", "luz")

Si NO es sobre dinero: {{"es_financiero": false}}"""

    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://mis-finanzas-xu5y.onrender.com",
            "X-Title": "Mis Finanzas"
        },
        json={
            "model": "openai/gpt-oss-120b:free",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1
        },
        timeout=25
    )
    
    result = response.json()
    
    if "choices" in result:
        texto = result["choices"][0]["message"]["content"]
    elif "error" in result:
        raise Exception(f"OpenRouter error: {result['error']}")
    else:
        raise Exception(f"Respuesta inesperada: {result}")
    
    texto = texto.strip().replace("```json", "").replace("```", "").strip()
    data = json.loads(texto)
    if "descripcion" not in data:
        data["descripcion"] = data.get("categoria", "sin descripción")
    return data

def guardar_en_sheets(datos):
    sheet = conectar_sheets()
    fecha = datetime.now().strftime("%d/%m/%Y")
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
    sheet = conectar_sheets()
    registros = sheet.get_all_records()
    
    if not registros:
        return "No hay registros aún."
    
    total_gastos = sum(float(r["Monto"]) for r in registros if str(r["Tipo"]) == "GASTO")
    total_ingresos = sum(float(r["Monto"]) for r in registros if str(r["Tipo"]) == "INGRESO")
    balance = total_ingresos - total_gastos
    
    return f"""📊 *Resumen de tus finanzas:*

💸 Total gastos: ${total_gastos:,.0f}
💰 Total ingresos: ${total_ingresos:,.0f}
📈 Balance: ${balance:,.0f}
📝 Registros totales: {len(registros)}"""

def enviar_whatsapp(numero, mensaje):
    """Envía mensaje via Twilio API directamente"""
    client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    client.messages.create(
        from_="whatsapp:+14155238886",
        to=numero,
        body=mensaje
    )

def procesar_en_background(mensaje, numero_origen):
    """Procesa el mensaje y responde por WhatsApp en segundo plano"""
    try:
        datos = analizar_mensaje(mensaje)
        
        if not datos.get("es_financiero"):
            enviar_whatsapp(numero_origen, "No entendí eso como un gasto o ingreso. Contame algo como:\n'gasté 500 en comida'\n'me depositaron 3000 de sueldo'\n\nO escribí *resumen* para ver tu balance 📊")
            return
        
        guardar_en_sheets(datos)
        
        emoji = "💸" if datos["tipo"] == "gasto" else "💰"
        tipo_texto = "Gasto" if datos["tipo"] == "gasto" else "Ingreso"
        
        respuesta = f"""{emoji} *{tipo_texto} registrado!*

💵 Monto: ${datos['monto']:,}
📂 Categoría: {datos['categoria'].capitalize()}
💳 Método: {datos['metodo'].capitalize()}
📝 {datos['descripcion'].capitalize()}

Escribí *resumen* para ver tu balance 📊"""
        
        enviar_whatsapp(numero_origen, respuesta)
        
    except Exception as e:
        print(f"Error en background: {e}")
        enviar_whatsapp(numero_origen, "Hubo un error procesando tu mensaje. Intentá de nuevo 🙏")

@app.route("/webhook", methods=["POST"])
def webhook():
    mensaje = request.form.get("Body", "").strip()
    numero_origen = request.form.get("From", "")
    
    # Responder inmediato a Twilio (evita timeout)
    resp = MessagingResponse()
    
    if mensaje.lower() in ["resumen", "balance", "total"]:
        resp.message(obtener_resumen())
        return str(resp)
    
    # Procesar en segundo plano para no hacer timeout
    thread = threading.Thread(target=procesar_en_background, args=(mensaje, numero_origen))
    thread.start()
    
    return str(resp)  # Respuesta vacía inmediata a Twilio

@app.route("/", methods=["GET"])
def home():
    return "Bot de finanzas activo! ✅"

if __name__ == "__main__":
    app.run(debug=True, port=5000)
