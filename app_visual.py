from datetime import date
from urllib.parse import quote

import httpx
import streamlit as st
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from main import verificar_actor
from models import FRENTE_CIMENTACION, PROYECTO_BOTANICA, obtener_motor

API = "http://127.0.0.1:8000"
MENSAJES_ACCESO = {
    401: "El token no es válido o ha caducado. Pega uno nuevo.",
    403: "Tu usuario no tiene acceso a esta operación.",
}


def texto_breve(valor, respaldo):
    if isinstance(valor, str):
        valor = valor.strip()
        if valor and len(valor.split()) <= 50 and len(valor.splitlines()) <= 3:
            return valor
    return respaldo


def limpiar_sesion():
    for clave in (
        "estado_hito",
        "proyectos_conocidos",
        "proyecto_elegido",
        "aviso_proyectos",
        "evidencias_tareas",
        "respuesta_chat",
        "id_proyecto_manual",
    ):
        st.session_state.pop(clave, None)


def consultar_api(token, metodo, ruta, *, cabeceras=None, **opciones):
    try:
        respuesta = httpx.request(
            metodo,
            f"{API}{ruta}",
            headers={"Authorization": f"Bearer {token}", **(cabeceras or {})},
            timeout=60.0,
            **opciones,
        )
        respuesta.raise_for_status()
        datos = respuesta.json()
        if not isinstance(datos, dict):
            raise ValueError("Se esperaba un objeto JSON.")
        return datos
    except httpx.HTTPStatusError as error:
        codigo = error.response.status_code
        if codigo in MENSAJES_ACCESO:
            st.error(MENSAJES_ACCESO[codigo])
        else:
            try:
                datos_error = error.response.json()
            except ValueError:
                datos_error = {}
            mensaje = (
                datos_error.get("respuesta") or datos_error.get("detail")
                if isinstance(datos_error, dict)
                else None
            )
            respaldo = (
                "Revisa los datos del formulario."
                if codigo == 422
                else f"La API rechazó la operación ({codigo})."
            )
            st.error(texto_breve(mensaje, respaldo))
    except (httpx.RequestError, ValueError):
        st.error("La API de Botánica no está disponible o devolvió una respuesta inválida.")
    return None


def consultar_bd(sentencia):
    # Se usa después de validar el JWT.
    try:
        with obtener_motor().connect() as db:
            return db.execute(
                text(sentencia), {"proyecto": PROYECTO_BOTANICA}
            ).mappings().all()
    except (SQLAlchemyError, KeyError):
        st.error("No se pudo leer PostgreSQL. Revisa la conexión y la migración de Semana 3.")
        return None


def guardar_proyecto(datos, *, seleccionar=False):
    proyectos = st.session_state.setdefault("proyectos_conocidos", {})
    proyecto_id = datos["proyecto_id"]
    proyectos[proyecto_id] = datos
    if seleccionar:
        st.session_state["proyecto_elegido"] = proyecto_id


def renderizar_proyectos(token, actor):
    if actor.rol != "oli":
        st.info("La apertura, el checklist y el avance de fases corresponden a dirección.")
        return

    proyectos = st.session_state.setdefault("proyectos_conocidos", {})
    aviso = st.session_state.pop("aviso_proyectos", None)
    if aviso:
        st.success(aviso)

    with st.form("abrir_proyecto"):
        nombre = st.text_input("Nombre del proyecto", max_chars=160)
        presupuesto = st.number_input(
            "Presupuesto objetivo", min_value=0.0, step=1000.0, format="%.2f"
        )
        abrir = st.form_submit_button("Abrir proyecto")

    if abrir:
        if not nombre.strip() or presupuesto <= 0:
            st.error("Introduce un nombre y un presupuesto mayor que cero.")
        else:
            datos = consultar_api(
                token,
                "POST",
                "/proyectos",
                json={"nombre": nombre.strip(), "presupuesto": f"{presupuesto:.2f}"},
            )
            if datos is not None:
                guardar_proyecto(datos, seleccionar=True)
                st.success(texto_breve(datos.get("respuesta"), "Proyecto cargado."))

    with st.form("cargar_proyecto"):
        manual = st.text_input("ID de un proyecto existente", key="id_proyecto_manual")
        cargar = st.form_submit_button("Cargar por ID")

    if cargar:
        if not manual.strip():
            st.error("Introduce el ID del proyecto.")
        else:
            datos = consultar_api(
                token, "GET", f"/proyectos/{quote(manual.strip(), safe='')}"
            )
            if datos is not None:
                guardar_proyecto(datos, seleccionar=True)

    proyecto_id = st.selectbox(
        "Selecciona un proyecto",
        options=list(proyectos),
        index=None,
        format_func=lambda identificador: proyectos[identificador]["nombre"],
        key="proyecto_elegido",
    )
    if not proyecto_id:
        return

    proyecto = proyectos[proyecto_id]
    ruta = f"/proyectos/{quote(proyecto_id, safe='')}"
    st.caption(f"ID: {proyecto_id}")

    if st.button("Actualizar proyecto"):
        datos = consultar_api(token, "GET", ruta)
        if datos is not None:
            guardar_proyecto(datos)
            proyecto = datos

    st.subheader(f"Fase actual: {proyecto['fase_actual']}")
    if proyecto["cerrado"]:
        st.success("Proyecto cerrado.")

    for tarea in proyecto["tareas"]:
        tarea_id = tarea["id"]
        st.checkbox(
            tarea["descripcion"],
            value=tarea["completada"],
            disabled=True,
            key=f"check-{tarea_id}-{tarea['completada']}",
        )
        if tarea["completada"] or proyecto["cerrado"]:
            continue

        evidencias = st.session_state.setdefault("evidencias_tareas", {})
        clave = (proyecto_id, tarea_id)

        if st.button("🔍 Buscar evidencia", key=f"evidencia-{proyecto_id}-{tarea_id}"):
            evidencias.pop(clave, None)
            with st.spinner("Buscando evidencia en los documentos del proyecto…"):
                resultado = consultar_api(
                    token, "GET", f"{ruta}/tareas/{tarea_id}/evidencia"
                )
            if resultado is not None:
                evidencias[clave] = resultado

        sugerencia = evidencias.get(clave)
        if sugerencia is not None:
            if sugerencia["encontrado"]:
                st.info(
                    f"Evidencia encontrada en {sugerencia['archivo']} "
                    f"({sugerencia['ubicacion']}): «{sugerencia['cita']}»"
                )
                st.caption(sugerencia["mensaje"])
            else:
                st.warning(
                    "No se ha encontrado evidencia documental para esta tarea. "
                    "Revisa los documentos o súbelos."
                )

        with st.form(f"completar-{tarea_id}"):
            evidencia = st.text_input(
                "Referencia de evidencia",
                max_chars=500,
                placeholder="Acta, plano o documento y sección",
            )
            completar = st.form_submit_button("Completar tarea")

        if completar:
            if not evidencia.strip():
                st.error("Introduce la referencia de evidencia.")
            else:
                datos = consultar_api(
                    token,
                    "PUT",
                    f"{ruta}/tareas/{tarea_id}",
                    json={"referencia_evidencia": evidencia.strip()},
                )
                if datos is not None:
                    guardar_proyecto(datos)
                    st.session_state["aviso_proyectos"] = texto_breve(
                        datos.get("respuesta"), "Tarea registrada."
                    )
                    st.rerun()

    if proyecto["cerrado"]:
        return

    etiqueta = (
        "Cerrar proyecto"
        if proyecto["fase_actual"] == "Entrega y Cierre"
        else "Avanzar a la siguiente fase"
    )
    if st.button(etiqueta, type="primary", width="stretch"):
        datos = consultar_api(
            token,
            "POST",
            f"{ruta}/avanzar",
            cabeceras={"X-Revision-Proyecto": str(proyecto["revision"])},
        )
        if datos is not None:
            guardar_proyecto(datos)
            st.session_state["aviso_proyectos"] = texto_breve(
                datos.get("respuesta"), "Proyecto actualizado."
            )
            st.rerun()


st.set_page_config(page_title="Botánica · PM de obra", page_icon="🏗️")
st.title("Botánica · PM de obra")

with st.sidebar:
    st.header("Acceso")
    token = st.text_input(
        "Token de acceso",
        type="password",
        key="token",
        on_change=limpiar_sesion,
    ).strip()

if not token:
    st.info("Por favor, introduce tu token de acceso")
    st.stop()

try:
    actor = verificar_actor(
        HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    )
except HTTPException as error:
    limpiar_sesion()
    st.warning(MENSAJES_ACCESO.get(error.status_code, "No se pudo validar el acceso."))
    st.stop()
except (OSError, KeyError):
    st.error("Falta la configuración JWT del proyecto en el servidor.")
    st.stop()

panel, partes, proyectos, documentos = st.tabs([
    "🚦 Panel de control",
    "📝 Parte diario",
    "🏗️ Gestión de proyectos",
    "🧠 Consultar documentos",
])

with panel:
    st.subheader("Cimentación de la huella")
    if st.button("Consultar estado", type="primary"):
        st.session_state.pop("estado_hito", None)
        datos = consultar_api(
            token, "GET", "/botanica/estado", params={"frente_id": FRENTE_CIMENTACION}
        )
        if datos is not None:
            estado = datos.get("respuesta")
            if isinstance(estado, str) and estado.strip():
                st.session_state["estado_hito"] = texto_breve(
                    estado, "La respuesta supera el límite de visualización."
                )
            else:
                st.error("La API no devolvió el estado del hito.")

    if "estado_hito" in st.session_state:
        st.text_area(
            "Respuesta del PM", st.session_state["estado_hito"], height=140, disabled=True
        )

    if st.button("Ver alertas recientes"):
        alertas = consultar_bd("""
            SELECT id, estado, mensaje
            FROM alertas_pendientes
            WHERE proyecto_id = :proyecto
            ORDER BY id DESC
            LIMIT 5
        """)
        if alertas == []:
            st.info("No hay alertas registradas.")
        elif alertas:
            for alerta in alertas:
                st.caption(f"Alerta {alerta['id']} · {alerta['estado']}")
                st.text(texto_breve(alerta["mensaje"], "Mensaje de alerta no disponible."))

with partes:
    with st.form("parte_diario"):
        st.caption("Frente: Cimentación de la huella")
        fecha = st.date_input("Fecha del parte", value=date.today())
        avance = st.number_input(
            "Avance reportado (%)",
            min_value=0.0,
            max_value=100.0,
            step=0.01,
            format="%.2f",
        )
        enviar = st.form_submit_button("Enviar parte", type="primary")

    if enviar:
        datos = consultar_api(
            token,
            "POST",
            "/botanica/parte",
            json={
                "frente_id": FRENTE_CIMENTACION,
                "fecha": fecha.isoformat(),
                "avance_porcentaje": round(avance, 2),
            },
        )
        if datos is not None:
            alerta = datos.get("alerta")
            if alerta == "RECHAZADA":
                st.warning("Parte registrado. No se pudo encolar la alerta.")
            elif alerta:
                st.success(f"Parte registrado. Alerta {alerta}.")
            else:
                st.success("Parte registrado.")

with proyectos:
    renderizar_proyectos(token, actor)

with documentos:
    st.caption("Consulta de los documentos indexados de Botánica.")
    with st.form("consulta_documental"):
        pregunta = st.text_area("Pregunta sobre los documentos", max_chars=2000)
        consultar = st.form_submit_button("Consultar", type="primary")

    if consultar:
        st.session_state.pop("respuesta_chat", None)
        if not pregunta.strip():
            st.error("Escribe una pregunta.")
        else:
            datos = consultar_api(
                token, "POST", "/botanica/chat", json={"pregunta": pregunta.strip()}
            )
            if datos is not None:
                st.session_state["respuesta_chat"] = texto_breve(
                    datos.get("respuesta"), "La respuesta documental no está disponible."
                )

    if "respuesta_chat" in st.session_state:
        with st.chat_message("assistant"):
            st.text(st.session_state["respuesta_chat"])