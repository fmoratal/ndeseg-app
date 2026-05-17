import streamlit as st
import chromadb
from google import genai
from google.genai import types
import os
from PIL import Image, ImageDraw, ImageFont  
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
st.title("🔥 NDEseg: Mapas de Seguridad Inteligentes")
st.markdown("Sube la imagen de tu plano y escribe tu consulta para generar el informe técnico legal y el mapa visual de dispositivos.")

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
if prompt_usuario := st.chat_input("Ej. ¿Dónde y cuántos dispositivos necesito en este plano de 165m2?"):
    
    with st.chat_message("user"):
        st.markdown(prompt_usuario)
    st.session_state.mensajes.append({"rol": "user", "contenido": prompt_usuario})

    with st.chat_message("assistant"):
        with st.spinner("Buscando en la ordenanza y calibrando coordenadas espaciales..."):
            
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
            
            prompt_sistema = f"""
            Eres un ingeniero inspector experto en Prevención contra Incendios y Diseño de Planos de Seguridad.
            Tu objetivo es brindar un Informe Técnico de Ingeniería y mapear los dispositivos de forma PIXEL-PERFECT sobre el plano visual provisto.

            NORMATIVA RECUPERADA:
            {contexto_recuperado}
            
            TABLA DE ANEXOS:
            {tabla_memoria}
            
            CONSULTA DEL USUARIO:
            {prompt_usuario}
            
            GUÍA DE CALIBRACIÓN GEOMÉTRICA DEL PLANO (Trata la imagen como una matriz de X: 0-100% e Y: 0-100%):
            - LÍMITES EXTERNOS: El edificio real empieza en X=4, Y=11 y termina en X=96, Y=95. ¡PROHIBIDO colocar dispositivos fuera de este rango!
            - ACCESO PRINCIPAL (Puerta arriba a la izquierda): Está ubicado exactamente en X=12, Y=12.
            - OFICINAS IZQUIERDAS (Privadas): Se ubican entre X=5 hasta X=30.
            - SALA DE DESCANSO / COCINA (Arriba a la derecha): Se ubica entre X=43 hasta X=95 en el eje horizontal, y entre Y=11 hasta Y=41.
            - OFICINA PLANTA ABIERTA (Centro con 12 escritorios): Se ubica entre X=43 hasta X=95 en el eje horizontal, y entre Y=42 hasta Y=68.
            - SALA DE REUNIONES GRANDE (Abajo a la derecha): Se ubica entre X=44 hasta X=95 en el eje horizontal, y entre Y=69 hasta Y=95.

            INSTRUCCIONES DE UBICACIÓN LÓGICA:
            1. DETECTORES DE HUMO/CALOR: En el CENTRO GEOMÉTRICO del techo de cada sala.
            2. EXTINTORES Y PULSADORES: En los MUROS O TABIQUES, al lado de las puertas de acceso.
            3. LUCES Y CARTELES DE EMERGENCIA: Cerca de las puertas de salida.
            4. REGLA ANTI-SUPERPOSICIÓN (¡CRÍTICA!): Si vas a colocar un Cartel de Salida y una Luz de Emergencia en la misma puerta, NUNCA les des las mismas coordenadas exactas. Desplaza uno de ellos unos 4 puntos porcentuales en el eje Y (ej: Luz en Y=10, Cartel en Y=14) para que no se dibujen uno encima del otro.

            Formato obligatorio al final de tu respuesta:
            Antes del JSON, escribe una sección llamada "PENSAMIENTO DE COORDENADAS". Luego, pon el bloque JSON exacto usando SOLAMENTE los tipos "extintor", "detector", "cartel", "luz":
            ```json
            [
              {{"tipo": "extintor", "x_pct": 14, "y_pct": 16, "label": "Extintor ABC 4kg"}},
              {{"tipo": "luz", "x_pct": 12, "y_pct": 9, "label": "Luz Emerg."}},
              {{"tipo": "cartel", "x_pct": 12, "y_pct": 14, "label": "Cartel Salida"}}
            ]
            ```
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
                    
                    texto_informe = re.sub(r'```json.*?```', '', texto_respuesta, flags=re.DOTALL)
                    st.markdown(texto_informe)
                    
                    # --- MOTOR DE DIBUJO AVANZADO ---
                    imagen_final_mostrar = None
                    if imagen_pil:
                        bloque_json = re.search(r'```json(.*?)```', texto_respuesta, flags=re.DOTALL)
                        if bloque_json:
                            try:
                                datos_dispositivos = json.loads(bloque_json.group(1).strip())
                                
                                img_dibujo = imagen_pil.copy().convert("RGB")
                                draw = ImageDraw.Draw(img_dibujo)
                                ancho, alto = img_dibujo.size
                                
                                try:
                                    font = ImageFont.load_default(size=24)
                                except Exception:
                                    font = ImageFont.load_default()
                                
                                for disp in datos_dispositivos:
                                    px = int((disp['x_pct'] / 100) * ancho)
                                    py = int((disp['y_pct'] / 100) * alto)
                                    
                                    if disp['tipo'] == 'extintor':
                                        draw.rectangle([px-22, py-22, px+22, py+22], fill=(255, 0, 0), outline="black", width=4)
                                    elif disp['tipo'] == 'detector':
                                        draw.ellipse([px-18, py-18, px+18, py+18], fill=(0, 0, 255), outline="white", width=4)
                                    elif disp['tipo'] == 'luz':
                                        # NUEVO: Círculo Amarillo brillante para Luces
                                        draw.ellipse([px-20, py-20, px+20, py+20], fill=(255, 255, 0), outline="black", width=4)
                                    else: # Cartel u otros
                                        # Triángulo Naranja para Carteles
                                        draw.polygon([(px, py-24), (px-22, py+20), (px+22, py+20)], fill=(255, 140, 0), outline="black")
                                    
                                    draw.text((px + 30, py - 12), disp['label'], fill="black", font=font, stroke_width=3, stroke_fill="white")
                                
                                st.image(img_dibujo, caption="📐 Plano de Distribución de Seguridad Generado Automáticamente", use_container_width=True)
                                imagen_final_mostrar = img_dibujo
                            except Exception as e:
                                st.warning(f"No se pudo procesar el gráfico automático: {e}")
                    
                    st.caption(f"⚡ Procesado por: {modelo_actual}")
                    
                    if contexto_recuperado:
                        with st.expander("🔍 Ver los artículos originales extraídos del PDF"):
                            st.info(contexto_recuperado)
                    
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
                st.error("⚠️ Los servidores de Google rechazaron todas las peticiones.")
