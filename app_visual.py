import streamlit as st
import chromadb
from google import genai
from google.genai import types
import os
from PIL import Image, ImageDraw, ImageFont  
import json
import re
from pdf2image import convert_from_bytes
import ezdxf
from ezdxf import bbox
import tempfile
import math

# --- LIBRERÍAS DEL MOTOR DE RENDERIZADO DXF ---
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from ezdxf.addons.drawing import RenderContext, Frontend
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

# --- 1. CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(page_title="Asistente NDEseg - Ordenanza 468", page_icon="🔥", layout="centered")

GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"] 

CASCADA_MODELOS = [
    'gemini-2.0-flash',       
    'gemini-2.5-pro',         
    'gemini-2.5-flash',       
    'gemini-flash-latest'     
]

# --- 2. INICIALIZACIÓN DE BASE DE DATOS ---
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
st.title("🔥 NDEseg: Ingeniería Automática de Planos")
st.markdown("Sube tu archivo DXF. El sistema generará una cuadrícula de francotirador para ubicar los dispositivos con precisión milimétrica.")

archivos_subidos = st.file_uploader("📂 Sube tu archivo (PDF, DXF, PNG, JPG)", type=["png", "jpg", "jpeg", "pdf", "dxf"], accept_multiple_files=True)

imagen_pil = None
dxf_doc = None
nombre_dxf_descarga = "Plano_Seguridad_NDEseg.dxf"

if archivos_subidos:
    for archivo in archivos_subidos:
        ext = archivo.name.split('.')[-1].lower()
        
        if ext in ['png', 'jpg', 'jpeg'] and not imagen_pil:
            imagen_pil = Image.open(archivo)
            st.success(f"🖼️ Imagen cargada: {archivo.name}")
            
        elif ext == 'pdf' and not imagen_pil:
            with st.spinner("Convirtiendo PDF a formato visual..."):
                paginas = convert_from_bytes(archivo.read())
                if paginas:
                    imagen_pil = paginas[0]
                    st.success(f"📄 PDF convertido a imagen: {archivo.name}")
                    
        elif ext == 'dxf':
            with tempfile.NamedTemporaryFile(delete=False, suffix=".dxf") as tmp:
                tmp.write(archivo.getvalue())
                tmp_path = tmp.name
            try:
                dxf_doc = ezdxf.readfile(tmp_path)
                nombre_dxf_descarga = f"NDEseg_{archivo.name}"
                st.success(f"📐 Archivo AutoCAD DXF cargado: {archivo.name}")
                
                # --- LA MAGIA: MODO FRANCOTIRADOR (CUADRÍCULA DE COORDENADAS) ---
                with st.spinner("Generando mapa táctico con cuadrícula de coordenadas CAD..."):
                    try:
                        msp = dxf_doc.modelspace()
                        fig = plt.figure(dpi=250) # Alta resolución para que lea bien los números
                        ax = fig.add_subplot(111)
                        
                        ctx = RenderContext(dxf_doc)
                        out = MatplotlibBackend(ax)
                        Frontend(ctx, out).draw_layout(msp, finalize=True)
                        
                        # Inyectamos los ejes de AutoCAD en la foto
                        ax.grid(True, color='red', linestyle='--', linewidth=0.5, alpha=0.5)
                        ax.tick_params(axis='both', labelsize=6, colors='blue')
                        for spine in ax.spines.values():
                            spine.set_edgecolor('blue')
                        
                        tmp_img = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
                        fig.savefig(tmp_img.name, format='png', bbox_inches='tight', pad_inches=0.1, facecolor='white')
                        plt.close(fig)
                        
                        imagen_pil = Image.open(tmp_img.name)
                        st.success("🎯 ¡Modo Francotirador activado! La IA leerá las coordenadas reales.")
                    except Exception as img_err:
                        st.warning(f"No se pudo generar la foto del DXF. Error: {img_err}")
            except Exception as e:
                st.error(f"Error al procesar el archivo DXF: {e}")

if imagen_pil:
    st.image(imagen_pil, caption="Mapa Táctico que analizará la Inteligencia Artificial", use_container_width=True)

if "mensajes" not in st.session_state:
    st.session_state.mensajes = []

for msg in st.session_state.mensajes:
    with st.chat_message(msg["rol"]):
        st.markdown(msg["contenido"])
        if "imagen_dibujada" in msg:
            st.image(msg["imagen_dibujada"], caption="📐 Vista Previa Generada")
        if "boton_dxf" in msg and msg["boton_dxf"] is not None:
            st.download_button(label="📥 Descargar Plano AutoCAD (DXF)", data=msg["boton_dxf"], file_name=nombre_dxf_descarga, mime="application/dxf", key=str(len(st.session_state.mensajes)))

# --- 4. LÓGICA DE PROCESAMIENTO ---
if prompt_usuario := st.chat_input("Ej. Ubicar extintores y detectores según normativa."):
    
    with st.chat_message("user"):
        st.markdown(prompt_usuario)
    st.session_state.mensajes.append({"rol": "user", "contenido": prompt_usuario})

    with st.chat_message("assistant"):
        with st.spinner("Cruzando normativa con cuadrícula de coordenadas..."):
            
            resultados = db_collection.query(query_texts=[prompt_usuario], n_results=10)
            contexto_recuperado = "\n\n---\n\n".join(resultados['documents'][0]) if resultados['documents'] else ""
            
            tabla_memoria = ""
            try:
                with open("anexos_limpios.txt", "r", encoding="utf-8") as f:
                    tabla_memoria = f.read()
            except:
                pass

            prompt_sistema = f"""
            Eres un ingeniero experto en Prevención contra Incendios. Dicta un Informe Técnico detallado.
            NORMATIVA APLICABLE: {contexto_recuperado}
            TABLA: {tabla_memoria}
            CONSULTA: {prompt_usuario}

            INSTRUCCIONES CRÍTICAS DE UBICACIÓN (MODO FRANCOTIRADOR):
            1. Mira la imagen adjunta. Verás que tiene una CUADRÍCULA ROJA y números azules en los bordes (Ejes X e Y). ¡Esas son las coordenadas reales de AutoCAD!
            2. Identifica visualmente las puertas y los centros de las salas.
            3. Lee los números en los ejes de la imagen para averiguar la coordenada (cad_x, cad_y) exacta de donde debes ubicar el dispositivo.
            4. REGLA ORO: Los extintores y pulsadores van pegados a las paredes junto a las puertas. Los detectores van en el medio de las habitaciones.

            Formato JSON requerido al final:
            ```json
            [
              {{"tipo": "extintor", "cad_x": 105.2, "cad_y": -40.5, "x_pct": null, "y_pct": null, "label": "Ext. ABC 4kg"}}
            ]
            ```
            (Si la imagen NO tiene cuadrícula, usa x_pct e y_pct del 0 al 100 y deja cad_x/cad_y en null).
            """
            
            elementos_peticion = []
            if imagen_pil:
                elementos_peticion.append(imagen_pil)
            elementos_peticion.append(prompt_sistema)
            
            respuesta_generada = False
            
            for modelo_actual in CASCADA_MODELOS:
                try:
                    respuesta = gemini_client.models.generate_content(
                        model=modelo_actual,
                        contents=elementos_peticion,
                        config=types.GenerateContentConfig(temperature=0.1)
                    )
                    texto_respuesta = respuesta.text
                    texto_informe = re.sub(r'```json.*?```', '', texto_respuesta, flags=re.DOTALL)
                    st.markdown(texto_informe)
                    
                    imagen_final_mostrar = None
                    dxf_buffer_descarga = None
                    
                    bloque_json = re.search(r'```json(.*?)```', texto_respuesta, flags=re.DOTALL)
                    if bloque_json:
                        datos_dispositivos = json.loads(bloque_json.group(1).strip())

                        # --- MOTOR 1: DIBUJO EN IMAGEN (Fallback si no hay DXF) ---
                        if imagen_pil and not dxf_doc:
                            try:
                                img_dibujo = imagen_pil.copy().convert("RGB")
                                draw = ImageDraw.Draw(img_dibujo)
                                ancho, alto = img_dibujo.size
                                factor_base = (ancho + alto) / 1000.0
                                font = ImageFont.load_default(size=max(int(factor_base * 10), 12))
                                
                                for disp in datos_dispositivos:
                                    if disp.get('x_pct') is not None:
                                        px = int((disp['x_pct'] / 100) * ancho)
                                        py = int((disp['y_pct'] / 100) * alto)
                                        r = int(factor_base * 6.0)
                                        if disp['tipo'] == 'extintor': draw.rectangle([px-r, py-r, px+r, py+r], fill=(255, 0, 0), outline="black")
                                        else: draw.ellipse([px-r, py-r, px+r, py+r], fill=(0, 0, 255), outline="white")
                                        draw.text((px + int(r * 1.2), py), disp['label'], fill="black", font=font)
                                
                                st.image(img_dibujo, caption="Plano Visual", use_container_width=True)
                                imagen_final_mostrar = img_dibujo
                            except Exception as e:
                                st.warning(f"Error en renderizado visual: {e}")

                        # --- MOTOR 2: INYECCIÓN VECTORIAL EXACTA EN DXF ---
                        if dxf_doc:
                            try:
                                msp = dxf_doc.modelspace()
                                extents = bbox.extents(msp)
                                
                                if extents.has_data:
                                    ancho_dxf = extents.extmax.x - extents.extmin.x
                                    alto_dxf = extents.extmax.y - extents.extmin.y
                                    radio_base_cad = min(ancho_dxf, alto_dxf) * 0.003 
                                    alto_texto = radio_base_cad * 0.8
                                else:
                                    radio_base_cad, alto_texto = 1.0, 0.8
                                
                                posiciones_usadas_cad = []
                                distancia_minima_cad = radio_base_cad * 3.5

                                for disp in datos_dispositivos:
                                    # PRIORIDAD 1: Usamos la coordenada leída directamente de la cuadrícula
                                    if disp.get('cad_x') is not None and disp.get('cad_y') is not None:
                                        dxf_x = float(disp['cad_x'])
                                        dxf_y = float(disp['cad_y'])
                                    # PRIORIDAD 2: Si por algún motivo la IA devolvió porcentajes, los traducimos
                                    elif extents.has_data and disp.get('x_pct') is not None:
                                        dxf_x = extents.extmin.x + (disp['x_pct'] / 100.0) * ancho_dxf
                                        dxf_y = extents.extmax.y - (disp['y_pct'] / 100.0) * alto_dxf
                                    else:
                                        continue
                                        
                                    # ALGORITMO ANTI-COLISIÓN
                                    intentos = 0
                                    while intentos < 10:
                                        colision = False
                                        for ux, uy in posiciones_usadas_cad:
                                            if math.hypot(dxf_x - ux, dxf_y - uy) < distancia_minima_cad:
                                                dxf_x += radio_base_cad * 2.5
                                                dxf_y -= radio_base_cad * 2.5
                                                colision = True
                                                break
                                        if not colision:
                                            break
                                        intentos += 1
                                    
                                    posiciones_usadas_cad.append((dxf_x, dxf_y))
                                    
                                    color_cad = 1 if disp['tipo'] == 'extintor' else (5 if disp['tipo'] == 'detector' else 2)
                                    msp.add_circle((dxf_x, dxf_y), radius=radio_base_cad, dxfattribs={'color': color_cad})
                                    msp.add_text(disp['label'], dxfattribs={'height': alto_texto, 'color': color_cad}).set_placement((dxf_x + radio_base_cad*1.2, dxf_y))
                                
                                with tempfile.NamedTemporaryFile(delete=False, suffix=".dxf") as tmp_out:
                                    dxf_doc.saveas(tmp_out.name)
                                    tmp_out_path = tmp_out.name
                                with open(tmp_out_path, "rb") as f:
                                    dxf_buffer_descarga = f.read()
                                
                                st.success("📐 ¡Tu plano vectorial ha sido procesado de forma nativa!")
                                st.download_button(label="📥 Descargar Plano AutoCAD (DXF) Modificado", data=dxf_buffer_descarga, file_name=nombre_dxf_descarga, mime="application/dxf")
                            except Exception as e:
                                st.warning(f"Error inyectando vectores CAD: {e}")

                    msg_guardar = {"rol": "assistant", "contenido": texto_informe}
                    if imagen_final_mostrar: msg_guardar["imagen_dibujada"] = imagen_final_mostrar
                    if dxf_buffer_descarga: msg_guardar["boton_dxf"] = dxf_buffer_descarga
                    st.session_state.mensajes.append(msg_guardar)
                    
                    respuesta_generada = True
                    break 
                
                except Exception as e:
                    if "429" in str(e) or "Quota" in str(e): continue 
                    else: break
            
            if not respuesta_generada:
                st.error("⚠️ Los servidores de Google rechazaron todas las peticiones.")
