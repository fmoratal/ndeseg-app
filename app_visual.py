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

# --- CATÁLOGO MAESTRO DE DISPOSITIVOS ---
# Define colores RGB para imagen, Color Index para CAD, y la forma geométrica
CATALOGO = {
    'extintor':  {'rgb': (255, 0, 0),   'cad': 1,   'forma': 'cuadrado'},  # Rojo
    'detector':  {'rgb': (0, 0, 255),   'cad': 5,   'forma': 'circulo'},   # Azul
    'luz':       {'rgb': (255, 255, 0), 'cad': 2,   'forma': 'circulo'},   # Amarillo
    'cartel':    {'rgb': (0, 255, 0),   'cad': 3,   'forma': 'triangulo'}, # Verde
    'alarma':    {'rgb': (255, 140, 0), 'cad': 30,  'forma': 'triangulo'}, # Naranja
    'pulsador':  {'rgb': (255, 0, 255), 'cad': 6,   'forma': 'cuadrado'},  # Magenta
    'bie':       {'rgb': (0, 255, 255), 'cad': 4,   'forma': 'cuadrado'},  # Cian
    'rociador':  {'rgb': (0, 191, 255), 'cad': 130, 'forma': 'circulo'}    # Celeste
}

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
st.markdown("Sube tu archivo DXF o Imagen. El motor renderizará y ubicará los 8 tipos de dispositivos de prevención.")

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
                
                with st.spinner("Sincronizando coordenadas exactas (Aspect Ratio 1:1)..."):
                    try:
                        msp = dxf_doc.modelspace()
                        extents = bbox.extents(msp)
                        
                        if extents.has_data:
                            min_x, min_y = extents.extmin.x, extents.extmin.y
                            max_x, max_y = extents.extmax.x, extents.extmax.y
                            ancho_dxf = max_x - min_x
                            alto_dxf = max_y - min_y
                            
                            st.session_state['dxf_bounds'] = (min_x, min_y, max_x, max_y, ancho_dxf, alto_dxf)
                            
                            # Calculamos la proporción para que la foto no se estire ni deforme
                            fig_w = 12.0
                            fig_h = fig_w * (alto_dxf / ancho_dxf)
                            
                            fig = plt.figure(figsize=(fig_w, fig_h), dpi=200)
                            ax = fig.add_axes([0, 0, 1, 1]) # Ocupa el 100% de la figura, sin márgenes
                            ax.axis('off')
                            
                            ctx = RenderContext(dxf_doc)
                            out = MatplotlibBackend(ax)
                            Frontend(ctx, out).draw_layout(msp, finalize=True)
                            
                            # Forzamos a que la vista sea EXACTAMENTE el Bounding Box de AutoCAD
                            ax.set_xlim(min_x, max_x)
                            ax.set_ylim(min_y, max_y)
                            
                            tmp_img = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
                            # Guardamos sin "bbox_inches='tight'" para respetar los límites matemáticos forzados
                            fig.savefig(tmp_img.name, format='png', facecolor='white')
                            plt.close(fig)
                            
                            imagen_pil = Image.open(tmp_img.name)
                            st.success("👁️ ¡Sincronización CAD lograda sin márgenes de error!")
                        else:
                            st.warning("El DXF no tiene entidades válidas para renderizar.")
                    except Exception as img_err:
                        st.warning(f"No se pudo generar la foto del DXF. Error: {img_err}")
            except Exception as e:
                st.error(f"Error al procesar el archivo DXF: {e}")

if imagen_pil:
    st.image(imagen_pil, caption="Mapa exacto que analizará la IA", use_container_width=True)

if "mensajes" not in st.session_state:
    st.session_state.mensajes = []

for msg in st.session_state.mensajes:
    with st.chat_message(msg["rol"]):
        st.markdown(msg["contenido"])
        if "imagen_dibujada" in msg:
            st.image(msg["imagen_dibujada"], caption="📐 Vista Previa")
        if "boton_dxf" in msg and msg["boton_dxf"] is not None:
            st.download_button(label="📥 Descargar Plano AutoCAD (DXF)", data=msg["boton_dxf"], file_name=nombre_dxf_descarga, mime="application/dxf", key=str(len(st.session_state.mensajes)))

# --- 4. LÓGICA DE PROCESAMIENTO ---
if prompt_usuario := st.chat_input("Ej. Distribuir extintores, detectores, BIE y luces de emergencia."):
    
    with st.chat_message("user"):
        st.markdown(prompt_usuario)
    st.session_state.mensajes.append({"rol": "user", "contenido": prompt_usuario})

    with st.chat_message("assistant"):
        with st.spinner("Aplicando normativa estricta y mapeando 8 tipos de dispositivos..."):
            
            resultados = db_collection.query(query_texts=[prompt_usuario], n_results=10)
            contexto_recuperado = "\n\n---\n\n".join(resultados['documents'][0]) if resultados['documents'] else ""
            
            try:
                with open("anexos_limpios.txt", "r", encoding="utf-8") as f:
                    tabla_memoria = f.read()
            except:
                tabla_memoria = ""

            prompt_sistema = f"""
            Eres un ingeniero experto en Prevención contra Incendios.
            NORMATIVA APLICABLE: {contexto_recuperado}
            TABLA: {tabla_memoria}
            CONSULTA: {prompt_usuario}

            INSTRUCCIONES CRÍTICAS DE UBICACIÓN Y CANTIDAD:
            1. Tipos PERMITIDOS: "extintor", "detector", "luz", "cartel", "alarma", "pulsador", "bie", "rociador".
            2. REGLA DE CANTIDAD: NO satures. Coloca solo 1 'cartel' y 1 'luz' justo encima de las puertas principales de SALIDA. Pon 1 'alarma' y 1 'pulsador' por pasillo o área general central, NO en cada habitación. 
            3. UBICACIÓN (x_pct, y_pct de 0 a 100):
               - PAREDES (Junto a puertas): extintor, luz, cartel, pulsador, bie, alarma.
               - TECHO (Centro del cuarto): detector, rociador.

            Formato JSON estrictamente al final:
            ```json
            [
              {{"tipo": "extintor", "x_pct": 15, "y_pct": 20, "label": "Extintor ABC"}},
              {{"tipo": "luz", "x_pct": 12, "y_pct": 10, "label": "Luz Emergencia"}},
              {{"tipo": "bie", "x_pct": 80, "y_pct": 50, "label": "BIE 45mm"}}
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
                            
                            # --- MOTOR 1: DIBUJO EN IMAGEN (PIL) ---
                            if imagen_pil:
                                img_dibujo = imagen_pil.copy().convert("RGB")
                                draw = ImageDraw.Draw(img_dibujo)
                                ancho, alto = img_dibujo.size
                                factor_base = (ancho + alto) / 1000.0
                                font = ImageFont.load_default(size=max(int(factor_base * 10), 12))
                                
                                posiciones_usadas_img = []
                                
                                for disp in datos_dispositivos:
                                    if 'x_pct' in disp and 'y_pct' in disp:
                                        tipo_key = disp['tipo'].lower()
                                        if tipo_key not in CATALOGO: continue
                                            
                                        config = CATALOGO[tipo_key]
                                        px = int((disp['x_pct'] / 100) * ancho)
                                        py = int((disp['y_pct'] / 100) * alto)
                                        r = int(factor_base * 6.0)
                                        
                                        # Anti-Colisión Imagen
                                        for ux, uy in posiciones_usadas_img:
                                            if math.hypot(px - ux, py - uy) < (r * 3):
                                                px += r * 2.5
                                                py += r * 2.5
                                        posiciones_usadas_img.append((px, py))
                                        
                                        # DIBUJO SEGÚN FORMA
                                        if config['forma'] == 'cuadrado':
                                            draw.rectangle([px-r, py-r, px+r, py+r], fill=config['rgb'], outline="black", width=2)
                                        elif config['forma'] == 'circulo':
                                            draw.ellipse([px-r, py-r, px+r, py+r], fill=config['rgb'], outline="white" if tipo_key=='detector' else "black", width=2)
                                        elif config['forma'] == 'triangulo':
                                            draw.polygon([(px, py-r), (px-r, py+r), (px+r, py+r)], fill=config['rgb'], outline="black")
                                            
                                        draw.text((px + int(r * 1.5), py - int(r/2)), disp['label'], fill="black", font=font, stroke_width=2, stroke_fill="white")
                                
                                st.image(img_dibujo, caption="Plano Visual", use_container_width=True)
                                imagen_final_mostrar = img_dibujo

                            # --- MOTOR 2: INYECCIÓN EXACTA EN DXF ---
                            if dxf_doc and 'dxf_bounds' in st.session_state:
                                msp = dxf_doc.modelspace()
                                min_x, min_y, max_x, max_y, ancho_dxf, alto_dxf = st.session_state['dxf_bounds']
                                
                                radio_base_cad = min(ancho_dxf, alto_dxf) * 0.008 
                                alto_texto = radio_base_cad * 0.8
                                
                                posiciones_usadas_cad = []

                                for disp in datos_dispositivos:
                                    if 'x_pct' in disp and 'y_pct' in disp:
                                        tipo_key = disp['tipo'].lower()
                                        if tipo_key not in CATALOGO: continue
                                        
                                        config = CATALOGO[tipo_key]
                                        
                                        # MAPEO MATEMÁTICO PERFECTO (Sin desfases)
                                        dxf_x = min_x + (disp['x_pct'] / 100.0) * ancho_dxf
                                        dxf_y = max_y - (disp['y_pct'] / 100.0) * alto_dxf
                                        
                                        # ANTI-COLISIÓN CAD
                                        intentos = 0
                                        while intentos < 15:
                                            colision = False
                                            for ux, uy in posiciones_usadas_cad:
                                                if math.hypot(dxf_x - ux, dxf_y - uy) < (radio_base_cad * 3):
                                                    dxf_x += radio_base_cad * 2.5
                                                    dxf_y -= radio_base_cad * 2.5
                                                    colision = True
                                                    break
                                            if not colision: break
                                            intentos += 1
                                        
                                        posiciones_usadas_cad.append((dxf_x, dxf_y))
                                        
                                        color_cad = config['cad']
                                        r_cad = radio_base_cad * 0.7 if tipo_key == 'rociador' else radio_base_cad
                                        
                                        # INYECCIÓN VECTORIAL SEGÚN FORMA EN AUTOCAD
                                        if config['forma'] == 'cuadrado':
                                            p1 = (dxf_x-r_cad, dxf_y-r_cad)
                                            p2 = (dxf_x+r_cad, dxf_y-r_cad)
                                            p3 = (dxf_x+r_cad, dxf_y+r_cad)
                                            p4 = (dxf_x-r_cad, dxf_y+r_cad)
                                            msp.add_lwpolyline([p1, p2, p3, p4], close=True, dxfattribs={'color': color_cad})
                                        elif config['forma'] == 'triangulo':
                                            p1 = (dxf_x, dxf_y+r_cad)
                                            p2 = (dxf_x-r_cad, dxf_y-r_cad)
                                            p3 = (dxf_x+r_cad, dxf_y-r_cad)
                                            msp.add_lwpolyline([p1, p2, p3], close=True, dxfattribs={'color': color_cad})
                                        elif config['forma'] == 'circulo':
                                            msp.add_circle((dxf_x, dxf_y), radius=r_cad, dxfattribs={'color': color_cad})
                                            
                                        msp.add_text(disp['label'], dxfattribs={'height': alto_texto, 'color': color_cad}).set_placement((dxf_x + r_cad*1.5, dxf_y))
                                
                                with tempfile.NamedTemporaryFile(delete=False, suffix=".dxf") as tmp_out:
                                    dxf_doc.saveas(tmp_out.name)
                                    tmp_out_path = tmp_out.name
                                with open(tmp_out_path, "rb") as f:
                                    dxf_buffer_descarga = f.read()
                                
                                st.success("📐 ¡Plano vectorial procesado con los 8 tipos de dispositivos!")
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
