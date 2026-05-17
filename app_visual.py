import streamlit as st
import chromadb
from google import genai
from google.genai import types
import os

# --- 1. CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(page_title="Asistente NDEseg - Ordenanza 468", page_icon="🔥", layout="centered")

# ¡RECUERDA PONER TU CLAVE AQUÍ!
GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"] 

# Lista de modelos en cascada para la interfaz web
CASCADA_MODELOS = [
    'gemini-2.0-flash',       # Empezamos con este porque tiene cuota gigante
    'gemini-2.5-pro',         # Si falla, vamos al más inteligente
    'gemini-2.5-flash',       # El que se agotó hoy (por si se reinicia mañana)
    'gemini-flash-latest'     # El comodín final
]

# --- 2. INICIALIZACIÓN DE IA Y BASE DE DATOS AUTO-GENERABLE ---
@st.cache_resource
def init_sistema():
    client = genai.Client(api_key=GOOGLE_API_KEY)
    
    directorio_actual = os.path.dirname(os.path.abspath(__file__))
    ruta_bd = os.path.join(directorio_actual, "base_datos_normativa")
    
    chroma_client = chromadb.PersistentClient(path=ruta_bd)
    
    # Intentamos abrir la colección existente, si falla la creamos de cero
    try:
        collection = chroma_client.get_collection(name="ordenanza_468_limpia")
    except Exception:
        # Forzamos la creación limpia en la nube usando los documentos de texto
        collection = chroma_client.create_collection(name="ordenanza_468_limpia")
        
        # Leer fragmentos para procesar e indexar
        lineas_a_indexar = []
        if os.path.exists("anexos_limpios.txt"):
            with open("anexos_limpios.txt", "r", encoding="utf-8") as f:
                texto_completo = f.read()
                # Segmentamos el texto por párrafos o bloques dobles para no saturar
                lineas_a_indexar = [bloque.strip() for bloque in texto_completo.split("\n\n") if bloque.strip()]
        
        if lineas_a_indexar:
            ids = [f"id_{i}" for i in range(len(lineas_a_indexar))]
            collection.add(documents=lineas_a_indexar, ids=ids)
            
    return client, collection

try:
    gemini_client, db_collection = init_sistema()
except Exception as e:
    st.error(f"⚠️ Error al conectar o generar la base de datos: {e}")
    st.stop()

# --- 3. DISEÑO DE LA INTERFAZ ---
st.title("🔥 NDEseg: Ordenanza 468/14")
st.markdown("Escribe tu consulta y el sistema buscará en la normativa, realizando los cálculos necesarios según el área o uso que especifiques.")

# Memoria del chat
if "mensajes" not in st.session_state:
    st.session_state.mensajes = []

# Dibujar mensajes previos
for msg in st.session_state.mensajes:
    with st.chat_message(msg["rol"]):
        st.markdown(msg["contenido"])

# --- 4. LÓGICA DE BÚSQUEDA Y CASCADA ---
if prompt_usuario := st.chat_input("Ej. ¿Cuántos detectores necesito en una oficina de 200m2?"):
    
    with st.chat_message("user"):
        st.markdown(prompt_usuario)
    st.session_state.mensajes.append({"rol": "user", "contenido": prompt_usuario})

    with st.chat_message("assistant"):
        with st.spinner("Buscando en la ordenanza y calculando..."):
            
            resultados = db_collection.query(
                query_texts=[prompt_usuario],
                n_results=10 # <--- AHORA TRAERÁ MUCHA MÁS INFORMACIÓN
            )
            
            if not resultados['documents'] or not resultados['documents'][0]:
                st.error("No encontré información relacionada en la normativa.")
            else:
                # 1. Recuperar contexto de la base de datos
                contexto_recuperado = "\n\n---\n\n".join(resultados['documents'][0])
                
                # 2. Cargar la tabla purificada siempre en memoria (El secreto)
                tabla_memoria = ""
                try:
                    with open("anexos_limpios.txt", "r", encoding="utf-8") as f:
                        tabla_memoria = f.read()
                except:
                    pass
                
                prompt_sistema = f"""
                Eres un ingeniero inspector experto en Prevención contra Incendios.
                Tu objetivo es brindar respuestas exhaustivas, detalladas y con calidad de "Informe Técnico de Ingeniería".
                Responde a la consulta basándote ÚNICA Y EXCLUSIVAMENTE en el texto de la normativa provista y en la Tabla de Anexos.
                
                NORMATIVA RECUPERADA (Artículos):
                {contexto_recuperado}
                
                TABLA DE ANEXOS (MATRIZ DE REQUISITOS OBLIGATORIOS):
                {tabla_memoria}
                
                CONSULTA DEL USUARIO:
                {prompt_usuario}
                
                INSTRUCCIONES ESTRICTAS:
                1. EXHAUSTIVIDAD: No des respuestas cortas. Estructura tu respuesta como un Informe Técnico detallado dividiéndolo en secciones claras (Extintores, Sistema de Detección, Red Hidráulica y Reserva de Agua).
                2. VERIFICACIÓN INICIAL: Revisa la "TABLA DE ANEXOS" para determinar qué sistemas son obligatorios (SI) para el uso y superficie consultados.
                3. CÁLCULO DE CANTIDADES (¡VITAL!): Por cada sistema que sea obligatorio, DEBES hacer la matemática y estimar cantidades:
                   - Detección: Si requiere alarma/sensores, asume un Espaciamiento Certificado de S=9m (cobertura de 81m2 por detector) y calcula la cantidad matemática exacta de detectores necesarios para la superficie total, redondeando hacia arriba.
                   - Red Hidráulica y Agua: Si requiere red hidráulica, busca en los artículos recuperados la "reserva técnica mínima" (ej. los 10.000 litros) y menciónala explícitamente como la capacidad del tanque de agua. Especifica el diámetro de las válvulas según el nivel de riesgo.
                   - Extintores: Si no hay una regla exacta de m2 en los artículos, da una recomendación técnica sobre su distribución.
                4. Cita textualmente el artículo y la fila de la tabla en los que basaste tus cálculos.
                """
                
                respuesta_generada = False
                ultimo_error = "" # Variable para guardar el error real
                
                # Contenedor para mostrar mensajes de estado
                estado_cascada = st.empty() 
                
                for modelo_actual in CASCADA_MODELOS:
                    try:
                        estado_cascada.info(f"🔄 Intentando conectar con: {modelo_actual}...")
                        
                        respuesta = gemini_client.models.generate_content(
                            model=modelo_actual,
                            contents=prompt_sistema,
                            config=types.GenerateContentConfig(temperature=0.1)
                        )
                        
                        estado_cascada.empty()
                        
                        texto_respuesta = respuesta.text
                        st.markdown(texto_respuesta)
                        st.caption(f"⚡ Generado exitosamente por: {modelo_actual}")
                        
                        with st.expander("🔍 Ver los artículos originales extraídos del PDF"):
                            st.info(contexto_recuperado)
                            
                        st.session_state.mensajes.append({"rol": "assistant", "contenido": texto_respuesta})
                        respuesta_generada = True
                        break 
                    
                    except Exception as e:
                        ultimo_error = str(e) # Guardamos el texto del error
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
