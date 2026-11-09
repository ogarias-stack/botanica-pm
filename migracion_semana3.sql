-- Después de init_db.py de la Semana 2.
-- psql -v ON_ERROR_STOP=1 -f migracion_semana3.sql
BEGIN;

CREATE TABLE IF NOT EXISTS configuracion_alerta (
    proyecto_id varchar(80) PRIMARY KEY,
    umbral_retraso_porcentaje numeric(5,2) NOT NULL
        CHECK (umbral_retraso_porcentaje BETWEEN 0 AND 100),
    umbral_sobrecoste_porcentaje numeric(8,2) NOT NULL
        CHECK (umbral_sobrecoste_porcentaje >= 0),
    umbral_bloqueo_dias integer NOT NULL CHECK (umbral_bloqueo_dias >= 0),
    destinatarios_whatsapp text[] NOT NULL DEFAULT '{}',
    destinatarios_email text[] NOT NULL DEFAULT '{}',
    CHECK (cardinality(destinatarios_whatsapp) + cardinality(destinatarios_email) > 0)
);

CREATE TABLE IF NOT EXISTS linea_base_avance (
    proyecto_id varchar(80) NOT NULL,
    hito_id varchar(80) NOT NULL,
    fecha date NOT NULL,
    avance_planificado numeric(5,2) NOT NULL CHECK (avance_planificado BETWEEN 0 AND 100),
    PRIMARY KEY (proyecto_id, hito_id, fecha),
    FOREIGN KEY (proyecto_id, hito_id) REFERENCES hitos (proyecto_id, id)
);

CREATE TABLE IF NOT EXISTS partes_diarios (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    proyecto_id varchar(80) NOT NULL,
    hito_id varchar(80) NOT NULL,
    fecha date NOT NULL,
    actor_id text NOT NULL,
    avance_reportado numeric(5,2) NOT NULL CHECK (avance_reportado BETWEEN 0 AND 100),
    avance_verificado numeric(5,2) CHECK (avance_verificado BETWEEN 0 AND 100),
    UNIQUE (proyecto_id, hito_id, fecha, avance_reportado, actor_id),
    FOREIGN KEY (proyecto_id, hito_id) REFERENCES hitos (proyecto_id, id)
);

-- Importar solo desde fuentes de coste y bloqueo autorizadas.
CREATE TABLE IF NOT EXISTS mediciones_alerta (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    proyecto_id varchar(80) NOT NULL,
    hito_id varchar(80) NOT NULL,
    fecha date NOT NULL,
    tipo text NOT NULL CHECK (tipo IN ('sobrecoste', 'bloqueo')),
    valor numeric(12,2) NOT NULL CHECK (valor >= 0),
    fuente_id text NOT NULL CHECK (length(fuente_id) > 0),
    FOREIGN KEY (proyecto_id, hito_id) REFERENCES hitos (proyecto_id, id)
);

CREATE TABLE IF NOT EXISTS alertas_pendientes (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    proyecto_id varchar(80) NOT NULL REFERENCES configuracion_alerta (proyecto_id),
    hito_id varchar(80) NOT NULL,
    tipo_alerta text NOT NULL CHECK (tipo_alerta IN ('retraso', 'sobrecoste', 'bloqueo')),
    evidencia_ids text[] NOT NULL,
    clave_idempotencia text NOT NULL,
    mensaje text NOT NULL,
    estado text NOT NULL DEFAULT 'equipo_pendiente'
        CHECK (estado IN ('equipo_pendiente', 'esperando_acuse', 'acusada', 'escalada', 'fallida')),
    intentos integer NOT NULL DEFAULT 0,
    proximo_intento timestamptz NOT NULL DEFAULT now(),
    equipo_notificado_en timestamptz,
    acuse_por text,
    acuse_en timestamptz,
    ultimo_error text,
    UNIQUE (proyecto_id, clave_idempotencia),
    FOREIGN KEY (proyecto_id, hito_id) REFERENCES hitos (proyecto_id, id)
);

CREATE INDEX IF NOT EXISTS alertas_por_procesar
    ON alertas_pendientes (proximo_intento, id)
    WHERE estado IN ('equipo_pendiente', 'esperando_acuse');

COMMIT;

-- Carga la configuración aprobada del equipo y la línea base por hito y fecha.
-- El parte HTTP solo escribe avance_reportado. El avance_verificado requiere
-- un registro de verificación independiente.
