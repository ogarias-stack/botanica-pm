# ingest_docs.py
import argparse
import os
from pathlib import Path

import pandas as pd
from openai import OpenAI
from pypdf import PdfReader
from sqlalchemy import text

from agente import generar_embeddings
from models import PROYECTO_BOTANICA, obtener_motor

EXTENSIONES = {".pdf", ".xlsx", ".xlsm", ".xls"}
MAX_FRAGMENTO = 1000
SOLAPE = 150
LOTE = 50


def trocear(texto: str, ubicacion: str):
    prefijo = f"{ubicacion}\n"
    capacidad = MAX_FRAGMENTO - len(prefijo)
    texto = texto.strip()
    for inicio in range(0, len(texto), capacidad - SOLAPE):
        fin = inicio + capacidad
        yield prefijo + texto[inicio:fin]
        if fin >= len(texto):
            break


def extraer_fragmentos(archivo: Path) -> list[str]:
    fragmentos = []
    if archivo.suffix.lower() == ".pdf":
        for numero, pagina in enumerate(PdfReader(archivo).pages, start=1):
            fragmentos.extend(trocear(pagina.extract_text() or "", f"Página {numero}"))
    else:
        hojas = pd.read_excel(
            archivo, sheet_name=None, header=None, dtype=str, keep_default_na=False,
        )
        for hoja, tabla in hojas.items():
            filas = [
                f"Fila {numero}: " + " | ".join(str(valor).strip() for valor in valores)
                for numero, valores in enumerate(
                    tabla.itertuples(index=False, name=None), start=1
                )
                if any(str(valor).strip() for valor in valores)
            ]
            fragmentos.extend(trocear("\n".join(filas), f"Hoja {hoja}"))

    if not fragmentos:
        raise ValueError(
            f"{archivo.name}: sin texto extraíble. Los PDFs escaneados necesitan OCR."
        )
    return fragmentos


def indexar_archivo(cliente: OpenAI, archivo: Path) -> int:
    fragmentos = extraer_fragmentos(archivo)
    parametros = {"proyecto": PROYECTO_BOTANICA, "archivo": archivo.name}

    # Un fallo de ingesta conserva la versión anterior del archivo.
    with obtener_motor().begin() as db:
        db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:clave, 0))"),
            {"clave": f"{PROYECTO_BOTANICA}/{archivo.name}"},
        )
        anteriores = db.execute(text("""
            SELECT contenido FROM documentos_rag
            WHERE proyecto_id = :proyecto AND nombre_archivo = :archivo
            ORDER BY id
        """), parametros).scalars().all()
        if anteriores == fragmentos:
            return 0

        db.execute(text("""
            DELETE FROM documentos_rag
            WHERE proyecto_id = :proyecto AND nombre_archivo = :archivo
        """), parametros)
        insertar = text("""
            INSERT INTO documentos_rag (proyecto_id, nombre_archivo, contenido, embedding)
            VALUES (:proyecto, :archivo, :contenido, CAST(:embedding AS vector))
        """)
        for inicio in range(0, len(fragmentos), LOTE):
            lote = fragmentos[inicio:inicio + LOTE]
            vectores = generar_embeddings(cliente, lote)
            db.execute(insertar, [
                parametros | {"contenido": contenido, "embedding": vector}
                for contenido, vector in zip(lote, vectores, strict=True)
            ])

    return len(fragmentos)


def main() -> None:
    parser = argparse.ArgumentParser(description="Indexa documentos de Botánica.")
    parser.add_argument("--carpeta", type=Path, default=Path(__file__).with_name("docs"))
    carpeta = parser.parse_args().carpeta
    if not carpeta.is_dir():
        parser.error(f"No existe la carpeta {carpeta}")

    archivos = sorted(
        archivo for archivo in carpeta.iterdir()
        if archivo.is_file()
        and not archivo.is_symlink()
        and archivo.suffix.lower() in EXTENSIONES
    )
    if not archivos:
        parser.exit(message="No hay PDFs ni Excels en la carpeta.\n")

    # Indexa únicamente documentos autorizados para enviar a la API de OpenAI.
    with OpenAI(api_key=os.environ["OPENAI_API_KEY"], timeout=30.0) as cliente:
        for archivo in archivos:
            cantidad = indexar_archivo(cliente, archivo)
            if cantidad:
                print(f"{archivo.name}: {cantidad} fragmentos indexados.")
            else:
                print(f"{archivo.name}: sin cambios.")


if __name__ == "__main__":
    main()