"""MaterialFolder — M2M связь материал ↔ папка."""
from __future__ import annotations

from sqlalchemy import BigInteger, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base


class MaterialFolder(Base):
    """Many-to-many между Material и Folder.

    Один материал может принадлежать нескольким папкам разных уровней.
    """

    __tablename__ = "material_folders"

    material_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("materials.id", ondelete="CASCADE"), primary_key=True
    )
    folder_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("folders.id", ondelete="CASCADE"), primary_key=True
    )

    # Связи
    material = relationship = None  # type: ignore[assignment]  # устанавливается ниже
    folder = relationship = None  # type: ignore[assignment]


from sqlalchemy.orm import relationship  # noqa: E402

MaterialFolder.material = relationship("Material", back_populates="folder_links")  # type: ignore[attr-defined]
MaterialFolder.folder = relationship("Folder", back_populates="material_links")  # type: ignore[attr-defined]
