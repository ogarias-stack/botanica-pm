BEGIN;

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documentos_rag (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    proyecto_id varchar(80) NOT NULL,
    nombre_archivo text NOT NULL,
    contenido text NOT NULL CHECK (char_length(contenido) BETWEEN 1 AND 1000),
    embedding vector(1536) NOT NULL
);

CREATE INDEX IF NOT EXISTS documentos_rag_proyecto_archivo_idx
    ON documentos_rag (proyecto_id, nombre_archivo);

COMMIT;