import os
from datetime import date, datetime
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import DateTime, String, create_engine, func
from sqlalchemy import BigInteger, Boolean, Date, ForeignKey, Identity, Index, Integer, Numeric, Text, UniqueConstraint
from sqlalchemy import text as sql_text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

load_dotenv(Path(__file__).with_name(".env"))
PROYECTO_BOTANICA = "botanica-punta-cana"
FRENTE_CIMENTACION = "cimentacion-huella"
ROLES_TECNICOS = frozenset({"jefe_obra", "ingeniero_residente"})


class Base(DeclarativeBase):
    pass


class Hito(Base):
    __tablename__ = "hitos"

    proyecto_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    nombre: Mapped[str] = mapped_column(String(160), nullable=False)
    estado: Mapped[str] = mapped_column(String(80), nullable=False)
    fecha_actualizacion: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


@lru_cache(maxsize=1)
def obtener_motor():
    return create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)

# Esquema gestionado por migracion_fases.sql. init_db.py conserva su alcance anterior.
class BaseFases(DeclarativeBase):
    pass


class Proyecto(BaseFases):
    __tablename__ = "proyectos"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    nombre: Mapped[str] = mapped_column(String(160))
    fase_actual: Mapped[str] = mapped_column(String(40))
    presupuesto_objetivo: Mapped[Decimal] = mapped_column(Numeric(16, 2))
    fecha_inicio: Mapped[date] = mapped_column(Date, server_default=func.current_date())
    revision: Mapped[int] = mapped_column(Integer, server_default=sql_text("1"))
    cerrado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("proyectos_nombre_unico", func.lower(nombre), unique=True),)


class TareaFase(BaseFases):
    __tablename__ = "tareas_fase"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    proyecto_id: Mapped[str] = mapped_column(String(80), ForeignKey("proyectos.id"))
    fase: Mapped[str] = mapped_column(String(40))
    descripcion: Mapped[str] = mapped_column(String(160))
    completada: Mapped[bool] = mapped_column(Boolean, server_default=sql_text("false"))
    referencia_evidencia: Mapped[str | None] = mapped_column(String(500))
    completada_por: Mapped[str | None] = mapped_column(Text)
    completada_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (UniqueConstraint("proyecto_id", "fase", "descripcion"),)
