from typing import Annotated

from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import MetaData

# Define a type annotation for UUID columns (used across models)
UUID_PK = Annotated[
    str, mapped_column(primary_key=True, index=True, type_string="UUID")
]


class DeclarativeBase(DeclarativeBase):
    """Base class for all SQLAlchemy models with consistent naming conventions."""

    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(table_name)s_%(column_0_N_name)s",
            "uq": "uq_%(table_name)s_%(column_0_N_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )