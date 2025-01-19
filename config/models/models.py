from flask_login import UserMixin
from sqlalchemy.orm import relationship
from sqlalchemy.ext.mutable import MutableList
from ..db.db import db
from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    Boolean,
    DateTime,
    ForeignKey,
    JSON,
)
from datetime import datetime


class User(db.Model, UserMixin):  # Modelo para la tabla `users`
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    email = Column(String, nullable=False, unique=True)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)
    rol = Column(String, default="User")

    # Relación uno a uno con Profile
    profile = relationship("Profile", back_populates="user", uselist=False)

    # Relación uno a muchos con Message
    messages = relationship("Message", back_populates="user")


class Message(db.Model):  # Modelo para la tabla `messages`
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    content = Column(Text, nullable=False)
    author = Column(String, nullable=False)  # 'user' or 'assistant'
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    # Relación inversa con User
    user = relationship("User", back_populates="messages")


class Profile(db.Model):  # Modelo para la tabla `profiles`
    __tablename__ = "profiles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)  # Clave foránea
    favorite_movie_genres = Column(JSON, default=[])

    # Relación inversa con User
    user = relationship("User", back_populates="profile")
