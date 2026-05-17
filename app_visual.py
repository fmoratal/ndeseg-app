import streamlit as st
import chromadb
from google import genai
from google.genai import types
import os
from PIL import Image  # <-- Nueva librería para manejar los píxeles del plano

# --- 1. CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(page_title="Asistente NDEseg - Ordenanza 468", page_icon="🔥", layout="centered")

# Llave de API segura desde los Secrets de Streamlit
GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"] 

# Lista de modelos en cascada (¡Importante! Todos estos soportan Visión de imágenes)
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
st.title("🔥 NDEseg: Ordenanza 468/14 + Planos")
st.markdown("Escribe tu consulta y el sistema buscará en la normativa. **Opcional:** Sube una imagen de tu plano para ubicar los dispositivos en el espacio.")

# 🛠️ NUEVO: El cargador de planos (Se renderiza arriba para que sea accesible)
archivo_plano = st.file_uploader("📂 Sube la imagen del plano (PNG, JPG, JPEG)", type=["png", "jpg", "jpeg"])

# Si el usuario sube un plano, se lo mostramos en pantalla como confirmación
imagen_pil = None
if archivo_plano:
    imagen_pil = Image.open(archivo_plano)
    st.image(imagen_pil, caption="📐 Plano cargado correctamente", use_container_width=True)

# Memoria del chat
if "mensajes" not in st.session_state:
    st.session_state.mensajes = []

for msg in st.session_state.mensajes:
    with st.chat_message(msg["rol"]):
        st.markdown(msg["contenido"])

# --- 4. LÓGICA DE BÚSQUEDA Y CASCADA ---
if prompt_usuario := st.chat_input("Ej. ¿Dónde y cuántos detectores debo ubicar en este plano de 200m2?"):
    
    with st.chat_message("user"):
        st.markdown(prompt_usuario)
    st.session_state.mensajes.append({"rol": "user", "contenido": prompt_usuario})

    with st.chat_message("assistant"):
        with st.spinner("Buscando en la ordenanza y analizando distribución espacial..."):
            
            # Buscamos los artículos más relevantes en base a lo que escribió el usuario
            resultados = db_collection.query(
                query_texts=[prompt_usuario],
                n_results=10 
            )
            
            contexto_recuperado = ""
            if resultados['documents'] and resultados['documents'][0]:
                contexto_recuperado = "\n\n---\n\n".join(resultados['documents'][0])
            
            # Cargamos las tablas de anexos directamente en memoria
            tabla_memoria = ""
            try:
                with open("anexos_limpios.txt", "r", encoding="utf-8") as f:
                    tabla_memoria = f.read()
            except:
                pass
            
            # PROMPT EVOLUCIONADO: Ahora le exige a Gemini analizar la imagen espacialmente si existe
            prompt_sistema = f"""
            Eres un ingeniero inspector experto en Prevención contra Incendios.
            Tu objetivo es brindar respuestas exhaustivas, detalladas y con calidad de "Informe Técnico de Ingeniería".
            Responde a la consulta basándote ÚNICA Y EXCLUSIVAMENTE en el texto de la normativa provista y en la Tabla de Anexos.
            
            NORMATIVA RECUPERADA (Artículos Reales de la Ley):
            {contexto_recuperado}
            
            TABLA DE ANEXOS (MATRIZ DE REQUISITOS OBLIGATORIOS):
            {tabla_memoria}
            
            CONSULTA DEL USUARIO:
            {prompt_usuario}
            
            INSTRUCCIONES DE ANÁLISIS ESPACIAL (SI HAY IMAGEN ADJUNTA):
            1. Mira detalladamente la imagen del plano provista. Identifica los accesos, salidas, pasillos y habitaciones.
            2. Determina las zonas de mayor riesgo y los puntos estratégicos exactos donde se deben colocar los extintores (cerca de tableros eléctricos, salidas, etc.).
            3. Para el Sistema de Detección (Espaciamiento S=9m), indica visualmente dónde deberían colgarse los sensores en el techo de cada habitación para evitar zonas muertas.
            
            INSTRUCCIONES DE RESPUESTA:
            1. EXHAUSTIVIDAD: Estructura tu respuesta como un Informe Técnico detallado dividiéndolo en secciones claras (Extintores, Sistema de Detección, Red Hidráulica y Reserva de Agua).
            2. UBICACIÓN DETALLADA: En la sección correspondiente, describe textualmente de forma exacta dónde colocar cada dispositivo dentro del plano analizado (ej: "Colocar un extintor ABC de 4kg a la derecha de la puerta de acceso principal en el área administrativa...").
            3. Cita textualmente el artículo y la fila de la tabla en los que basaste tus cálculos.
            """
            
            # 🛠️ NUEVO: Preparar los contenidos para Gemini. 
            # Si el usuario subió una imagen, se la empaquetamos junto con las instrucciones en un array multimoldal.
            elementos_peticion = []
            if imagen_pil:
                elementos_peticion.append(imagen_pil)
            elementos_peticion.append(prompt_sistema)
            
            respuesta_generada = False
            ultimo_error = "" 
            estado_cascada = st.empty() 
            
            for modelo_actual in CASCADA_MODELOS:
                try:
                    estado_cascada.info(f"🔄 Intentando conectar con: {modelo_actual}...")
                    
                    # Ejecutamos la petición multimodal
                    respuesta = gemini_client.models.generate_content(
                        model=modelo_actual,
                        contents=elementos_peticion,
                        config=types.GenerateContentConfig(temperature=0.1)
                    )
                    
                    estado_cascada.empty()
                    
                    texto_respuesta = respuesta.text
                    st.markdown(texto_respuesta)
                    st.caption(f"⚡ Generado exitosamente por: {modelo_actual}")
                    
                    if contexto_recuperado:
                        with st.expander("🔍 Ver los artículos originales extraídos del PDF"):
                            st.info(contexto_recuperado)
                        
                    st.session_state.mensajes.append({"rol": "assistant", "contenido": texto_respuesta})
                    respuesta_generada = True
                    break 
                
                except Exception as e:
                    ultimo_error = str(e)
                    if "429" in ultimo_error or "Quota" in ultimo_error:
                        estado_cascada.warning(f"⚠️ {modelo_actual} rechazó la conexión. Saltando...")
                        continue 
                    else:
                        st.error(f"Error inesperado con {modelo_actual}: {e}")
                        break
            
            if not respuesta_generada:
                estado_cascada.empty()
                st.error("⚠️ Los servidores de Google rechazaron todas las peticiones.")
                with st.expander("Ver detalle técnico del error"):
                    st.code(ultimo_error)
