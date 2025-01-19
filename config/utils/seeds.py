from app import app
from config.db.db import db
from config.models.models import User, Message, Profile
from werkzeug.security import generate_password_hash

with app.app_context():
    db.create_all()  # Crea las tablas en Turso si no existen

    user = User(
        email="carl.sanchez@guc.cl",
        hashed_password=generate_password_hash("password_seguro"),  # Hashed password
        is_active=True,
        is_admin=True,
        rol="Admin",
    )
    db.session.add(user)
    db.session.commit()

    profile = Profile(
        user_id=user.id,
        favorite_movie_genres=["terror", "ciencia ficción", "comedia"],
    )
    db.session.add(profile)

    message = Message(
        content="Hola! Soy iA MovieAssist, IA que te ayuda a encontrar y recomendar las mejores películas. ¿En qué te puedo ayudar?",
        author="assistant",
        user_id=user.id,
    )
    db.session.add(message)
    db.session.commit()

    print("Datos de prueba creados correctamente.")

