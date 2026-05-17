import streamlit as st
import chromadb
from google import genai
from google.genai import types
import os
from PIL import Image, ImageDraw  # <-- Cargamos el motor de dibujo de Python
import json
import re

# --- 1. CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(page_title="Asistente NDEseg - Ordenanza 468", page_icon="🔥", layout="centered")

GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"] 

CASCADA_MODELOS = [
    'gemini-2.0-flash',       
    'gemini-2.5-pro',         
    'gemini-2.5-flash',       
    'gemini-flash-latest'     
]

# --- 2. INICIALIZACIÓN DE IA Y BASE DE DATOS AUTO-GENERABLE ---
@st.cache_resource
def init_sistema():
    client = genai.Client(api_key=GOOGLE_API_KEY)
    directorio_actual = os.path.dirname(os.path.abspath(__file__))
    ruta_bd = os.path.join(directorio_actual, "base_datos_normativa")
    chroma_client = chromadb.PersistentClient(path=ruta_bd)
    
    try:
        collection = chroma_client.get_collection(name="ordenanza_468_limpia")
    except Exception:
        collection = chroma_client.create_collection(name="ordenanza_468_limpia")
        if os.path.exists("normativa_completa.txt"):
            with open("normativa_completa.txt", "r", encoding="utf-8") as f:
                texto_completo = f.read()
            bloques = [b.strip() for b in texto_completo.split("ARTICULO") if b.strip()]
            if len(bloques) <= 1:
                bloques = [b.strip() for b in texto_completo.split("\n\n") if b.strip()]
            documentos_finales = [f"ARTICULO {b}" if not b.startswith("CAPITULO") else b for b in bloques]
            ids = [f"art_{i}" for i in range(len(documentos_finales))]
            collection.add(documents=documentos_finales, ids=ids)
            
    return client, collection

try:
    gemini_client, db_collection = init_sistema()
except Exception as e:
    st.error(f"⚠️ Error al conectar o generar la base de datos: {e}")
    st.stop()

# --- 3. DISEÑO DE LA INTERFAZ ---
st.title("🔥 NDEseg: Ordenanza 468/14 + Planos Inteligentes")
st.markdown("Sube la imagen de tu plano y escribe tu consulta para generar el informe y el mapa de dispositivos.")

archivo_plano = st.file_uploader("📂 Sube la imagen del plano (PNG, JPG, JPEG)", type=["png", "jpg", "jpeg"])

imagen_pil = None
if archivo_plano:
    imagen_pil = Image.open(archivo_plano)

# Memoria del chat
if "mensajes" not in st.session_state:
    st.session_state.mensajes = []

for msg in st.session_state.mensajes:
    with st.chat_message(msg["rol"]):
        st.markdown(msg["contenido"])
        if "imagen_dibujada" in msg:
            st.image(msg["imagen_dibujada"], caption="📐 Ubicación de Dispositivos Generada")

# --- 4. LÓGICA DE BÚSQUEDA Y DIBUJO ---
if prompt_usuario := st.chat_input("Ej. ¿Qué necesito para esta oficina de 165m2 y dónde ubico los dispositivos?"):
    
    with st.chat_message("user"):
        st.markdown(prompt_usuario)
    st.session_state.mensajes.append({"rol": "user", "contenido": prompt_usuario})

    with st.chat_message("assistant"):
        with st.spinner("Buscando en la ordenanza y renderizando plano de seguridad..."):
            
            resultados = db_collection.query(query_texts=[prompt_usuario], n_results=10)
            contexto_recuperado = ""
            if resultados['documents'] and resultados['documents'][0]:
                contexto_recuperado = "\n\n---\n\n".join(resultados['documents'][0])
            
            tabla_memoria = ""
            try:
                with open("anexos_limpios.txt", "r", encoding="utf-8") as f:
                    tabla_memoria = f.read()
            except:
                pass
            
            # Ajustamos el prompt para exigir una sección JSON limpia al final de la respuesta
            prompt_sistema = f"""
            Eres un ingeniero inspector experto en Prevención contra Incendios.
            Tu objetivo es brindar respuestas exhaustivas, detalladas y con calidad de "Informe Técnico de Ingeniería".
            Responde a la consulta basándote ÚNICA Y EXCLUSIVAMENTE en la normativa provista y en la Tabla de Anexos.
            
            NORMATIVA RECUPERADA:
            {contexto_recuperado}
            
            TABLA DE ANEXOS:
            {tabla_memoria}
            
            CONSULTA DEL USUARIO:
            {prompt_usuario}
            
            INSTRUCCIONES DE RESPUESTA:
            1. EXHAUSTIVIDAD: Genera el "INFORME TÉCNICO DE INGENIERÍA" completo como lo venías haciendo.
            2. COORDENADAS DE MAPEO (¡CRÍTICO!): Al final de TODO tu informe técnico, debes agregar un bloque JSON que contenga las coordenadas espaciales estimadas (en porcentaje de 0 a 100 de ancho y alto de la imagen) para ubicar físicamente cada dispositivo que calculaste en base al plano visual proporcionado.
            
            Formato exacto requerido al final del mensaje:
            ```json
            [
              {{"tipo": "extintor", "x_pct": 15, "y_pct": 20, "label": "Extintor ABC 4kg"}},
              {{"tipo": "detector", "x_pct": 45, "y_pct": 50, "label": "Detector Humo"}}
            ]
            ```
            Usa únicamente los tipos "extintor", "detector", "alarma" o "luces". Colócalos de manera estratégica en base a la distribución visual.
            """
            
            elementos_peticion = []
            if imagen_pil:
                elementos_peticion.append(imagen_pil)
            elementos_peticion.append(prompt_sistema)
            
            respuesta_generada = False
            ultimo_error = "" 
            estado_cascada = st.empty() 
            
            for modelo_actual in CASCADA_MODELOS:
                try:
                    estado_cascada.info(f"🔄 Conectando con: {modelo_actual}...")
                    
                    respuesta = gemini_client.models.generate_content(
                        model=modelo_actual,
                        contents=elementos_peticion,
                        config=types.GenerateContentConfig(temperature=0.1)
                    )
                    
                    estado_cascada.empty()
                    texto_respuesta = respuesta.text
                    
                    # Separamos el JSON del texto del informe técnico
                    texto_informe = re.sub(r'```json.*?```', '', texto_respuesta, flags=re.DOTALL)
                    st.markdown(texto_informe)
                    
                    # --- MOTOR DE DIBUJO ---
                    imagen_final_mostrar = None
                    if imagen_pil:
                        # Buscamos el JSON en la respuesta de Gemini
                        bloque_json = re.search(r'```json(.*?)```', texto_respuesta, flags=re.DOTALL)
                        if bloque_json:
                            try:
                                datos_dispositivos = json.loads(bloque_json.group(1).strip())
                                
                                # Creamos una copia del plano para dibujar encima sin romper el original
                                img_dibujo = imagen_pil.copy()
                                draw = ImageDraw.Draw(img_dibujo)
                                ancho, alto = img_dibujo.size
                                
                                for disp in datos_dispositivos:
                                    # Convertimos los porcentajes de la IA a píxeles reales del plano
                                    px = int((disp['x_pct'] / 100) * ancho)
                                    py = int((disp['y_pct'] / 100) * alto)
                                    
                                    # Dibujamos según el tipo de dispositivo
                                    if disp['tipo'] == 'extintor':
                                        # Cuadrado Rojo para Extintores
                                        draw.rectangle([px-12, py-12, px+12, py+12], fill="red", outline="black", width=2)
                                    elif disp['tipo'] == 'detector':
                                        # Círculo Azul para Detectores de Humo/Calor
                                        draw.ellipse([px-10, py-10, px+10, py+10], fill="blue", outline="white", width=2)
                                    else:
                                        # Triángulo Amarillo para Alarmas o Luces
                                        draw.polygon([(px, py-12), (px-12, py+12), (px+12, py+12)], fill="orange", outline="black")
                                
                                # Mostramos el plano con los elementos dibujados
                                st.image(img_dibujo, caption="📐 Plano de Distribución de Seguridad Generado Automáticamente", use_container_width=True)
                                imagen_final_mostrar = img_dibujo
                            except Exception as e:
                                st.warning(f"No se pudo procesar el gráfico automático: {e}")
                    
                    st.caption(f"⚡ Procesado por: {modelo_actual}")
                    
                    if contexto_recuperado:
                        with st.expander("🔍 Ver los artículos originales extraídos del PDF"):
                            st.info(contexto_recuperado)
                    
                    # Guardamos todo en la sesión del chat
                    msg_guardar = {"rol": "assistant", "contenido": texto_informe}
                    if imagen_final_mostrar:
                        msg_guardar["imagen_dibujada"] = imagen_final_mostrar
                    st.session_state.mensajes.append(msg_guardar)
                    
                    respuesta_generada = True
                    break 
                
                except Exception as e:
                    ultimo_error = str(e)
                    if "429" in ultimo_error or "Quota" in ultimo_error:
                        estado_cascada.warning(f"⚠️ {modelo_actual} ocupado. Saltando...")
                        continue 
                    else:
                        st.error(f"Error inesperado: {e}")
                        break
            
            if not respuesta_generada:
                estado_cascada.empty()
                st.error("⚠️ Error de conexión con los servidores de IA.")
