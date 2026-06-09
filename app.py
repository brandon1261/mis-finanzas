import os
import json
import requests
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

app = Flask(__name__)

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
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
    prompt = f"""Analizá este mensaje de finanzas personales: "{mensaje}"

Respondé ÚNICAMENTE con JSON válido, sin markdown ni explicaciones:
{{"es_financiero": true, "tipo": "gasto", "monto": 500, "categoria": "alimentación", "metodo": "efectivo", "descripcion": "comida delivery"}}

Campos:
- tipo: "gasto" o "ingreso"
- monto: solo el número
- categoria: alimentación/transporte/servicios/salud/entretenimiento/ropa/trabajo/otro
- metodo: efectivo/transferencia/tarjeta/desconocido

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
            "model": "deepseek/deepseek-chat-v3-0324:free",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1
        },
        timeout=15
    )
    
    result = response.json()
    print(f"OpenRouter response: {result}")  # Para debug
    
    # Manejar diferentes formatos de respuesta
    if "choices" in result:
        texto = result["choices"][0]["message"]["content"]
    elif "error" in result:
        raise Exception(f"OpenRouter error: {result['error']}")
    else:
        raise Exception(f"Respuesta inesperada: {result}")
    
    texto = texto.strip().replace("```json", "").replace("```", "").strip()
    return json.loads(texto)

def guardar_en_sheets(datos):
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

@app.route("/webhook", methods=["POST"])
def webhook():
    mensaje = request.form.get("Body", "").strip()
    resp = MessagingResponse()
    
    if mensaje.lower() in ["resumen", "balance", "total"]:
        resp.message(obtener_resumen())
        return str(resp)
    
    try:
        datos = analizar_mensaje(mensaje)
        
        if not datos.get("es_financiero"):
            resp.message("No entendí eso como un gasto o ingreso. Contame algo como:\n'gasté 500 en comida'\n'me depositaron 3000 de sueldo'\n\nO escribí *resumen* para ver tu balance 📊")
            return str(resp)
        
        guardar_en_sheets(datos)
        
        emoji = "💸" if datos["tipo"] == "gasto" else "💰"
        tipo_texto = "Gasto" if datos["tipo"] == "gasto" else "Ingreso"
        
        resp.message(f"""{emoji} *{tipo_texto} registrado!*

💵 Monto: ${datos['monto']:,}
📂 Categoría: {datos['categoria'].capitalize()}
💳 Método: {datos['metodo'].capitalize()}
📝 {datos['descripcion'].capitalize()}

Escribí *resumen* para ver tu balance 📊""")
        
    except Exception as e:
        print(f"Error completo: {e}")
        resp.message(f"Error: {e}")  # Temporal para ver el error exacto
    
    return str(resp)

@app.route("/", methods=["GET"])
def home():
    return "Bot de finanzas activo! ✅"

if __name__ == "__main__":
    app.run(debug=True, port=5000)
