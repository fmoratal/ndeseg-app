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
st.title("🔥 NDEseg: Procesamiento Inteligente de Planos")
st.markdown("Sube tu plano en el formato que tengas (**Imagen, PDF o DXF**) para generar el informe técnico legal y los planos modificados.")

# El cargador ahora acepta cualquier combinación
archivos_subidos = st.file_uploader("📂 Sube tus archivos (Puedes subir uno solo o varios)", type=["png", "jpg", "jpeg", "pdf", "dxf"], accept_multiple_files=True)

imagen_pil = None
dxf_doc = None
textos_cad_extraidos = []
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
                
                # Extraemos los textos del modelo CAD para darle contexto a la IA si no hay imagen
                msp = dxf_doc.modelspace()
                for entity in msp.query('TEXT MTEXT'):
                    txt = entity.dxf.text if entity.dxftype() == 'TEXT' else entity.text
                    txt_limpio = re.sub(r'\\P|\\{.*?\\}', ' ', txt).strip()
                    if txt_limpio and len(txt_limpio) > 2:
                        pos = entity.dxf.insert
                        textos_cad_extraidos.append({"sala": txt_limpio, "x": pos.x, "y": pos.y})
            except Exception as e:
                st.error(f"Error al procesar el archivo DXF: {e}")

if imagen_pil:
    st.image(imagen_pil, caption="Vista previa del plano", use_container_width=True)

# Memoria del chat
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
if prompt_usuario := st.chat_input("Ej. ¿Qué dispositivos de seguridad contra incendios corresponden?"):
    
    with st.chat_message("user"):
        st.markdown(prompt_usuario)
    st.session_state.mensajes.append({"rol": "user", "contenido": prompt_usuario})

    with st.chat_message("assistant"):
        with st.spinner("Procesando ingeniería normativa..."):
            
            resultados = db_collection.query(query_texts=[prompt_usuario], n_results=10)
            contexto_recuperado = "\n\n---\n\n".join(resultados['documents'][0]) if resultados['documents'] else ""
            
            tabla_memoria = ""
            try:
                with open("anexos_limpios.txt", "r", encoding="utf-8") as f:
                    tabla_memoria = f.read()
            except:
                pass
            
            # Construimos un contexto dinámico del plano para la IA si es solo texto vectorial
            contexto_estructural_dxf = ""
            if textos_cad_extraidos:
                contexto_estructural_dxf = f"\nESTRUCTURA GEOMÉTRICA DETECTADA EN DXF (Nombres de salas y coordenadas):\n{json.dumps(textos_cad_extraidos)}"

            prompt_sistema = f"""
            Eres un ingeniero experto en Prevención contra Incendios. Tu objetivo es dictar un Informe Técnico completo basándote en la ley.
            
            NORMATIVA APLICABLE:
            {contexto_recuperado}
            
            TABLA DE ANEXOS:
            {tabla_memoria}
            
            CONSULTA DEL USUARIO:
            {prompt_usuario}
            {contexto_estructural_dxf}

            INSTRUCCIONES DE COORDENADAS:
            - Si hay una imagen/PDF adjunto, devuelve coordenadas aproximadas por PORCENTAJE (0 a 100) en base a lo que ves visualmente.
            - Si NO hay imagen pero se te proveyó la "ESTRUCTURA GEOMÉTRICA DETECTADA EN DXF", debes leer los nombres de las salas y asignar las coordenadas EXACTAS (X, Y) que tienen esas etiquetas en la lista de arriba para colocar los dispositivos en los lugares correctos.

            Formato JSON requerido estrictamente al final:
            ```json
            [
              {{"tipo": "extintor", "x_pct": 15, "y_pct": 20, "label": "Extintor ABC 4kg", "cad_x": 145.2, "cad_y": 320.1}},
              {{"tipo": "detector", "x_pct": 45, "y_pct": 50, "label": "Detector Humo", "cad_x": 180.5, "cad_y": 210.4}}
            ]
            ```
            (Si usas porcentajes pon los valores en x_pct e y_pct. Si usas coordenadas CAD cópialas directamente en cad_x y cad_y).
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
                        
                        # --- MOTOR 1: DIBUJO EN IMAGEN (Si se subió imagen o PDF) ---
                        if imagen_pil:
                            try:
                                img_dibujo = imagen_pil.copy().convert("RGB")
                                draw = ImageDraw.Draw(img_dibujo)
                                ancho, alto = img_dibujo.size
                                factor_base = (ancho + alto) / 1000.0
                                font = ImageFont.load_default(size=max(int(factor_base * 12), 16))
                                
                                for disp in datos_dispositivos:
                                    if 'x_pct' in disp and disp['x_pct'] is not None:
                                        px = int((disp['x_pct'] / 100) * ancho)
                                        py = int((disp['y_pct'] / 100) * alto)
                                        r = int(factor_base * 9.0)
                                        
                                        if disp['tipo'] == 'extintor':
                                            draw.rectangle([px-r, py-r, px+r, py+r], fill=(255, 0, 0), outline="black", width=2)
                                        elif disp['tipo'] == 'detector':
                                            draw.ellipse([px-r, py-r, px+r, py+r], fill=(0, 0, 255), outline="white", width=2)
                                        else:
                                            draw.ellipse([px-r, py-r, px+r, py+r], fill=(255, 255, 0), outline="black", width=2)
                                        draw.text((px + int(r * 1.5), py - int(r/2)), disp['label'], fill="black", font=font, stroke_width=2, stroke_fill="white")
                                
                                st.image(img_dibujo, caption="Plano Visual con Dispositivos Ubicados", use_container_width=True)
                                imagen_final_mostrar = img_dibujo
                            except Exception as e:
                                st.warning(f"Error en renderizado visual: {e}")

                        # --- MOTOR 2: INYECCIÓN VECTORIAL EN DXF (Si se subió archivo AutoCAD) ---
                        if dxf_doc:
                            try:
                                msp = dxf_doc.modelspace()
                                extents = bbox.extents(msp)
                                
                                for disp in datos_dispositivos:
                                    # Si la IA nos dio coordenadas CAD directas del mapeo de texto, las usamos. 
                                    # Si no, las calculamos mediante interpolación proporcional de la caja de límites.
                                    if 'cad_x' in disp and disp['cad_x'] is not None:
                                        dxf_x = disp['cad_x']
                                        dxf_y = disp['cad_y']
                                        radio_cad = 15.0 # Radio estándar estimado si es puntual
                                    elif extents.has_data:
                                        min_x, min_y = extents.extmin.x, extents.extmin.y
                                        max_x, max_y = extents.extmax.x, extents.extmax.y
                                        dxf_x = min_x + (disp['x_pct'] / 100.0) * (max_x - min_x)
                                        dxf_y = max_y - (disp['y_pct'] / 100.0) * (max_y - min_y)
                                        radio_cad = (max_x - min_x) * 0.012
                                    else:
                                        continue
                                    
                                    # Inyectamos las entidades nativas en AutoCAD
                                    color_cad = 1 if disp['tipo'] == 'extintor' else (5 if disp['tipo'] == 'detector' else 2)
                                    msp.add_circle((dxf_x, dxf_y), radius=radio_cad, dxfattribs={'color': color_cad})
                                    msp.add_text(disp['label'], dxfattribs={'height': radio_cad*1.2, 'color': color_cad}).set_placement((dxf_x + radio_cad*1.5, dxf_y))
                                
                                with tempfile.NamedTemporaryFile(delete=False, suffix=".dxf") as tmp_out:
                                    dxf_doc.saveas(tmp_out.name)
                                    tmp_out_path = tmp_out.name
                                with open(tmp_out_path, "rb") as f:
                                    dxf_buffer_descarga = f.read()
                                
                                st.success("📐 ¡Tu plano vectorial de AutoCAD ha sido procesado de forma nativa!")
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
