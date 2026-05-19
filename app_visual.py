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
st.markdown("Sube tu archivo DXF o Imagen. El sistema sincronizará perfectamente la vista para ubicar los dispositivos con precisión.")

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
                
                # --- LA MAGIA: ESPEJO MATEMÁTICO PERFECTO ---
                with st.spinner("Sincronizando coordenadas visuales con AutoCAD..."):
                    try:
                        msp = dxf_doc.modelspace()
                        fig = plt.figure(dpi=200)
                        # Creamos un eje que ocupa el 100% de la imagen (sin bordes blancos)
                        ax = fig.add_axes([0, 0, 1, 1])
                        ax.axis('off')
                        
                        ctx = RenderContext(dxf_doc)
                        out = MatplotlibBackend(ax)
                        Frontend(ctx, out).draw_layout(msp, finalize=True)
                        
                        # CAPTURAMOS LAS COORDENADAS EXACTAS DEL RECUADRO DE LA FOTO
                        cad_xlim = ax.get_xlim()
                        cad_ylim = ax.get_ylim()
                        st.session_state['dxf_bounds'] = (cad_xlim, cad_ylim)
                        
                        tmp_img = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
                        # Guardamos sin recortar para que la foto sea un mapa 1:1 de las coordenadas capturadas
                        fig.savefig(tmp_img.name, format='png', facecolor='white')
                        plt.close(fig)
                        
                        imagen_pil = Image.open(tmp_img.name)
                        st.success("👁️ ¡Sincronización CAD perfecta lograda!")
                    except Exception as img_err:
                        st.warning(f"No se pudo generar la foto del DXF. Error: {img_err}")
            except Exception as e:
                st.error(f"Error al procesar el archivo DXF: {e}")

if imagen_pil:
    st.image(imagen_pil, caption="Vista que analizará la Inteligencia Artificial", use_container_width=True)

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
        with st.spinner("Analizando y calculando ubicaciones milimétricas..."):
            
            resultados = db_collection.query(query_texts=[prompt_usuario], n_results=10)
            contexto_recuperado = "\n\n---\n\n".join(resultados['documents'][0]) if resultados['documents'] else ""
            
            prompt_sistema = f"""
            Eres un ingeniero experto en Prevención contra Incendios. 
            NORMATIVA APLICABLE: {contexto_recuperado}
            CONSULTA: {prompt_usuario}

            INSTRUCCIONES DE UBICACIÓN (MODO PORCENTAJE):
            1. Mira la imagen del plano. Identifica paredes y puertas.
            2. EXTINTORES: Ubícalos SIEMPRE pegados a las paredes, justo al lado de las puertas de acceso.
            3. DETECTORES: Ubícalos SIEMPRE en el centro geométrico del techo de cada recinto u oficina.
            4. Utiliza porcentajes visuales: "x_pct" (0=izquierda, 100=derecha) y "y_pct" (0=arriba, 100=abajo).

            Formato JSON requerido estrictamente al final:
            ```json
            [
              {{"tipo": "extintor", "x_pct": 15, "y_pct": 20, "label": "Extintor 4kg"}},
              {{"tipo": "detector", "x_pct": 45, "y_pct": 50, "label": "Detector Humo"}}
            ]
            ```
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
                        try:
                            datos_dispositivos = json.loads(bloque_json.group(1).strip())
                            
                            # --- MOTOR DE VISTA PREVIA ---
                            if imagen_pil:
                                img_dibujo = imagen_pil.copy().convert("RGB")
                                draw = ImageDraw.Draw(img_dibujo)
                                ancho, alto = img_dibujo.size
                                factor_base = (ancho + alto) / 1000.0
                                font = ImageFont.load_default(size=max(int(factor_base * 10), 12))
                                
                                for disp in datos_dispositivos:
                                    if 'x_pct' in disp and 'y_pct' in disp:
                                        px = int((disp['x_pct'] / 100) * ancho)
                                        py = int((disp['y_pct'] / 100) * alto)
                                        r = int(factor_base * 6.0)
                                        if disp['tipo'] == 'extintor': draw.rectangle([px-r, py-r, px+r, py+r], fill=(255, 0, 0), outline="black")
                                        else: draw.ellipse([px-r, py-r, px+r, py+r], fill=(0, 0, 255), outline="white")
                                        draw.text((px + int(r * 1.2), py), disp['label'], fill="black", font=font)
                                
                                st.image(img_dibujo, caption="Plano Visual", use_container_width=True)
                                imagen_final_mostrar = img_dibujo

                            # --- MOTOR DE INYECCIÓN DXF CON ESPEJO MATEMÁTICO ---
                            if dxf_doc and 'dxf_bounds' in st.session_state:
                                msp = dxf_doc.modelspace()
                                
                                # Recuperamos las coordenadas exactas de la cámara que sacó la foto
                                cad_xlim, cad_ylim = st.session_state['dxf_bounds']
                                cad_xmin, cad_xmax = min(cad_xlim), max(cad_xlim)
                                cad_ymin, cad_ymax = min(cad_ylim), max(cad_ylim)
                                
                                ancho_dxf = cad_xmax - cad_xmin
                                alto_dxf = cad_ymax - cad_ymin
                                
                                # Tamaño adaptado al tamaño de este edificio específico (0.8%)
                                radio_base_cad = min(ancho_dxf, alto_dxf) * 0.008 
                                alto_texto = radio_base_cad * 0.8
                                
                                posiciones_usadas_cad = []
                                distancia_minima_cad = radio_base_cad * 3.5

                                for disp in datos_dispositivos:
                                    if 'x_pct' in disp and 'y_pct' in disp:
                                        # TRADUCCIÓN PERFECTA: 
                                        # x_pct=0 -> Izquierda (cad_xmin), y_pct=0 -> Arriba (cad_ymax, porque en CAD Y sube)
                                        dxf_x = cad_xmin + (disp['x_pct'] / 100.0) * ancho_dxf
                                        dxf_y = cad_ymax - (disp['y_pct'] / 100.0) * alto_dxf
                                        
                                        # ALGORITMO ANTI-COLISIÓN (Evita encimar íconos)
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
                                
                                st.success("📐 ¡Plano vectorial de AutoCAD procesado con éxito!")
                                st.download_button(label="📥 Descargar Plano AutoCAD (DXF) Modificado", data=dxf_buffer_descarga, file_name=nombre_dxf_descarga, mime="application/dxf")
                        except Exception as e:
                            st.warning(f"Error procesando los datos: {e}")

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
