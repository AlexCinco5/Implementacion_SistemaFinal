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
        auth_client = create_client(SUPABASE_URL, SUPABASE_KEY)
        auth_res = auth_client.auth.sign_up({"email": datos.correo, "password": datos.password})
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
        auth_client = create_client(SUPABASE_URL, SUPABASE_KEY)
        auth_res = auth_client.auth.sign_in_with_password({"email": datos.correo, "password": datos.password})
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
def listar_alojamientos(
    capacidad: int | None = None,
    tipo: str | None = None,
    fecha_entrada: date | None = None,
    fecha_salida: date | None = None
):
    supabase.rpc("liberar_reservas_expiradas").execute()

    query = supabase.table("alojamientos").select("*").eq("activo", True)
    if capacidad:
        query = query.gte("capacidad_huespedes", capacidad)
    if tipo:
        query = query.ilike("tipo", f"%{tipo}%")
    alojamientos = query.order("creado_en", desc=True).execute().data or []

    if fecha_entrada and fecha_salida:
        if fecha_salida <= fecha_entrada:
            raise HTTPException(status_code=400, detail="La fecha de salida debe ser posterior a la llegada.")
        ocupadas = (
            supabase.table("reservaciones")
            .select("alojamiento_id")
            .in_("estado", ["pendiente_pago", "en_revision", "confirmada"])
            .lt("fecha_entrada", fecha_salida.isoformat())
            .gt("fecha_salida", fecha_entrada.isoformat())
            .execute()
            .data or []
        )
        ids_ocupados = {r["alojamiento_id"] for r in ocupadas}
        alojamientos = [a for a in alojamientos if a["id"] not in ids_ocupados]

    return alojamientos

@app.get("/api/alojamientos/{alojamiento_id}/disponibilidad")
def disponibilidad_alojamiento(alojamiento_id: str):
    supabase.rpc("liberar_reservas_expiradas").execute()
    hoy = date.today().isoformat()
    res = (
        supabase.table("reservaciones")
        .select("fecha_entrada, fecha_salida, estado")
        .eq("alojamiento_id", alojamiento_id)
        .in_("estado", ["pendiente_pago", "en_revision", "confirmada"])
        .gte("fecha_salida", hoy)
        .order("fecha_entrada")
        .execute()
    )
    return {"rangos_ocupados": res.data or []}

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

    aloj = supabase.table("alojamientos").select("*").eq("id", datos.alojamiento_id).single().execute()
    if not aloj.data:
        raise HTTPException(status_code=404, detail="Alojamiento no encontrado")

    tarifa_servicio = 350.00
    total_pagar = (float(aloj.data["precio_noche"]) * noches) + tarifa_servicio

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
        creada = res.data[0]
    except Exception as e:
        msg = str(e)
        if "no está disponible" in msg:
            raise HTTPException(status_code=409, detail="El alojamiento ya está apartado o reservado en esas fechas.")
        raise HTTPException(status_code=400, detail=msg)

    titulo_aloj = aloj.data.get("titulo", "tu alojamiento")
    anfitrion_id = aloj.data.get("anfitrion_id")
    fechas = f"{datos.fecha_entrada} al {datos.fecha_salida}"

    # Notificar al huésped
    crear_notificacion(
        usuario["id"],
        "Reservación apartada · Sube tu comprobante",
        f"Apartaste {titulo_aloj} ({fechas}) por ${total_pagar:,.2f} MXN. Tienes {minutos} min para subir tu comprobante SPEI.",
        creada["id"]
    )

    # Notificar al anfitrión
    if anfitrion_id and anfitrion_id != usuario["id"]:
        crear_notificacion(
            anfitrion_id,
            "Nueva solicitud de reservación",
            f"{usuario['nombre_completo']} apartó {titulo_aloj} ({fechas}) por ${total_pagar:,.2f} MXN. En espera de comprobante SPEI.",
            creada["id"]
        )

    return creada


@app.get("/api/reservaciones/{reserva_id}")
def detalle_reservacion(reserva_id: str, usuario = Depends(obtener_usuario_actual)):
    # Liberar vencidas antes de consultar
    supabase.rpc("liberar_reservas_expiradas").execute()

    res = (
        supabase.table("reservaciones")
        .select("*, alojamientos(titulo, direccion, tipo, precio_noche, imagenes, anfitrion_id), perfiles(nombre_completo, correo, telefono)")
        .eq("id", reserva_id)
        .single()
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="Reservación no encontrada")

    # Solo el dueño o el admin pueden ver el recibo
    if res.data["huesped_id"] != usuario["id"] and usuario["rol"] != "admin":
        raise HTTPException(status_code=403, detail="No tienes permiso para ver esta reservación")

    # Cuenta de la plataforma (respaldo) y tiempos límite
    config = supabase.table("configuracion_plataforma").select("*").eq("id", 1).single().execute()
    datos_spei = dict(config.data or {})

    # Si el anfitrión ya configuró su cuenta, se muestra la suya
    anfitrion_id = (res.data.get("alojamientos") or {}).get("anfitrion_id")
    if anfitrion_id:
        anf = (
            supabase.table("perfiles")
            .select("banco, titular_cuenta, clabe_spei")
            .eq("id", anfitrion_id)
            .execute()
            .data
        )
        if anf and anf[0].get("clabe_spei"):
            datos_spei["banco"] = anf[0].get("banco")
            datos_spei["titular"] = anf[0].get("titular_cuenta")
            datos_spei["clabe_spei"] = anf[0].get("clabe_spei")

    return {
        "reserva": res.data,
        "datos_spei": datos_spei
    }

@app.post("/api/reservaciones/{reserva_id}/comprobante")
async def subir_comprobante(
    reserva_id: str,
    archivo: UploadFile = File(...),
    usuario = Depends(obtener_usuario_actual)
):
    supabase.rpc("liberar_reservas_expiradas").execute()

    consulta = (
        supabase.table("reservaciones")
        .select("*, alojamientos(titulo, anfitrion_id)")
        .eq("id", reserva_id)
        .execute()
    )
    if not consulta.data:
        raise HTTPException(status_code=404, detail="Reservación no encontrada")

    reserva = consulta.data[0]
    if reserva["huesped_id"] != usuario["id"]:
        raise HTTPException(status_code=403, detail="No autorizado")
    if reserva["estado"] != "pendiente_pago":
        raise HTTPException(status_code=400, detail=f"No se puede subir comprobante. Estado actual: {reserva['estado']}")

    contenido = await archivo.read()
    if not contenido:
        raise HTTPException(status_code=400, detail="El archivo está vacío.")
    if len(contenido) > int(4.5 * 1024 * 1024):
        raise HTTPException(status_code=413, detail="El archivo supera 4.5 MB. Sube una imagen o PDF más ligero.")

    nombre_archivo = archivo.filename or "comprobante.jpg"
    ext = nombre_archivo.rsplit(".", 1)[-1].lower() if "." in nombre_archivo else "jpg"
    ruta_storage = f"{usuario['id']}/{reserva_id}_{uuid.uuid4().hex[:6]}.{ext}"
    content_type = archivo.content_type or "application/octet-stream"

    try:
        supabase.storage.from_("comprobantes").upload(
            path=ruta_storage,
            file=contenido,
            file_options={"content-type": content_type, "upsert": "true"}
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"No se pudo guardar el archivo en Supabase Storage (bucket 'comprobantes'): {str(e)}"
        )

    config = supabase.table("configuracion_plataforma").select("*").eq("id", 1).single().execute()
    horas = config.data["tiempo_revision_horas"] if config.data else 24
    revision_expira = (datetime.now(timezone.utc) + timedelta(hours=horas)).isoformat()

    actualizada = supabase.table("reservaciones").update({
        "estado": "en_revision",
        "comprobante_url": ruta_storage,
        "revision_expira_en": revision_expira
    }).eq("id", reserva_id).execute()

    aloj = reserva.get("alojamientos") or {}
    titulo_aloj = aloj.get("titulo", "el alojamiento")
    anfitrion_id = aloj.get("anfitrion_id")
    monto = float(reserva["total_pagar"])

    # Notificar a administradores
    admins = supabase.table("perfiles").select("id").eq("rol", "admin").execute().data or []
    for admin in admins:
        crear_notificacion(
            admin["id"],
            "Nuevo comprobante SPEI recibido",
            f"{usuario['nombre_completo']} subió un comprobante para {titulo_aloj} por ${monto:,.2f} MXN. Tienes {horas}h para validar.",
            reserva_id
        )

    # Notificar al huésped
    crear_notificacion(
        usuario["id"],
        "Comprobante SPEI en revisión",
        f"Recibimos tu comprobante para {titulo_aloj}. El administrador tiene hasta {horas} horas para validar tu pago.",
        reserva_id
    )

    # Notificar al anfitrión
    if anfitrion_id and anfitrion_id != usuario["id"]:
        crear_notificacion(
            anfitrion_id,
            "Comprobante de pago recibido",
            f"{usuario['nombre_completo']} subió su comprobante SPEI para {titulo_aloj} (${monto:,.2f} MXN). Pendiente de validación del administrador.",
            reserva_id
        )

    return {"mensaje": "Comprobante enviado a revisión", "reserva": actualizada.data[0]}

@app.put("/api/reservaciones/{reserva_id}/cancelar")
def cancelar_mi_reserva(reserva_id: str, usuario = Depends(obtener_usuario_actual)):
    consulta = (
        supabase.table("reservaciones")
        .select("*, alojamientos(titulo, anfitrion_id)")
        .eq("id", reserva_id)
        .eq("huesped_id", usuario["id"])
        .execute()
    )
    if not consulta.data:
        raise HTTPException(status_code=404, detail="Reservación no encontrada")

    reserva = consulta.data[0]
    if reserva["estado"] in ("cancelada", "expirada", "completada"):
        raise HTTPException(status_code=400, detail=f"No se puede cancelar una reservación en estado '{reserva['estado']}'.")

    res = (
        supabase.table("reservaciones")
        .update({"estado": "cancelada"})
        .eq("id", reserva_id)
        .eq("huesped_id", usuario["id"])
        .execute()
    )

    aloj = reserva.get("alojamientos") or {}
    titulo_aloj = aloj.get("titulo", "el alojamiento")
    anfitrion_id = aloj.get("anfitrion_id")
    fechas = f"{reserva['fecha_entrada']} al {reserva['fecha_salida']}"

    # Notificar al huésped
    crear_notificacion(
        usuario["id"],
        "Reservación cancelada",
        f"Cancelaste tu reservación en {titulo_aloj} ({fechas}).",
        reserva_id
    )

    # Notificar al anfitrión
    if anfitrion_id and anfitrion_id != usuario["id"]:
        crear_notificacion(
            anfitrion_id,
            "Reservación cancelada por el huésped",
            f"{usuario['nombre_completo']} canceló su reservación en {titulo_aloj} ({fechas}). Las fechas volvieron a estar disponibles.",
            reserva_id
        )

    # Notificar a administradores
    admins = supabase.table("perfiles").select("id").eq("rol", "admin").execute().data or []
    for admin in admins:
        if admin["id"] not in (usuario["id"], anfitrion_id):
            crear_notificacion(
                admin["id"],
                "Reservación cancelada",
                f"{usuario['nombre_completo']} canceló su reservación en {titulo_aloj} ({fechas}).",
                reserva_id
            )

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
    capacidad: int = Form(4),
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
        "capacidad_huespedes": capacidad,
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

    consulta = (
        supabase.table("reservaciones")
        .select("*, alojamientos(titulo, anfitrion_id), perfiles(nombre_completo)")
        .eq("id", reserva_id)
        .execute()
    )
    if not consulta.data:
        raise HTTPException(status_code=404, detail="Reservación no encontrada")

    reserva = consulta.data[0]
    nuevo_estado = "confirmada" if datos.accion == "aprobar" else "cancelada"
    actualizada = supabase.table("reservaciones").update({
        "estado": nuevo_estado,
        "notas_admin": datos.notas_admin
    }).eq("id", reserva_id).execute()

    aloj = reserva.get("alojamientos") or {}
    perfil_huesped = reserva.get("perfiles") or {}
    titulo_aloj = aloj.get("titulo", "el alojamiento")
    anfitrion_id = aloj.get("anfitrion_id")
    nombre_huesped = perfil_huesped.get("nombre_completo", "El huésped")
    fechas = f"{reserva['fecha_entrada']} al {reserva['fecha_salida']}"
    monto = float(reserva["total_pagar"])

    # Notificar al huésped
    if nuevo_estado == "confirmada":
        crear_notificacion(
            reserva["huesped_id"],
            "¡Reservación confirmada!",
            f"Tu pago SPEI para {titulo_aloj} ({fechas}) fue validado. ¡Te esperamos!",
            reserva_id
        )
    else:
        nota = f" Motivo: {datos.notas_admin}" if datos.notas_admin else ""
        crear_notificacion(
            reserva["huesped_id"],
            "Comprobante rechazado",
            f"Tu comprobante para {titulo_aloj} ({fechas}) no pudo ser validado y las fechas fueron liberadas.{nota}",
            reserva_id
        )

    # Notificar al anfitrión
    if anfitrion_id and anfitrion_id != reserva["huesped_id"]:
        if nuevo_estado == "confirmada":
            crear_notificacion(
                anfitrion_id,
                "¡Reservación confirmada en tu alojamiento!",
                f"Se aprobó el pago de {nombre_huesped} para {titulo_aloj} ({fechas}) por ${monto:,.2f} MXN.",
                reserva_id
            )
        else:
            crear_notificacion(
                anfitrion_id,
                "Pago rechazado · Fechas liberadas",
                f"El comprobante de {nombre_huesped} para {titulo_aloj} ({fechas}) fue rechazado y las fechas quedaron libres nuevamente.",
                reserva_id
            )

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

# --- BLOQUE 5: NOTIFICACIONES (HUÉSPED, ANFITRIÓN Y ADMIN) ---
def crear_notificacion(usuario_id: str | None, titulo: str, mensaje: str, reservacion_id: str | None = None):
    if not usuario_id:
        return
    try:
        payload = {
            "usuario_id": usuario_id,
            "titulo": titulo,
            "mensaje": mensaje,
            "leida": False
        }
        if reservacion_id:
            payload["reservacion_id"] = reservacion_id
        supabase.table("notificaciones").insert(payload).execute()
    except Exception as e:
        print(f"[Notificaciones] Error al insertar para {usuario_id}: {e}")

@app.get("/api/notificaciones")
def listar_notificaciones(usuario = Depends(obtener_usuario_actual)):
    try:
        res = (
            supabase.table("notificaciones")
            .select("*")
            .eq("usuario_id", usuario["id"])
            .order("creado_en", desc=True)
            .limit(30)
            .execute()
        )
        items = res.data or []
    except Exception:
        res = (
            supabase.table("notificaciones")
            .select("*")
            .eq("usuario_id", usuario["id"])
            .limit(30)
            .execute()
        )
        items = res.data or []

    sin_leer = sum(1 for n in items if not n.get("leida"))
    return {"notificaciones": items, "sin_leer": sin_leer}

@app.put("/api/notificaciones/leer-todas")
def marcar_todas_leidas(usuario = Depends(obtener_usuario_actual)):
    supabase.table("notificaciones").update({"leida": True}).eq("usuario_id", usuario["id"]).eq("leida", False).execute()
    return {"mensaje": "Todas las notificaciones marcadas como leídas"}

@app.put("/api/notificaciones/{notif_id}/leer")
def marcar_notificacion_leida(notif_id: str, usuario = Depends(obtener_usuario_actual)):
    res = (
        supabase.table("notificaciones")
        .update({"leida": True})
        .eq("id", notif_id)
        .eq("usuario_id", usuario["id"])
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="Notificación no encontrada")
    return res.data[0]

def _calcular_reportes(dias: int, anfitrion_id: str | None = None):
    supabase.rpc("liberar_reservas_expiradas").execute()

    aloj_q = supabase.table("alojamientos").select("*")
    if anfitrion_id:
        aloj_q = aloj_q.eq("anfitrion_id", anfitrion_id)
    alojamientos = aloj_q.order("creado_en", desc=True).execute().data or []
    aloj_ids = [a["id"] for a in alojamientos]

    if anfitrion_id and not aloj_ids:
        reservas, resenas = [], []
    else:
        res_q = supabase.table("reservaciones").select("*, alojamientos(titulo), perfiles(nombre_completo)")
        rev_q = supabase.table("resenas").select("alojamiento_id, calificacion")
        if anfitrion_id:
            res_q = res_q.in_("alojamiento_id", aloj_ids)
            rev_q = rev_q.in_("alojamiento_id", aloj_ids)
        reservas = res_q.order("creado_en", desc=True).execute().data or []
        resenas = rev_q.execute().data or []
    ahora = datetime.now(timezone.utc)
    fecha_corte = (ahora - timedelta(days=dias)) if dias > 0 else None

    def parse_dt(valor: str | None):
        if not valor:
            return None
        try:
            dt = datetime.fromisoformat(valor.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            return None

    reservas_periodo = []
    for r in reservas:
        dt = parse_dt(r.get("creado_en")) or parse_dt(r.get("fecha_entrada"))
        if not fecha_corte or (dt and dt >= fecha_corte):
            reservas_periodo.append(r)

    confirmadas = [r for r in reservas_periodo if r.get("estado") in ("confirmada", "completada")]
    ingresos_totales = sum(float(r.get("total_pagar") or 0) for r in confirmadas)
    ticket_promedio = round(ingresos_totales / len(confirmadas), 2) if confirmadas else 0.0

    # Noches reservadas y calificaciones por alojamiento
    noches_por_aloj = {}
    reservas_por_aloj = {}
    for r in confirmadas:
        aid = r.get("alojamiento_id")
        try:
            d1 = date.fromisoformat(str(r["fecha_entrada"])[:10])
            d2 = date.fromisoformat(str(r["fecha_salida"])[:10])
            noches = max(1, (d2 - d1).days)
        except Exception:
            noches = 1
        noches_por_aloj[aid] = noches_por_aloj.get(aid, 0) + noches
        reservas_por_aloj[aid] = reservas_por_aloj.get(aid, 0) + 1

    dias_base = dias if dias > 0 else 90
    aloj_activos = [a for a in alojamientos if a.get("activo", True)]
    capacidad_noches = max(1, len(aloj_activos) * dias_base)
    ocupacion_promedio = min(100, round((sum(noches_por_aloj.values()) / capacidad_noches) * 100))

    # Ingresos de los ultimos 7 meses (incluyendo el mes actual)
    nombres_mes = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
    meses_clave = []
    y, m = ahora.year, ahora.month
    for _ in range(7):
        meses_clave.append((y, m))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    meses_clave.reverse()

    totales_mes = {f"{yy}-{mm:02d}": 0.0 for yy, mm in meses_clave}
    for r in reservas:
        if r.get("estado") not in ("confirmada", "completada"):
            continue
        dt = parse_dt(r.get("creado_en")) or parse_dt(r.get("fecha_entrada"))
        if not dt:
            continue
        clave = f"{dt.year}-{dt.month:02d}"
        if clave in totales_mes:
            totales_mes[clave] += float(r.get("total_pagar") or 0)

    ingresos_por_mes = [
        {
            "clave": f"{yy}-{mm:02d}",
            "etiqueta": nombres_mes[mm - 1],
            "total": round(totales_mes[f"{yy}-{mm:02d}"], 2)
        }
        for yy, mm in meses_clave
    ]

    # Calificacion promedio por alojamiento
    calif_mapa = {}
    for rs in resenas:
        aid = rs.get("alojamiento_id")
        calif_mapa.setdefault(aid, []).append(float(rs.get("calificacion") or 0))

    por_alojamiento = []
    for a in alojamientos:
        aid = a["id"]
        noches = noches_por_aloj.get(aid, 0)
        ocup = min(100, round((noches / dias_base) * 100))
        lista_c = calif_mapa.get(aid, [])
        prom_c = round(sum(lista_c) / len(lista_c), 2) if lista_c else None
        por_alojamiento.append({
            "id": aid,
            "titulo": a.get("titulo", "Alojamiento"),
            "activo": bool(a.get("activo", True)),
            "reservas": reservas_por_aloj.get(aid, 0),
            "ocupacion": ocup,
            "calificacion": prom_c
        })

    # Movimientos recientes basados en reservaciones reales
    movimientos = []
    for r in reservas_periodo[:15]:
        est = r.get("estado", "")
        if est in ("confirmada", "completada"):
            concepto = "Reserva confirmada"
            tipo_mov = "Ingreso"
        elif est in ("en_revision", "pendiente_pago"):
            concepto = "Reserva en proceso SPEI"
            tipo_mov = "Pendiente"
        else:
            concepto = "Reserva cancelada / expirada"
            tipo_mov = "Cancelada"

        movimientos.append({
            "concepto": concepto,
            "alojamiento": (r.get("alojamientos") or {}).get("titulo", "Alojamiento"),
            "huesped": (r.get("perfiles") or {}).get("nombre_completo", "Huésped"),
            "tipo": tipo_mov,
            "fecha": str(r.get("creado_en") or r.get("fecha_entrada") or "")[:10],
            "monto": float(r.get("total_pagar") or 0)
        })

    return {
        "dias": dias,
        "resumen": {
            "ingresos_totales": round(ingresos_totales, 2),
            "total_reservaciones": len(reservas_periodo),
            "confirmadas": len(confirmadas),
            "ocupacion_promedio": ocupacion_promedio,
            "ticket_promedio": ticket_promedio
        },
        "ingresos_por_mes": ingresos_por_mes,
        "por_alojamiento": por_alojamiento,
        "movimientos": movimientos
    }
@app.get("/api/admin/reportes")
def obtener_reportes_admin(dias: int = 30, usuario = Depends(requerir_admin)):
    return _calcular_reportes(dias)

@app.get("/api/anfitrion/reportes")
def obtener_reportes_anfitrion(dias: int = 30, usuario = Depends(requerir_anfitrion)):
    return _calcular_reportes(dias, usuario["id"] if usuario["rol"] == "anfitrion" else None)

# --- BLOQUE 3B: ANFITRIÓN · COMPROBANTES, VALIDACIÓN Y RESEÑAS ---
def _reserva_del_anfitrion(reserva_id: str, usuario: dict):
    """Devuelve la reservación solo si pertenece a un alojamiento del anfitrión."""
    res = (
        supabase.table("reservaciones")
        .select("*, alojamientos(titulo, anfitrion_id)")
        .eq("id", reserva_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="Reservación no encontrada")
    reserva = res.data[0]
    aloj = reserva.get("alojamientos") or {}
    if usuario["rol"] == "anfitrion" and aloj.get("anfitrion_id") != usuario["id"]:
        # 404 y no 403, para no revelar que la reservación existe
        raise HTTPException(status_code=404, detail="Reservación no encontrada")
    return reserva

@app.get("/api/anfitrion/reservaciones/{reserva_id}/comprobante")
def comprobante_anfitrion(reserva_id: str, usuario = Depends(requerir_anfitrion)):
    _reserva_del_anfitrion(reserva_id, usuario)
    return obtener_url_comprobante(reserva_id, usuario)

@app.put("/api/anfitrion/reservaciones/{reserva_id}/validar")
def validar_reservacion_anfitrion(reserva_id: str, datos: ValidarReservaRequest, usuario = Depends(requerir_anfitrion)):
    if datos.accion not in ("aprobar", "rechazar"):
        raise HTTPException(status_code=400, detail="Acción inválida.")
    supabase.rpc("liberar_reservas_expiradas").execute()
    reserva = _reserva_del_anfitrion(reserva_id, usuario)
    if reserva["estado"] != "en_revision":
        raise HTTPException(status_code=400, detail=f"Solo se pueden validar reservaciones en revisión. Estado actual: {reserva['estado']}")
    return validar_reservacion(reserva_id, datos, usuario)

@app.get("/api/anfitrion/resenas")
def resenas_anfitrion(usuario = Depends(requerir_anfitrion)):
    # Solo reseñas de alojamientos del anfitrión (el admin ve todas)
    aloj_q = supabase.table("alojamientos").select("id")
    if usuario["rol"] == "anfitrion":
        aloj_q = aloj_q.eq("anfitrion_id", usuario["id"])
    aloj_ids = [a["id"] for a in aloj_q.execute().data or []]

    if not aloj_ids:
        return []

    res = (
        supabase.table("resenas")
        .select("*, alojamientos(titulo), perfiles(nombre_completo)")
        .in_("alojamiento_id", aloj_ids)
        .order("creado_en", desc=True)
        .execute()
    )
    return res.data or []


# --- BLOQUE 3C: ANFITRIÓN · DATOS DE PAGO SPEI ---
class ConfigAnfitrionRequest(BaseModel):
    banco: str
    titular_cuenta: str
    clabe_spei: str

@app.get("/api/anfitrion/configuracion")
def obtener_config_anfitrion(usuario = Depends(requerir_anfitrion)):
    res = (
        supabase.table("perfiles")
        .select("banco, titular_cuenta, clabe_spei")
        .eq("id", usuario["id"])
        .execute()
    )
    return res.data[0] if res.data else {}

@app.put("/api/anfitrion/configuracion")
def actualizar_config_anfitrion(datos: ConfigAnfitrionRequest, usuario = Depends(requerir_anfitrion)):
    clabe = datos.clabe_spei.strip().replace(" ", "")
    if not (clabe.isdigit() and len(clabe) == 18):
        raise HTTPException(status_code=400, detail="La CLABE debe tener exactamente 18 dígitos.")
    if not datos.banco.strip() or not datos.titular_cuenta.strip():
        raise HTTPException(status_code=400, detail="Banco y titular son obligatorios.")

    res = supabase.table("perfiles").update({
        "banco": datos.banco.strip(),
        "titular_cuenta": datos.titular_cuenta.strip(),
        "clabe_spei": clabe
    }).eq("id", usuario["id"]).execute()
    return res.data[0]

# --- BLOQUE 6: GESTIÓN DE ALOJAMIENTOS (EDITAR, PAUSAR, ELIMINAR) Y CONTRASEÑA ---
class ActualizarAlojamientoRequest(BaseModel):
    titulo: str
    tipo: str
    precio_noche: float
    descripcion: str
    direccion: str
    ciudad: str | None = "Capulálpam de Méndez"
    estado: str | None = "Oaxaca"
    capacidad_huespedes: int = 4
    habitaciones: int = 1
    banos: int = 1
    latitud: str | None = ""
    longitud: str | None = ""
    activo: bool = True

class CambiarEstadoAlojamientoRequest(BaseModel):
    activo: bool

class CambiarPasswordRequest(BaseModel):
    password_actual: str
    password_nueva: str

def verificar_permiso_alojamiento(alojamiento_id: str, usuario: dict):
    consulta = supabase.table("alojamientos").select("*").eq("id", alojamiento_id).execute()
    if not consulta.data:
        raise HTTPException(status_code=404, detail="Alojamiento no encontrado")
    aloj = consulta.data[0]
    if usuario["rol"] != "admin" and aloj.get("anfitrion_id") != usuario["id"]:
        raise HTTPException(status_code=403, detail="No tienes permiso para modificar este alojamiento.")
    return aloj

@app.put("/api/anfitrion/alojamientos/{alojamiento_id}")
def actualizar_alojamiento(
    alojamiento_id: str,
    datos: ActualizarAlojamientoRequest,
    usuario = Depends(requerir_anfitrion)
):
    verificar_permiso_alojamiento(alojamiento_id, usuario)
    cambios = {
        "titulo": datos.titulo.strip(),
        "tipo": datos.tipo,
        "precio_noche": datos.precio_noche,
        "descripcion": datos.descripcion.strip(),
        "direccion": datos.direccion.strip(),
        "ciudad": (datos.ciudad or "Capulálpam de Méndez").strip(),
        "estado": (datos.estado or "Oaxaca").strip(),
        "capacidad_huespedes": datos.capacidad_huespedes,
        "habitaciones": datos.habitaciones,
        "banos": datos.banos,
        "latitud": (datos.latitud or "").strip(),
        "longitud": (datos.longitud or "").strip(),
        "activo": datos.activo
    }
    res = supabase.table("alojamientos").update(cambios).eq("id", alojamiento_id).execute()
    return res.data[0]

@app.patch("/api/anfitrion/alojamientos/{alojamiento_id}/estado")
def cambiar_estado_alojamiento(
    alojamiento_id: str,
    datos: CambiarEstadoAlojamientoRequest,
    usuario = Depends(requerir_anfitrion)
):
    verificar_permiso_alojamiento(alojamiento_id, usuario)
    res = (
        supabase.table("alojamientos")
        .update({"activo": datos.activo})
        .eq("id", alojamiento_id)
        .execute()
    )
    return res.data[0]

@app.delete("/api/anfitrion/alojamientos/{alojamiento_id}")
def eliminar_alojamiento(alojamiento_id: str, usuario = Depends(requerir_anfitrion)):
    verificar_permiso_alojamiento(alojamiento_id, usuario)
    try:
        supabase.table("alojamientos").delete().eq("id", alojamiento_id).execute()
        return {"mensaje": "Alojamiento eliminado correctamente"}
    except Exception as e:
        msg = str(e).lower()
        if "foreign key" in msg or "violates" in msg or "23503" in msg:
            raise HTTPException(
                status_code=409,
                detail="No se puede eliminar porque tiene reservaciones registradas. Puedes pausarlo para ocultarlo del catálogo."
            )
        raise HTTPException(status_code=400, detail=f"No se pudo eliminar: {str(e)}")

@app.put("/api/usuarios/me/password")
def cambiar_mi_password(datos: CambiarPasswordRequest, usuario = Depends(obtener_usuario_actual)):
    if len(datos.password_nueva) < 8:
        raise HTTPException(status_code=400, detail="La nueva contraseña debe tener al menos 8 caracteres.")
    try:
        auth_client = create_client(SUPABASE_URL, SUPABASE_KEY)
        auth_client.auth.sign_in_with_password({
            "email": usuario["correo"],
            "password": datos.password_actual
        })
    except Exception:
        raise HTTPException(status_code=400, detail="La contraseña actual es incorrecta.")

    try:
        supabase.auth.admin.update_user_by_id(usuario["id"], {"password": datos.password_nueva})
        return {"mensaje": "Contraseña actualizada correctamente."}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"No se pudo actualizar la contraseña: {str(e)}")

# --- BLOQUE 7: FAVORITOS ---
@app.get("/api/favoritos")
def listar_favoritos(usuario = Depends(obtener_usuario_actual)):
    res = (
        supabase.table("favoritos")
        .select("id, alojamiento_id, creado_en, alojamientos(*)")
        .eq("usuario_id", usuario["id"])
        .order("creado_en", desc=True)
        .execute()
    )
    items = res.data or []
    ids = [item["alojamiento_id"] for item in items]
    return {"ids": ids, "favoritos": items}

@app.post("/api/favoritos/{alojamiento_id}")
def agregar_favorito(alojamiento_id: str, usuario = Depends(obtener_usuario_actual)):
    try:
        supabase.table("favoritos").upsert(
            {"usuario_id": usuario["id"], "alojamiento_id": alojamiento_id},
            on_conflict="usuario_id,alojamiento_id"
        ).execute()
        return {"es_favorito": True, "alojamiento_id": alojamiento_id}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"No se pudo guardar en favoritos: {str(e)}")

@app.delete("/api/favoritos/{alojamiento_id}")
def quitar_favorito(alojamiento_id: str, usuario = Depends(obtener_usuario_actual)):
    supabase.table("favoritos").delete().eq("usuario_id", usuario["id"]).eq("alojamiento_id", alojamiento_id).execute()
    return {"es_favorito": False, "alojamiento_id": alojamiento_id}

# Servir la carpeta frontend desde FastAPI (debe ir al final del archivo)
frontend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
if os.path.exists(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")