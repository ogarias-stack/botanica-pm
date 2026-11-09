from sqlalchemy.dialects.postgresql import insert

from models import Base, FRENTE_CIMENTACION, Hito, PROYECTO_BOTANICA, obtener_motor


def inicializar_bd() -> None:
    with obtener_motor().begin() as conexion:
        Base.metadata.create_all(conexion)
        sentencia = (
            insert(Hito)
            .values(
                proyecto_id=PROYECTO_BOTANICA,
                id=FRENTE_CIMENTACION,
                nombre="Cimentación de la huella",
                estado="En ejecución",
            )
            .on_conflict_do_nothing(index_elements=[Hito.proyecto_id, Hito.id])
        )
        conexion.execute(sentencia)


if __name__ == "__main__":
    inicializar_bd()
