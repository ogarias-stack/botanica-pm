import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import httpx
import jwt
from openai.resources.responses.responses import Responses

from main import app

URL_ESTADO = "/botanica/estado?frente_id=cimentacion-huella"


def generar_token(rol: str) -> str:
    ahora = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": os.environ["OLI_ACTOR_ID"],
            "role": rol,
            "iss": os.environ["JWT_ISSUER"],
            "aud": os.environ["JWT_AUDIENCE"],
            "iat": ahora,
            "exp": ahora + timedelta(minutes=5),
        },
        Path(os.environ["JWT_PRIVATE_KEY_FILE"]).read_bytes(),
        algorithm="RS256",
    )


def consultar_estado(token: str) -> httpx.Response:
    async def consultar() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as cliente:
            return await cliente.get(
                URL_ESTADO,
                headers={"Authorization": f"Bearer {token}"},
            )

    return asyncio.run(consultar())


def test_estado_con_oli_y_openai_real() -> None:
    assert os.getenv("OPENAI_API_KEY"), "Configura OPENAI_API_KEY en .env."
    assert os.getenv("OPENAI_MODEL"), "Configura OPENAI_MODEL en .env."
    assert os.getenv("DATABASE_URL"), "Configura DATABASE_URL en .env."

    evidencias = []
    crear_respuesta_real = Responses.create

    def observar_responses(recurso, *args, **kwargs):
        resultado = crear_respuesta_real(recurso, *args, **kwargs)
        assert resultado.status == "completed", "OpenAI no completó la respuesta."
        assert resultado.output_text.strip(), "OpenAI devolvió texto vacío."
        evidencias.append(json.loads(kwargs["input"]))
        return resultado

    # Observa la llamada real. Un fallback por fallo de API no pasa la prueba.
    with patch.object(Responses, "create", observar_responses):
        respuesta = consultar_estado(generar_token("oli"))

    assert respuesta.status_code == 200
    datos = respuesta.json()
    assert "respuesta" in datos
    assert len(evidencias) == 1, "No se confirmó una respuesta real de OpenAI."
    assert evidencias[0]["id"] == "cimentacion-huella"

    texto = datos["respuesta"]
    assert isinstance(texto, str) and texto.strip()
    assert len(texto.split()) < 50, "La respuesta debe tener menos de 50 palabras."
    assert len(texto.strip().splitlines()) < 3, "La respuesta debe tener menos de 3 líneas."
    estado = evidencias[0]["estado"].casefold()
    assert "cimentación" in texto.casefold() or estado in texto.casefold()


def test_token_con_firma_invalida_devuelve_401() -> None:
    cabecera, datos, firma = generar_token("oli").split(".")
    primer_caracter = "B" if firma[0] == "A" else "A"
    token_alterado = ".".join((cabecera, datos, primer_caracter + firma[1:]))
    assert consultar_estado(token_alterado).status_code == 401


def test_token_valido_con_otro_rol_devuelve_403() -> None:
    assert consultar_estado(generar_token("contratista")).status_code == 403
