"""
AutomationLog — Registro de ejecuciones de automatización.

¿POR QUÉ existe este modelo?
  Cada vez que el usuario guarda un workspace, el motor de automatización
  escanea el contenido buscando ítems TODO.
  Para NO crear la misma tarea dos veces (si el usuario guarda sin cambiar
  el TODO), guardamos un hash SHA-256 de cada TODO procesado.
  Si el hash ya existe → skip.

Columnas:
  workspaceId : El workspace que disparó la automatización
  userId      : El dueño del workspace
  todoHash    : SHA-256 del texto exacto del TODO
                → sirve como "sello anti-duplicado"
  taskTitle   : Título de la tarea creada (útil para logs/debug)
  taskId      : ID de la tarea creada en la tabla Task
  createdAt   : Timestamp de ejecución
"""
from sqlalchemy import Column, String, DateTime, Integer
from sqlalchemy.sql import func
from app.database import Base


class AutomationLog(Base):
    __tablename__ = "AutomationLog"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    workspaceId = Column(String, nullable=False, index=True)
    userId      = Column(String, nullable=False, index=True)
    todoHash    = Column(String, nullable=False, index=True)
    taskTitle   = Column(String, nullable=True)
    taskId      = Column(String, nullable=True)
    createdAt   = Column(DateTime, default=func.now(), nullable=False)
