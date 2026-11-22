import os
import uuid
from fastapi.staticfiles import StaticFiles
from datetime import date, datetime, timedelta, timezone
from fastapi import FastAPI, HTTPException, Depends, Header, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from supabase import create_client, Client
from dotenv import load_dotenv


load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

app = FastAPI(title="Entre Nubes API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- MODELOS PYDANTIC ---
class RegistroRequest(BaseModel):
    nombre_completo: str
    correo: EmailStr
    telefono: str
    password: str

class LoginRequest(BaseModel):
    correo: EmailStr
    password: str

class ActualizarPerfilRequest(BaseModel):
    nombre_completo: str
    telefono: str | None = None

class CrearReservaRequest(BaseModel):
    alojamiento_id: str
    fecha_entrada: date
    fecha_salida: date
    num_huespedes: int = 2

# --- DEPENDENCIA DE AUTENTICACIÓN ---
def obtener_usuario_actual(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Debes iniciar sesión para continuar.")
    
    token = authorization.split(" ")[1]
    try:
        user_response = supabase.auth.get_user(token)
        user_id = user_response.user.id
        perfil = supabase.table("perfiles").select("*").eq("id", user_id).single().execute()
        return perfil.data
    except Exception:
        raise HTTPException(status_code=401, detail="Sesión inválida o expirada.")

# --- BLOQUE 1: AUTENTICACIÓN Y USUARIO ---
@app.post("/api/auth/registro")
def registrar_usuario(datos: RegistroRequest):
    try:
        auth_res = supabase.auth.sign_up({"email": datos.correo, "password": datos.password})
        if not auth_res.user:
            raise HTTPException(status_code=400, detail="No se pudo crear el usuario")

        perfil_data = {
            "id": auth_res.user.id,
            "nombre_completo": datos.nombre_completo,
            "correo": datos.correo,
            "telefono": datos.telefono,
            "rol": "huesped"
        }
        supabase.table("perfiles").insert(perfil_data).execute()
        token = auth_res.session.access_token if auth_res.session else None
        return {"jwt": token, "user": perfil_data}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/auth/login")
def iniciar_sesion(datos: LoginRequest):
    try:
        auth_res = supabase.auth.sign_in_with_password({"email": datos.correo, "password": datos.password})
        perfil = supabase.table("perfiles").select("*").eq("id", auth_res.user.id).single().execute()
        return {"jwt": auth_res.session.access_token, "user": perfil.data}
    except Exception:
        raise HTTPException(status_code=401, detail="Correo o contraseña incorrectos")

@app.get("/api/usuarios/me")
def ver_mi_perfil(usuario = Depends(obtener_usuario_actual)):
    return usuario

@app.put("/api/usuarios/me")
def actualizar_mi_perfil(datos: ActualizarPerfilRequest, usuario = Depends(obtener_usuario_actual)):
    update_data = {"nombre_completo": datos.nombre_completo}
    if datos.telefono is not None:
        update_data["telefono"] = datos.telefono
    res = supabase.table("perfiles").update(update_data).eq("id", usuario["id"]).execute()
    return res.data[0]

@app.get("/api/usuarios/me/reservaciones")
def mis_reservaciones(usuario = Depends(obtener_usuario_actual)):
    supabase.rpc("liberar_reservas_expiradas").execute()
    res = (
        supabase.table("reservaciones")
        .select("*, alojamientos(titulo, imagenes, direccion)")
        .eq("huesped_id", usuario["id"])
        .order("creado_en", desc=True)
        .execute()
    )
    return res.data

# --- BLOQUE 2: CATÁLOGO, RESERVAS Y COMPROBANTE SPEI ---
@app.get("/api/alojamientos")
def listar_alojamientos(capacidad: int | None = None, tipo: str | None = None):
    query = supabase.table("alojamientos").select("*").eq("activo", True)
    if capacidad:
        query = query.gte("capacidad_huespedes", capacidad)
    if tipo:
        query = query.ilike("tipo", f"%{tipo}%")
    res = query.order("creado_en", desc=True).execute()
    return res.data

@app.get("/api/alojamientos/{alojamiento_id}")
def detalle_alojamiento(alojamiento_id: str):
    res = (
        supabase.table("alojamientos")
        .select("*, perfiles(nombre_completo, correo)")
        .eq("id", alojamiento_id)
        .single()
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="Alojamiento no encontrado")
    return res.data

@app.post("/api/reservaciones")
def crear_reservacion(datos: CrearReservaRequest, usuario = Depends(obtener_usuario_actual)):
    noches = (datos.fecha_salida - datos.fecha_entrada).days
    if noches <= 0:
        raise HTTPException(status_code=400, detail="La fecha de salida debe ser posterior a la llegada.")

    # Obtener precio real del alojamiento desde la DB
    aloj = supabase.table("alojamientos").select("*").eq("id", datos.alojamiento_id).single().execute()
    if not aloj.data:
        raise HTTPException(status_code=404, detail="Alojamiento no encontrado")

    tarifa_servicio = 350.00
    total_pagar = (float(aloj.data["precio_noche"]) * noches) + tarifa_servicio

    # Obtener tiempo de expiración desde configuración (default 15 min)
    config = supabase.table("configuracion_plataforma").select("*").eq("id", 1).single().execute()
    minutos = config.data["tiempo_pago_minutos"] if config.data else 15
    expira_en = (datetime.now(timezone.utc) + timedelta(minutes=minutos)).isoformat()

    nueva_reserva = {
        "alojamiento_id": datos.alojamiento_id,
        "huesped_id": usuario["id"],
        "fecha_entrada": datos.fecha_entrada.isoformat(),
        "fecha_salida": datos.fecha_salida.isoformat(),
        "num_huespedes": datos.num_huespedes,
        "tarifa_servicio": tarifa_servicio,
        "total_pagar": total_pagar,
        "estado": "pendiente_pago",
        "pago_expira_en": expira_en
    }

    try:
        res = supabase.table("reservaciones").insert(nueva_reserva).execute()
        return res.data[0]
    except Exception as e:
        msg = str(e)
        if "no está disponible" in msg:
            raise HTTPException(status_code=409, detail="El alojamiento ya está apartado o reservado en esas fechas.")
        raise HTTPException(status_code=400, detail=msg)

@app.get("/api/reservaciones/{reserva_id}")
def detalle_reservacion(reserva_id: str, usuario = Depends(obtener_usuario_actual)):
    # Liberar vencidas antes de consultar
    supabase.rpc("liberar_reservas_expiradas").execute()

    res = (
        supabase.table("reservaciones")
        .select("*, alojamientos(titulo, direccion, tipo, precio_noche, imagenes), perfiles(nombre_completo, correo, telefono)")
        .eq("id", reserva_id)
        .single()
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="Reservación no encontrada")

    # Solo el dueño o el admin pueden ver el recibo
    if res.data["huesped_id"] != usuario["id"] and usuario["rol"] != "admin":
        raise HTTPException(status_code=403, detail="No tienes permiso para ver esta reservación")

    config = supabase.table("configuracion_plataforma").select("*").eq("id", 1).single().execute()
    return {
        "reserva": res.data,
        "datos_spei": config.data
    }

@app.post("/api/reservaciones/{reserva_id}/comprobante")
async def subir_comprobante(
    reserva_id: str,
    archivo: UploadFile = File(...),
    usuario = Depends(obtener_usuario_actual)
):
    supabase.rpc("liberar_reservas_expiradas").execute()

    res = supabase.table("reservaciones").select("*").eq("id", reserva_id).single().execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Reservación no encontrada")
    
    reserva = res.data
    if reserva["huesped_id"] != usuario["id"]:
        raise HTTPException(status_code=403, detail="No autorizado")
    if reserva["estado"] != "pendiente_pago":
        raise HTTPException(status_code=400, detail=f"No se puede subir comprobante. Estado actual: {reserva['estado']}")

    # Subir archivo al bucket privado 'comprobantes'
    ext = archivo.filename.split(".")[-1] if "." in archivo.filename else "jpg"
    ruta_storage = f"{usuario['id']}/{reserva_id}_{uuid.uuid4().hex[:6]}.{ext}"
    contenido = await archivo.read()

    supabase.storage.from_("comprobantes").upload(
        path=ruta_storage,
        file=contenido,
        file_options={"content-type": archivo.content_type}
    )

    # Actualizar reserva a 'en_revision' y dar 24 horas al admin
    config = supabase.table("configuracion_plataforma").select("*").eq("id", 1).single().execute()
    horas = config.data["tiempo_revision_horas"] if config.data else 24
    revision_expira = (datetime.now(timezone.utc) + timedelta(hours=horas)).isoformat()

    actualizada = supabase.table("reservaciones").update({
        "estado": "en_revision",
        "comprobante_url": ruta_storage,
        "revision_expira_en": revision_expira
    }).eq("id", reserva_id).execute()

    # Notificar a todos los administradores
    admins = supabase.table("perfiles").select("id").eq("rol", "admin").execute()
    for admin in admins.data:
        supabase.table("notificaciones").insert({
            "usuario_id": admin["id"],
            "titulo": "Nuevo comprobante SPEI recibido",
            "mensaje": f"{usuario['nombre_completo']} subió un comprobante por ${reserva['total_pagar']} MXN. Tienes {horas}h para validar.",
            "reservacion_id": reserva_id
        }).execute()

    return {"mensaje": "Comprobante enviado a revisión", "reserva": actualizada.data[0]}

@app.put("/api/reservaciones/{reserva_id}/cancelar")
def cancelar_mi_reserva(reserva_id: str, usuario = Depends(obtener_usuario_actual)):
    res = (
        supabase.table("reservaciones")
        .update({"estado": "cancelada"})
        .eq("id", reserva_id)
        .eq("huesped_id", usuario["id"])
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="Reservación no encontrada")
    return {"mensaje": "Reservación cancelada", "reserva": res.data[0]}

from fastapi import FastAPI, HTTPException, Depends, Header, UploadFile, File, Form
from typing import List

# --- BLOQUE 3: PANEL ANFITRIÓN ---
def requerir_anfitrion(usuario = Depends(obtener_usuario_actual)):
    if usuario["rol"] not in ("anfitrion", "admin"):
        raise HTTPException(status_code=403, detail="Acceso exclusivo para anfitriones o administradores.")
    return usuario

@app.get("/api/anfitrion/alojamientos")
def listar_mis_alojamientos(usuario = Depends(requerir_anfitrion)):
    query = supabase.table("alojamientos").select("*")
    if usuario["rol"] == "anfitrion":
        query = query.eq("anfitrion_id", usuario["id"])
    res = query.order("creado_en", desc=True).execute()
    return res.data

@app.post("/api/anfitrion/alojamientos")
async def crear_alojamiento(
    nombre: str = Form(...),
    tipo: str = Form(...),
    precio: float = Form(...),
    acerca: str = Form(...),
    direccion: str = Form(...),
    ciudad: str = Form("Capulálpam de Méndez"),
    estado: str = Form("Oaxaca"),
    latitud: str = Form(""),
    longitud: str = Form(""),
    amenidades: List[str] = Form([]),
    imagenes: List[UploadFile] = File([]),
    usuario = Depends(requerir_anfitrion)
):
    urls_imagenes = []
    for img in imagenes:
        if img.filename:
            ext = img.filename.split(".")[-1] if "." in img.filename else "jpg"
            ruta = f"{usuario['id']}/{uuid.uuid4().hex[:10]}.{ext}"
            contenido = await img.read()
            supabase.storage.from_("alojamientos").upload(
                path=ruta,
                file=contenido,
                file_options={"content-type": img.content_type}
            )
            url_publica = supabase.storage.from_("alojamientos").get_public_url(ruta)
            urls_imagenes.append(url_publica)

    nuevo = {
        "anfitrion_id": usuario["id"],
        "titulo": nombre,
        "tipo": tipo,
        "precio_noche": precio,
        "descripcion": acerca,
        "direccion": direccion,
        "ciudad": ciudad,
        "estado": estado,
        "latitud": latitud,
        "longitud": longitud,
        "amenidades": amenidades,
        "imagenes": urls_imagenes,
        "capacidad_huespedes": 4,
        "habitaciones": 1,
        "banos": 1,
        "activo": True
    }
    res = supabase.table("alojamientos").insert(nuevo).execute()
    return res.data[0]

@app.get("/api/anfitrion/reservaciones")
def reservaciones_anfitrion(usuario = Depends(requerir_anfitrion)):
    supabase.rpc("liberar_reservas_expiradas").execute()

    # Obtener IDs de alojamientos del anfitrión
    aloj_q = supabase.table("alojamientos").select("id")
    if usuario["rol"] == "anfitrion":
        aloj_q = aloj_q.eq("anfitrion_id", usuario["id"])
    aloj_ids = [a["id"] for a in aloj_q.execute().data]

    if not aloj_ids:
        return []

    res = (
        supabase.table("reservaciones")
        .select("*, alojamientos(titulo), perfiles(nombre_completo, correo, telefono)")
        .in_("alojamiento_id", aloj_ids)
        .order("creado_en", desc=True)
        .execute()
    )
    return res.data

@app.get("/api/anfitrion/huespedes")
def huespedes_anfitrion(usuario = Depends(requerir_anfitrion)):
    reservas = reservaciones_anfitrion(usuario)
    mapa = {}
    for r in reservas:
        p = r.get("perfiles") or {}
        hid = r["huesped_id"]
        if hid not in mapa:
            mapa[hid] = {
                "id": hid,
                "nombre_completo": p.get("nombre_completo", "Huésped"),
                "correo": p.get("correo", ""),
                "telefono": p.get("telefono", ""),
                "total_reservas": 0,
                "ultimo_estado": r["estado"],
                "ultimo_viaje": r["fecha_entrada"],
                "huespedes": r["num_huespedes"]
            }
        mapa[hid]["total_reservas"] += 1
    return list(mapa.values())
# --- BLOQUE 4: PANEL ADMINISTRADOR ---
class ValidarReservaRequest(BaseModel):
    accion: str  # "aprobar" o "rechazar"
    notas_admin: str | None = ""

class ConfigPlataformaRequest(BaseModel):
    banco: str
    titular: str
    clabe_spei: str
    tiempo_pago_minutos: int = 15
    tiempo_revision_horas: int = 24

def requerir_admin(usuario = Depends(obtener_usuario_actual)):
    if usuario["rol"] != "admin":
        raise HTTPException(status_code=403, detail="Acceso exclusivo para administradores.")
    return usuario

@app.get("/api/admin/resumen")
def resumen_admin(usuario = Depends(requerir_admin)):
    supabase.rpc("liberar_reservas_expiradas").execute()

    alojamientos = supabase.table("alojamientos").select("*").order("creado_en", desc=True).execute().data
    reservas = (
        supabase.table("reservaciones")
        .select("*, alojamientos(titulo), perfiles(nombre_completo, correo)")
        .order("creado_en", desc=True)
        .execute()
        .data
    )
    notifs = (
        supabase.table("notificaciones")
        .select("*")
        .eq("usuario_id", usuario["id"])
        .eq("leida", False)
        .execute()
        .data
    )
    return {
        "alojamientos": alojamientos,
        "reservaciones": reservas,
        "notificaciones_sin_leer": len(notifs)
    }

@app.get("/api/admin/reservaciones")
def listar_todas_reservaciones(usuario = Depends(requerir_admin)):
    supabase.rpc("liberar_reservas_expiradas").execute()
    res = (
        supabase.table("reservaciones")
        .select("*, alojamientos(titulo), perfiles(nombre_completo, correo, telefono)")
        .order("creado_en", desc=True)
        .execute()
    )
    return res.data

@app.get("/api/admin/reservaciones/{reserva_id}/comprobante")
def obtener_url_comprobante(reserva_id: str, usuario = Depends(requerir_admin)):
    res = supabase.table("reservaciones").select("comprobante_url").eq("id", reserva_id).single().execute()
    if not res.data or not res.data.get("comprobante_url"):
        raise HTTPException(status_code=404, detail="Esta reservación no tiene comprobante adjunto.")
    
    # Genera una URL firmada temporal (válida 5 minutos) desde el bucket privado 'comprobantes'
    signed = supabase.storage.from_("comprobantes").create_signed_url(res.data["comprobante_url"], 300)
    url = signed.get("signedURL") or signed.get("signedUrl")
    return {"url": url}

@app.put("/api/admin/reservaciones/{reserva_id}/validar")
def validar_reservacion(reserva_id: str, datos: ValidarReservaRequest, usuario = Depends(requerir_admin)):
    supabase.rpc("liberar_reservas_expiradas").execute()

    res = supabase.table("reservaciones").select("*").eq("id", reserva_id).single().execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Reservación no encontrada")

    nuevo_estado = "confirmada" if datos.accion == "aprobar" else "cancelada"
    actualizada = supabase.table("reservaciones").update({
        "estado": nuevo_estado,
        "notas_admin": datos.notas_admin
    }).eq("id", reserva_id).execute()

    # Notificar al huésped
    titulo_notif = "¡Reservación confirmada!" if nuevo_estado == "confirmada" else "Comprobante rechazado"
    msg_notif = (
        "Tu pago SPEI fue validado por el administrador. ¡Te esperamos!"
        if nuevo_estado == "confirmada"
        else f"Tu comprobante no pudo ser validado y las fechas fueron liberadas. {datos.notas_admin or ''}"
    )
    supabase.table("notificaciones").insert({
        "usuario_id": res.data["huesped_id"],
        "titulo": titulo_notif,
        "mensaje": msg_notif,
        "reservacion_id": reserva_id
    }).execute()

    return {"mensaje": f"Reservación marcada como {nuevo_estado}", "reserva": actualizada.data[0]}

@app.get("/api/admin/configuracion")
def obtener_configuracion(usuario = Depends(requerir_admin)):
    res = supabase.table("configuracion_plataforma").select("*").eq("id", 1).single().execute()
    return res.data

@app.put("/api/admin/configuracion")
def actualizar_configuracion(datos: ConfigPlataformaRequest, usuario = Depends(requerir_admin)):
    res = supabase.table("configuracion_plataforma").update({
        "banco": datos.banco,
        "titular": datos.titular,
        "clabe_spei": datos.clabe_spei,
        "tiempo_pago_minutos": datos.tiempo_pago_minutos,
        "tiempo_revision_horas": datos.tiempo_revision_horas
    }).eq("id", 1).execute()
    return res.data[0]
# --- BLOQUE 4B: ANFITRIONES, HUÉSPEDES Y RESEÑAS (ADMIN) ---
class CrearAnfitrionRequest(BaseModel):
    nombre_completo: str
    correo: EmailStr
    password: str
    telefono: str | None = ""

@app.get("/api/admin/anfitriones")
def listar_anfitriones(usuario = Depends(requerir_admin)):
    anfitriones = supabase.table("perfiles").select("*").eq("rol", "anfitrion").order("creado_en", desc=True).execute().data
    alojamientos = supabase.table("alojamientos").select("id, anfitrion_id").execute().data

    conteo = {}
    for a in alojamientos:
        aid = a["anfitrion_id"]
        conteo[aid] = conteo.get(aid, 0) + 1

    for anf in anfitriones:
        anf["total_propiedades"] = conteo.get(anf["id"], 0)
    return anfitriones

@app.post("/api/admin/anfitriones")
def crear_anfitrion(datos: CrearAnfitrionRequest, usuario = Depends(requerir_admin)):
    try:
        auth_res = supabase.auth.admin.create_user({
            "email": datos.correo,
            "password": datos.password,
            "email_confirm": True
        })
        perfil = {
            "id": auth_res.user.id,
            "nombre_completo": datos.nombre_completo,
            "correo": datos.correo,
            "telefono": datos.telefono,
            "rol": "anfitrion",
            "activo": True
        }
        supabase.table("perfiles").insert(perfil).execute()
        return perfil
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/admin/huespedes")
def listar_huespedes_admin(usuario = Depends(requerir_admin)):
    huespedes = supabase.table("perfiles").select("*").eq("rol", "huesped").order("creado_en", desc=True).execute().data
    reservas = supabase.table("reservaciones").select("huesped_id, estado, fecha_entrada").order("creado_en", desc=True).execute().data

    res_por_huesped = {}
    for r in reservas:
        hid = r["huesped_id"]
        if hid not in res_por_huesped:
            res_por_huesped[hid] = {"total": 0, "ultimo_estado": r["estado"], "ultimo_viaje": r["fecha_entrada"]}
        res_por_huesped[hid]["total"] += 1

    for h in huespedes:
        info = res_por_huesped.get(h["id"], {"total": 0, "ultimo_estado": "sin_reservas", "ultimo_viaje": "—"})
        h["total_reservas"] = info["total"]
        h["ultimo_estado"] = info["ultimo_estado"]
        h["ultimo_viaje"] = info["ultimo_viaje"]
    return huespedes

@app.get("/api/admin/resenas")
def listar_resenas_admin(usuario = Depends(requerir_admin)):
    res = (
        supabase.table("resenas")
        .select("*, alojamientos(titulo), perfiles(nombre_completo)")
        .order("creado_en", desc=True)
        .execute()
    )
    return res.data

# Servir la carpeta frontend desde FastAPI (debe ir al final del archivo)
frontend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
if os.path.exists(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")