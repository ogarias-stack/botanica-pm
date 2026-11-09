import logging
import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from secrets import compare_digest
from typing import Annotated, NamedTuple

import jwt
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from openai import OpenAIError
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy.exc import SQLAlchemyError

from agente import (
    ErrorFase,
    HitoNoEncontrado,
    RespuestaDocumentalInvalida,
    abrir_proyecto,
    acusar_alerta,
    agente,
    agente_chat,
    agente_partes,
    avanzar_fase,
    completar_tarea,
    consultar_proyecto,
    descripcion_tarea_pendiente,
    sugerir_evidencia,
)
from models import FRENTE_CIMENTACION, ROLES_TECNICOS

app = FastAPI(title="Botánica · Agente PM de obra")
bearer = HTTPBearer(auto_error=False)
logger_chat = logging.getLogger(__name__)

ALGORITMO = "RS256"
VIGENCIA_TOKEN_SEGUNDOS = 900
FrenteId = Annotated[
    str, StringConstraints(min_length=1, max_length=80, pattern=r"^[a-z0-9-]+$")
]


class Actor(NamedTuple):
    id: str
    rol: str


class ParteDiario(BaseModel):
    frente_id: FrenteId
    avance_porcentaje: Annotated[
        Decimal, Field(ge=0, le=100, max_digits=5, decimal_places=2)
    ]
    fecha: date


@app.get("/health")
def health():
    return {"status": "ok"}


def verificar_actor(
    credenciales: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> Actor:
    error_token = HTTPException(
        401, "Token ausente o inválido.", {"WWW-Authenticate": "Bearer"}
    )
    if credenciales is None:
        raise error_token

    try:
        claims = jwt.decode(
            credenciales.credentials,
            Path(os.environ["JWT_PUBLIC_KEY_FILE"]).read_bytes(),
            algorithms=[ALGORITMO],
            issuer=os.environ["JWT_ISSUER"],
            audience=os.environ["JWT_AUDIENCE"],
            options={"require": ["sub", "role", "iss", "aud", "iat", "exp"]},
        )
    except jwt.InvalidTokenError:
        raise error_token from None

    actor_id, rol = claims["sub"], claims["role"]
    equipo = {
        item.strip()
        for item in os.getenv("BOTANICA_EQUIPO_IDS", "").split(",")
        if item.strip()
    }
    if actor_id == os.environ["OLI_ACTOR_ID"] and rol == "oli":
        return Actor(actor_id, rol)
    if actor_id in equipo and isinstance(rol, str) and rol in ROLES_TECNICOS:
        return Actor(actor_id, rol)
    raise HTTPException(403, "Sin acceso a Botánica.")


if os.getenv("APP_ENV") == "development":

    @app.post("/auth/token")
    def emitir_token_desarrollo(
        response: Response,
        secreto: Annotated[str | None, Header(alias="X-Dev-Token-Secret")] = None,
    ):
        configurado = os.getenv("DEV_TOKEN_SECRET", "")
        if len(configurado) < 32:
            raise HTTPException(503, "Emisión de desarrollo sin configurar.")
        if not secreto or not compare_digest(secreto.encode(), configurado.encode()):
            raise HTTPException(403, "Acceso de desarrollo denegado.")

        ahora = datetime.now(timezone.utc)
        token = jwt.encode(
            {
                "sub": os.environ["OLI_ACTOR_ID"],
                "role": "oli",
                "iss": os.environ["JWT_ISSUER"],
                "aud": os.environ["JWT_AUDIENCE"],
                "iat": ahora,
                "exp": ahora + timedelta(seconds=VIGENCIA_TOKEN_SEGUNDOS),
            },
            Path(os.environ["JWT_PRIVATE_KEY_FILE"]).read_bytes(),
            algorithm=ALGORITMO,
        )
        response.headers["Cache-Control"] = "no-store"
        return {
            "access_token": token,
            "token_type": "bearer",
            "expires_in": VIGENCIA_TOKEN_SEGUNDOS,
        }


@app.get("/botanica/estado")
def consultar_estado(
    actor: Annotated[Actor, Depends(verificar_actor)],
    response: Response,
    frente_id: Annotated[FrenteId, Query()] = FRENTE_CIMENTACION,
):
    try:
        resultado = agente.invoke({
            "actor_id_verificado": actor.id,
            "frente_id": frente_id,
        })
    except HitoNoEncontrado:
        raise HTTPException(404, "Hito no encontrado.") from None

    response.headers["Cache-Control"] = "no-store"
    return {"respuesta": resultado["respuesta"]}


@app.post("/botanica/parte")
def registrar_parte(
    parte: ParteDiario,
    actor: Annotated[Actor, Depends(verificar_actor)],
):
    try:
        resultado = agente_partes.invoke({
            **parte.model_dump(),
            "actor_id_verificado": actor.id,
        })
    except HitoNoEncontrado:
        raise HTTPException(404, "Hito no encontrado.") from None

    salida = {"parte_id": resultado["parte_id"]}
    if resultado["resultado_alerta"] is not None:
        salida["alerta"] = resultado["resultado_alerta"]
    return salida


@app.post("/botanica/alertas/{alerta_id}/acuse", status_code=204)
def registrar_acuse(
    alerta_id: int,
    actor: Annotated[Actor, Depends(verificar_actor)],
):
    if actor.rol not in ROLES_TECNICOS:
        raise HTTPException(403, "El acuse corresponde al equipo técnico.")
    if not acusar_alerta(alerta_id, actor.id):
        raise HTTPException(404, "Alerta sin acuse disponible.")
    return Response(status_code=204)


class PreguntaDocumental(BaseModel):
    pregunta: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
    ]


@app.post("/botanica/chat")
def consultar_chat(
    consulta: PreguntaDocumental,
    actor: Annotated[Actor, Depends(verificar_actor)],
    response: Response,
) -> dict[str, str]:
    try:
        resultado = agente_chat.invoke({"pregunta": consulta.pregunta})
    except (
        OpenAIError, SQLAlchemyError, RespuestaDocumentalInvalida, KeyError, ValueError
    ) as error:
        logger_chat.warning("Consulta documental fallida: %s", str(error) if isinstance(error, RespuestaDocumentalInvalida) else type(error).__name__)
        raise HTTPException(503, "No se pudo completar la consulta documental.") from None

    response.headers["Cache-Control"] = "no-store"
    return {"respuesta": resultado["respuesta"]}


class AperturaProyecto(BaseModel):
    nombre: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)
    ]
    presupuesto: Annotated[Decimal, Field(gt=0, max_digits=16, decimal_places=2)]


class EvidenciaTarea(BaseModel):
    referencia_evidencia: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
    ]


def verificar_director(actor: Annotated[Actor, Depends(verificar_actor)]) -> Actor:
    if actor.rol != "oli":
        raise HTTPException(403, "La aprobación de fases corresponde a dirección.")
    return actor


Director = Annotated[Actor, Depends(verificar_director)]


@app.exception_handler(ErrorFase)
async def gestionar_error_fase(request: Request, error: ErrorFase) -> JSONResponse:
    return JSONResponse(
        status_code=error.codigo,
        content={"respuesta": error.respuesta, "pendientes": error.pendientes},
    )


@app.post("/proyectos")
def crear_proyecto_http(datos: AperturaProyecto, director: Director) -> dict:
    return abrir_proyecto(datos.nombre, datos.presupuesto)


@app.get("/proyectos/{proyecto_id}")
def obtener_proyecto_http(proyecto_id: str, director: Director) -> dict:
    return consultar_proyecto(proyecto_id)


@app.post("/proyectos/{proyecto_id}/avanzar")
def avanzar_proyecto_http(
    proyecto_id: str,
    revision: Annotated[int, Header(alias="X-Revision-Proyecto", ge=1)],
    director: Director,
) -> dict:
    return avanzar_fase(proyecto_id, revision)


@app.put("/proyectos/{proyecto_id}/tareas/{tarea_id}")
def completar_tarea_http(
    proyecto_id: str,
    tarea_id: int,
    datos: EvidenciaTarea,
    director: Director,
) -> dict:
    return completar_tarea(
        proyecto_id, tarea_id, datos.referencia_evidencia, director.id
    )


@app.get("/proyectos/{proyecto_id}/tareas/{tarea_id}/evidencia")
def buscar_evidencia_http(
    proyecto_id: str,
    tarea_id: int,
    director: Director,
    response: Response,
) -> dict[str, bool | str]:
    try:
        descripcion = descripcion_tarea_pendiente(proyecto_id, tarea_id)
        resultado = sugerir_evidencia(descripcion, proyecto_id)
    except (
        OpenAIError, SQLAlchemyError, RespuestaDocumentalInvalida, KeyError, ValueError
    ) as error:
        logger_chat.warning("Búsqueda de evidencia fallida: %s", type(error).__name__)
        raise HTTPException(503, "No se pudo verificar la evidencia documental.") from None

    response.headers["Cache-Control"] = "no-store"
    return resultado