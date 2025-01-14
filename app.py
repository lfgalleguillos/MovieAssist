from flask import Flask, render_template, request, redirect, url_for, flash, session
import os
import pandas as pd
from flask_bootstrap import Bootstrap5
from openai import OpenAI
from dotenv import load_dotenv
from config.db.db import db_config, db
from config.models.models import User, Message, Profile
import requests

load_dotenv()

client = OpenAI()
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "default_key")
bootstrap = Bootstrap5(app)
db_config(app)

# Configuración de la API de TMDB
TMDB_API_KEY = os.getenv("TMDB_API_KEY")
TMDB_BASE_URL = "https://api.themoviedb.org/3"

# Función para buscar detalles de películas en TMDB
def fetch_movie_details(movie_name):
    endpoint = f"{TMDB_BASE_URL}/search/movie"
    params = {
        "api_key": TMDB_API_KEY,
        "query": movie_name
    }
    response = requests.get(endpoint, params=params)
    if response.status_code == 200:
        results = response.json().get("results", [])
        if results:
            return results[0]  # Retorna el primer resultado
        else:
            return {"error": "No se encontraron resultados para la película especificada."}
    else:
        return {"error": f"Error al conectarse a TMDB: {response.status_code}"}

# Descriptor para Function Calling
tmdb_function_descriptor = {
    "name": "fetch_movie_details",
    "description": "Obtiene detalles de una película desde TMDB.",
    "parameters": {
        "type": "object",
        "properties": {
            "movie_name": {
                "type": "string",
                "description": "El nombre de la película a buscar."
            }
        },
        "required": ["movie_name"]
    }
}

@app.errorhandler(403)
def forbidden(e):
    return render_template("403.html"), 403

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")
        session["user_id"] = 1
        print("session")
        print(session["user_id"])

        # Cargar el perfil del usuario en la sesión
        profile = Profile.query.filter_by(user_id=session["user_id"]).first()
        session["profile"] = {"favorite_movie_genres": profile.favorite_movie_genres}
        print("session[profile]")
        print(session["profile"])
    return redirect("/chat")

@app.route("/chat", methods=["GET", "POST"])
def chat():
    # Obtener el usuario
    user = db.session.query(User).first()
    # Cargar el perfil del usuario en la sesión
    profile = Profile.query.filter_by(user_id=session["user_id"]).first()
    session["profile"] = {"favorite_movie_genres": profile.favorite_movie_genres}
    intents = {}

    # Crear intents basados en los temas de interés del usuario
    for topic in session["profile"]["favorite_movie_genres"]:
        intents[f"Quiero saber más sobre {topic}"] = f"Quiero saber más sobre {topic}"

    # Preparar el contexto para el modelo si hay géneros
    if intents:
        genres_text = ", ".join(session["profile"]["favorite_movie_genres"])
        profile_context = f"Recomendar películas de los siguientes géneros o tambien llamado perfil del usuario: {genres_text}."
    else:
        profile_context = "Recomendaciones de películas."

    # Agregar un intent para enviar un mensaje
    intents["Enviar"] = request.form.get("message")

    if request.method == "GET":
        # Pasar los intents al template para que se muestren como botones
        return render_template("chat.html", messages=user.messages, intents=intents)

    # Procesar el intent si se envió uno
    intent = request.form.get("intent")

    if intent and intent in intents:
        user_message = intents[intent]

        # Guardar nuevo mensaje en la base de datos
        db.session.add(Message(content=user_message, author="user", user=user))
        db.session.commit()
        # Preparar los mensajes para el LLM (modelo de lenguaje)
        messages_for_llm = [
            {
                "role": "system",
                "content": profile_context,
            }
        ]

        # Añadir los mensajes del chat
        for message in user.messages:
            messages_for_llm.append(
                {
                    "role": message.author,
                    "content": message.content,
                }
            )

        # Llamar al modelo para generar una recomendación
        chat_completion = client.chat.completions.create(
            messages=messages_for_llm,
            model="gpt-4-0613",
            functions=[tmdb_function_descriptor],
            function_call="auto",
        )

        if chat_completion['choices'][0]['finish_reason'] == 'function_call':
            function_call = chat_completion['choices'][0]['message']['function_call']
            arguments = eval(function_call['arguments'])

            tmdb_result = fetch_movie_details(arguments['movie_name'])

            enriched_response = client.chat.completions.create(
                model="gpt-4-0613",
                messages=[
                    {"role": "system", "content": profile_context},
                    {"role": "user", "content": user_message},
                    {"role": "assistant", "content": None, "function_call": function_call},
                    {"role": "function", "name": "fetch_movie_details", "content": str(tmdb_result)}
                ]
            )

            model_recommendation = enriched_response['choices'][0]['message']['content']

        else:
            model_recommendation = chat_completion['choices'][0]['message']['content']

        # Guardar la respuesta del modelo (asistente) en la base de datos
        db.session.add(
            Message(content=model_recommendation, author="assistant", user=user)
        )
        db.session.commit()

    # Renderizar la plantilla con los nuevos mensajes
    return render_template("chat.html", messages=user.messages, intents=intents)

@app.post("/recommend")
def recommend():
    user = db.session.query(User).first()
    data = request.get_json()
    user_message = data["message"]
    new_message = Message(content=user_message, author="user", user=user)
    db.session.add(new_message)
    db.session.commit()

    messages_for_llm = [
        {
            "role": "system",
            "content": """
            Eres un chatbot que recomienda películas, te llamas iA MovieAssist. 
            Tu rol es responder recomendaciones de manera breve y concisa, una pelicula por recomendacion. No repitas recomendaciones.
            Ademas debes considerar las preferencias del perfil del usuarios que tambien se pueden llamar generos de peliculas
            """,
        }
    ]

    for message in user.messages:
        messages_for_llm.append(
            {
                "role": message.author,
                "content": message.content,
            }
        )

    chat_completion = client.chat.completions.create(
        messages=messages_for_llm,
        model="gpt-4-0613",
    )

    message = chat_completion.choices[0].message.content

    return {
        "recommendation": message,
        "tokens": chat_completion.usage.total_tokens,
    }

@app.route("/editar-perfil", methods=["GET", "POST"])
def editar_perfil():
    # Obtener el perfil del usuario (esto depende de tu implementación)
    profile = db.session.query(Profile).first()

    if request.method == "POST":
        # Obtener los valores del formulario
        selected_genres = request.form.getlist("favorite_movie_genres")

        # Actualizar el perfil del usuario con los géneros seleccionados
        profile.favorite_movie_genres = selected_genres
        # Guardar los cambios en la base de datos
        db.session.commit()

        # Redirigir o mostrar un mensaje de éxito
        flash("Perfil actualizado con éxito", "success")
        return redirect(url_for("editar_perfil"))  # Redirigir a la página de perfil

    return render_template("editar_perfil.html", profile=profile)

        # Redirigir o mostrar un mensaje de éxito
        flash("Perfil actualizado con éxito", "success")
        return redirect(url_for("editar_perfil"))  # Redirigir a la página de perfil

    return render_template("editar_perfil.html", profile=profile)
