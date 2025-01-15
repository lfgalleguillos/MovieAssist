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
TMDB_BEARER_TOKEN = os.getenv("TMDB_BEARER_TOKEN")
TMDB_BASE_URL = "https://api.themoviedb.org/3"

# Función para buscar el ID de una película
def get_movie_id(movie_name):
    search_endpoint = f"{TMDB_BASE_URL}/search/movie"
    headers = {
        "accept": "application/json",
        "Authorization": f"Bearer {TMDB_BEARER_TOKEN}"
    }
    params = {
        "query": movie_name,
        "include_adult": False,
        "language": "en-US",
        "page": 1
    }
    response = requests.get(search_endpoint, headers=headers, params=params)

    if response.status_code == 200:
        results = response.json().get("results", [])
        if results:
            return results[0].get("id")  # Retorna el ID de la primera película encontrada
        else:
            return None
    else:
        raise Exception(f"Error al buscar el movie_id: {response.status_code}")

# Función para buscar el ID de una serie de TV
def get_tv_id(tv_name):
    search_endpoint = f"{TMDB_BASE_URL}/search/tv"
    headers = {
        "accept": "application/json",
        "Authorization": f"Bearer {TMDB_BEARER_TOKEN}"
    }
    params = {
        "query": tv_name,
        "include_adult": False,
        "language": "en-US",
        "page": 1
    }
    response = requests.get(search_endpoint, headers=headers, params=params)

    if response.status_code == 200:
        results = response.json().get("results", [])
        if results:
            return results[0].get("id")  # Retorna el ID de la primera serie encontrada
        else:
            return None
    else:
        raise Exception(f"Error al buscar el tv_id: {response.status_code}")

# Función para buscar los proveedores de streaming en Chile para una película o serie
def get_streaming_providers(name, type="movie"):
    if type == "movie":
        id = get_movie_id(name)
        providers_endpoint = f"{TMDB_BASE_URL}/movie/{id}/watch/providers"
    elif type == "tv":
        id = get_tv_id(name)
        providers_endpoint = f"{TMDB_BASE_URL}/tv/{id}/watch/providers"
    else:
        return ["Tipo desconocido. Use 'movie' o 'tv'."]

    if not id:
        return [f"No se encontró el ID para la {type} especificada."]

    headers = {
        "accept": "application/json",
        "Authorization": f"Bearer {TMDB_BEARER_TOKEN}"
    }
    response = requests.get(providers_endpoint, headers=headers)

    if response.status_code == 200:
        providers = response.json().get("results", {}).get("CL", {}).get("flatrate", [])
        if providers:
            return [provider["provider_name"] for provider in providers]
        else:
            return ["No se encontraron proveedores de streaming disponibles en Chile."]
    else:
        raise Exception(f"Error al obtener los proveedores de streaming: {response.status_code}")

# Descriptor para Function Calling
tmdb_function_descriptors = [
    {
        "name": "get_streaming_providers",
        "description": "Busca proveedores de streaming para una película o serie por su nombre.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "El nombre de la película o serie a buscar."
                },
                "type": {
                    "type": "string",
                    "enum": ["movie", "tv"],
                    "description": "Especifique si está buscando una película ('movie') o una serie ('tv')."
                }
            },
            "required": ["name", "type"]
        }
    }
]

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
        profile_context = f"Recomendar películas de los siguientes géneros o también llamado perfil del usuario: {genres_text}."
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

        # Limitar el historial de mensajes a los últimos 10 para evitar exceder tokens
        for message in user.messages[-10:]:
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
            functions=tmdb_function_descriptors,
            function_call="auto",
        )

        # Inicializa un mensaje predeterminado
        model_response = "Lo siento, no puedo procesar tu solicitud en este momento."

        if chat_completion.choices[0].finish_reason == "function_call":
            function_call = chat_completion.choices[0].message.function_call
            arguments = eval(function_call.arguments)

            if function_call.name == "get_streaming_providers":
                try:
                    providers = get_streaming_providers(arguments['name'], arguments['type'])
                    model_response = f"Proveedores de streaming en Chile para '{arguments['name']}' ({arguments['type']}): {', '.join(providers)}"
                except Exception as e:
                    model_response = f"Hubo un error al obtener los proveedores: {str(e)}"
        else:
            # Asignar respuesta generativa si no hay función
            model_response = chat_completion.choices[0].message.content or "No se generó una respuesta válida."

        # Asegúrate de que el mensaje no sea nulo antes de guardar en la base de datos
        if model_response and model_response.strip():
            db.session.add(
                Message(content=model_response, author="assistant", user=user)
            )
            db.session.commit()
        else:
            print("Error: El contenido de la respuesta está vacío. No se guardó el mensaje.")

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

    for message in user.messages[-10:]:  # Limitar a los últimos 10 mensajes
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
        db.session.commit()

        # Redirigir o mostrar un mensaje de éxito
        flash("Perfil actualizado con éxito", "success")
        return redirect(url_for("editar_perfil"))

    return render_template("editar_perfil.html", profile=profile)
