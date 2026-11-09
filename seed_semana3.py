"""Carga datos de prueba tras aplicar migracion_semana3.sql."""

from sqlalchemy import text

from models import FRENTE_CIMENTACION, PROYECTO_BOTANICA, obtener_motor


def main() -> None:
    parametros = {
        "proyecto_id": PROYECTO_BOTANICA,
        "hito_id": FRENTE_CIMENTACION,
    }

    with obtener_motor().begin() as db:
        hito = db.execute(
            text("""
                INSERT INTO hitos (proyecto_id, id, nombre, estado)
                VALUES (:proyecto_id, :hito_id, 'Cimentación de la huella', 'En ejecución')
                ON CONFLICT (proyecto_id, id) DO NOTHING
                RETURNING id
            """),
            parametros,
        ).scalar_one_or_none()

        configuracion = db.execute(
            text("""
                INSERT INTO configuracion_alerta (
                    proyecto_id,
                    umbral_retraso_porcentaje,
                    umbral_sobrecoste_porcentaje,
                    umbral_bloqueo_dias,
                    destinatarios_whatsapp,
                    destinatarios_email
                )
                VALUES (
                    :proyecto_id, 10, 5, 7,
                    ARRAY['+1809XXXXXXX'],
                    ARRAY['equipo@botanica.test']
                )
                ON CONFLICT (proyecto_id) DO NOTHING
                RETURNING proyecto_id
            """),
            parametros,
        ).scalar_one_or_none()

        fechas_insertadas = db.execute(
            text("""
                INSERT INTO linea_base_avance (
                    proyecto_id, hito_id, fecha, avance_planificado
                )
                VALUES
                    (:proyecto_id, :hito_id, DATE '2026-11-01', 10),
                    (:proyecto_id, :hito_id, DATE '2026-11-15', 30),
                    (:proyecto_id, :hito_id, DATE '2026-11-30', 50)
                ON CONFLICT (proyecto_id, hito_id, fecha) DO NOTHING
                RETURNING fecha, avance_planificado
            """),
            parametros,
        ).all()

    print(f"Hito {FRENTE_CIMENTACION}: {'insertado' if hito else 'ya existía'}.")
    if configuracion:
        print("Configuración insertada: retraso 10%, sobrecoste 5%, bloqueo 7 días.")
    else:
        print("Configuración existente conservada.")

    print(f"Línea base: {len(fechas_insertadas)} de 3 fechas insertadas.")
    for fecha, avance in sorted(fechas_insertadas):
        print(f"  {fecha.isoformat()} — {avance:g}%")

    print("Listo para probar.")


if __name__ == "__main__":
    main()
