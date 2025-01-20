from flask import Flask, render_template, request, redirect, url_for, flash, session
import os
import pandas as pd
from flask_bootstrap import Bootstrap5
from openai import OpenAI
from dotenv import load_dotenv
from config.db.db import db_config, db
from config.models.models import User, Message, Profile
import requests
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash

load_dotenv()

client = OpenAI()
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "default_key")
bootstrap = Bootstrap5(app)
db_config(app)

# Configuración de Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

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
    
# Función para buscar detalles de películas por nombre
def get_movie_details(movie_name):
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
            # Extraer información de la primera película encontrada
            movie = results[0]
            return {
                "title": movie.get("title"),
                "overview": movie.get("overview"),
                "release_date": movie.get("release_date"),
                "vote_average": movie.get("vote_average"),
                "poster_path": f"https://image.tmdb.org/t/p/w500{movie.get('poster_path')}" if movie.get("poster_path") else None
            }
        else:
            return {"error": "No se encontraron resultados para esa película."}
    else:
        raise Exception(f"Error al buscar detalles de la película: {response.status_code}")


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

tmdb_function_descriptors.append({
    "name": "get_movie_details",
    "description": "Busca información sobre una película por su nombre.",
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
})


@app.errorhandler(403)
def forbidden(e):
    return render_template("403.html"), 403

@app.route("/")
def home():
    return redirect(url_for("login"))  # Redirige directamente al login


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("chat"))  # Redirige al chat si ya está autenticado

    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")
        user = User.query.filter_by(email=email).first()

        if user and check_password_hash(user.hashed_password, password):  # Verifica la contraseña hashed
            login_user(user)
            flash("Inicio de sesión exitoso.", "success")
            return redirect(url_for("chat"))  # Redirige al chat después de iniciar sesión correctamente
        else:
            # Flash para enviar un mensaje de error
            flash("Correo o contraseña incorrectos.", "danger")

    return render_template("login.html")  

@app.route("/logout", methods=["GET"])
@login_required
def logout():
    logout_user()
    flash("Sesión cerrada con éxito.", "success")
    return redirect(url_for("login"))

@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("chat"))

    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")
        if User.query.filter_by(email=email).first():
            flash("El correo ya está registrado.", "danger")
        else:
            hashed_password = generate_password_hash(password)
            new_user = User(email=email, hashed_password=hashed_password)
            db.session.add(new_user)
            db.session.commit()

            # Crear un perfil vacío asociado al nuevo usuario
            new_profile = Profile(user_id=new_user.id, favorite_movie_genres=[])
            db.session.add(new_profile)
            db.session.commit()

            flash("Registro exitoso. Ahora puedes iniciar sesión.", "success")
            login_user(new_user)
            return redirect(url_for("chat"))

    return render_template("register.html")

@app.route("/chat", methods=["GET", "POST"])
@login_required
def chat():
    user = current_user
    profile = Profile.query.filter_by(user_id=user.id).first()

    # Validar si el perfil existe
    if not profile:
        flash("Debes completar tu perfil antes de usar el chat.", "warning")
        return redirect(url_for("editar_perfil"))

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

            elif function_call.name == "get_movie_details":
                try:
                    # Llama a la función para obtener los detalles de la película
                    movie_details = get_movie_details(arguments['movie_name'])

                    # Prepara un contexto enriquecido para OpenAI
                    additional_context = f"Información de la película '{arguments['movie_name']}': {movie_details}. Usa esta información para responder de manera completa y útil al usuario."

                    # Reenvía los mensajes al modelo con el contexto adicional
                    messages_for_llm.append({
                        "role": "system",
                        "content": additional_context,
                    })

                    # Llamada al modelo para generar una respuesta elaborada
                    enriched_response = client.chat.completions.create(
                        messages=messages_for_llm,
                        model="gpt-4-0613",
                    )
                    model_response = enriched_response.choices[0].message.content or "Lo siento, no pude elaborar una respuesta."
                except Exception as e:
                    model_response = f"Hubo un error al obtener la información de la película: {str(e)}"

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
@login_required
def recommend():
    user = current_user
    data = request.get_json()
    user_message = data["message"]
    new_message = Message(content=user_message, author="user", user=user)
    db.session.add(new_message)
    db.session.commit()

    messages_for_llm = [
        {
            "role": "system",
            "content": """
            Eres un chatbot que recomienda películas, te llamas MovieAssist. 
            Tu rol es responder recomendaciones de manera breve y concisa, una pelicula por recomendacion. No repitas recomendaciones.
            Ademas debes considerar las preferencias del perfil del usuarios que tambien se pueden llamar generos de peliculas
            """,
        }
    ]

    # Llamar al modelo para generar una recomendación
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
@login_required
def editar_perfil():
    # Obtener el perfil del usuario
    profile = Profile.query.filter_by(user_id=current_user.id).first()

    # Si el perfil no existe, créalo
    if not profile:
        profile = Profile(user_id=current_user.id, favorite_movie_genres=[])
        db.session.add(profile)
        db.session.commit()

    if request.method == "POST":
        # Obtener los valores del formulario
        selected_genres = request.form.getlist("favorite_movie_genres")

        # Actualizar el perfil del usuario con los géneros seleccionados
        profile.favorite_movie_genres = selected_genres
        db.session.commit()

        # Flash para confirmar los cambios
        flash("Tus cambios han sido guardados correctamente.", "success")
        return redirect(url_for("editar_perfil"))

    return render_template("editar_perfil.html", profile=profile)

if __name__ == "__main__":
    app.run(debug=True)
