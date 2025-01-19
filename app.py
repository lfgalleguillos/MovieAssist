from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
import os
import json
import pandas as pd
from flask_bootstrap import Bootstrap5
from openai import OpenAI
from dotenv import load_dotenv
from config.db.db import db_config, db
from config.models.models import User, Message, Profile
import requests
import re
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash

load_dotenv()

client = OpenAI()
app = Flask(__name__)
app.debug = True
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

print(f"Bearer Token utilizado: {TMDB_BEARER_TOKEN}")

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
    try:
        search_endpoint = f"{TMDB_BASE_URL}/search/movie"
        headers = {
            "accept": "application/json",
            "Authorization": f"Bearer {TMDB_BEARER_TOKEN}"
        }
        params = {
            "query": movie_name,
            "include_adult": False,
            "language": "es-ES",  # Cambiar a español
            "page": 1
        }

        response = requests.get(search_endpoint, headers=headers, params=params)
        print(f"Solicitud a {search_endpoint}, respuesta: {response.status_code}, datos: {response.text}")

        if response.status_code == 200:
            results = response.json().get("results", [])
            if results:
                movie = results[0]
                return {
                    "title": movie.get("title"),
                    "overview": movie.get("overview"),
                    "release_date": movie.get("release_date"),
                    "vote_average": movie.get("vote_average"),
                    "poster_path": f"https://image.tmdb.org/t/p/w500{movie.get('poster_path')}" if movie.get("poster_path") else None
                }
            else:
                return {"error": f"No se encontraron resultados para la película '{movie_name}'."}
        elif response.status_code == 401:
            raise Exception("Error de autenticación: verifica tu Bearer Token.")
        else:
            raise Exception(f"Error al buscar detalles de la película: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"Error en get_movie_details: {str(e)}")
        return {"error": f"Excepción en get_movie_details: {str(e)}"}

# Función para buscar el ID de una serie de TV
def get_tv_id(tv_name):
    try:
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

        # Log para depuración
        print(f"Solicitud a {search_endpoint}, respuesta: {response.status_code}, datos: {response.text}")

        if response.status_code == 200:
            results = response.json().get("results", [])
            if results:
                return results[0].get("id")
            else:
                return None
        elif response.status_code == 401:
            raise Exception("Error de autenticación: verifica tu Bearer Token.")
        else:
            raise Exception(f"Error al buscar el tv_id: {response.status_code}")
    except Exception as e:
        print(f"Error en get_tv_id: {str(e)}")
        raise

# Función para buscar los proveedores de streaming en Chile para una película o serie
def get_streaming_providers(name, type="movie"):
    try:
        # Determinar el endpoint según el tipo
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

        print(f"Solicitud a {providers_endpoint}, respuesta: {response.status_code}, datos: {response.json()}")

        if response.status_code == 200:
            providers = response.json().get("results", {}).get("CL", {}).get("flatrate", [])
            if providers:
                return [provider["provider_name"] for provider in providers]
            else:
                return ["No se encontraron proveedores de streaming disponibles en Chile."]
        else:
            return [f"Error en la API de TMDB: Código {response.status_code}"]

    except Exception as e:
        print(f"Error en get_streaming_providers: {str(e)}")
        return [f"Error al obtener proveedores: {str(e)}"]


def extract_movie_name(message):
    """
    Esta función extrae el nombre de la película de un mensaje. 
    Asume que el nombre de la película sigue frases como "donde puedo ver" o "qué me puedes decir sobre".
    """
    # Usamos una expresión regular para buscar un patrón que sea típico en una pregunta sobre películas
    # Ejemplo: "donde puedo ver [nombre de la película]" o "qué me puedes decir sobre [nombre de la película]"
    match = re.search(r"(donde puedo ver|qué me puedes decir sobre)\s*['\"]?([^'\"]+)[\"']?", message, re.IGNORECASE)
    
    if match:
        # Si se encuentra un nombre de película en el mensaje, lo retornamos
        return match.group(2).strip()
    else:
        # Si no se encuentra ningún nombre de película, devolvemos None
        return None

# Descriptor para Function Calling
tmdb_function_descriptors = [
    {
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
    },
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
            flash("Correo o contraseña incorrectos.", "danger")

    return render_template("login.html")  

@app.route("/logout", methods=["GET"])
@login_required
def logout():    
    logout_user()
    flash("Sesión cerrada con éxito.", "success")
    return redirect(url_for("login"))

@app.route("/chat", methods=['GET', 'POST'])
@login_required
def chat():
    try:
        user = current_user
        profile = Profile.query.filter_by(user_id=user.id).first()

        if not profile:
            flash("Debes completar tu perfil antes de usar el chat.", "warning")
            return redirect(url_for("editar_perfil"))

        # Crear intents basados en los géneros favoritos del perfil
        session["profile"] = {"favorite_movie_genres": profile.favorite_movie_genres}
        intents = {f"Recomiéndame una película de {topic}": f"Recomiéndame una película de {topic}" for topic in session["profile"]["favorite_movie_genres"]}
        profile_context = f"Recomendar películas para géneros: {', '.join(profile.favorite_movie_genres)}." if intents else "Recomendaciones de películas."

        # Obtener los datos del formulario
        message_text = request.form.get("message")
        intent = request.form.get("intent")

        if request.method == "POST" and (intent or message_text):
            user_message = intents.get(intent, message_text)

            if user_message:
                # Guardar el mensaje del usuario
                db.session.add(Message(content=user_message, author="user", user=user))
                db.session.commit()

                # Construir los mensajes para el modelo
                messages_for_llm = [{"role": "system", "content": profile_context}] + [
                    {"role": msg.author, "content": msg.content} for msg in user.messages[-10:]
                ]

                try:
                    chat_completion = client.chat.completions.create(
                        messages=messages_for_llm,
                        model="gpt-4-0613",
                        functions=tmdb_function_descriptors,
                        function_call="auto",
                    )
                except Exception as e:
                    return jsonify({'status': 'error', 'message': f'Error del modelo: {str(e)}'}), 500

                # Manejar la respuesta del modelo
                if chat_completion.choices[0].finish_reason == "function_call":
                    function_call = chat_completion.choices[0].message.function_call
                    arguments = json.loads(function_call.arguments)

                    if function_call.name == "get_movie_details":
                        try:
                            # Llama a la función para obtener detalles de la película
                            movie_details = get_movie_details(arguments["movie_name"])
                            if "error" in movie_details:
                                model_response = movie_details["error"]
                            else:
                                model_response = (
                                    f"Título: {movie_details['title']}\n"
                                    f"Sinopsis: {movie_details['overview']}\n"
                                    f"Fecha de lanzamiento: {movie_details['release_date']}\n"
                                    f"Calificación: {movie_details['vote_average']}\n"
                                    f"Póster: {movie_details['poster_path']}"
                                )
                        except Exception as e:
                            model_response = f"Hubo un error al procesar la solicitud: {str(e)}"

                    elif function_call.name == "get_streaming_providers":
                        try:
                            # Llama a la función para obtener proveedores de streaming
                            providers = get_streaming_providers(arguments["name"], arguments["type"])
                            if providers and isinstance(providers, list):
                                model_response = (
                                    f"Proveedores de streaming disponibles en Chile para '{arguments['name']}' ({arguments['type']}): "
                                    f"{', '.join(providers)}"
                                )
                            else:
                                model_response = f"No se encontraron proveedores de streaming para '{arguments['name']}' ({arguments['type']})."
                        except Exception as e:
                            model_response = f"Hubo un error al procesar la solicitud: {str(e)}"

                    else:
                        model_response = f"No se reconoció la función solicitada: {function_call.name}"
                else:
                    model_response = chat_completion.choices[0].message.content or "No se generó una respuesta válida."

                # Guardar la respuesta del modelo
                if model_response and model_response.strip():
                    db.session.add(Message(content=model_response, author="assistant", user=user))
                    db.session.commit()

            messages_data = [{"author": msg.author, "content": msg.content} for msg in user.messages]
            return jsonify({'status': 'success', 'messages': messages_data})

        if request.method == "GET":
            return render_template("chat.html", messages=user.messages, intents=intents)

    except Exception as e:
        print(f"Error general en la función 'chat': {str(e)}")
        return jsonify({'status': 'error', 'message': f'Error inesperado: {str(e)}'}), 500

    return jsonify({'status': 'error', 'message': 'Request no válido.'}), 400

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
            Eres un chatbot que recomienda películas, te llamas MovieAssist. Responde siempre en español.
            Tu rol es responder recomendaciones de manera breve y concisa, una pelicula por recomendacion. No repitas recomendaciones.
            Ademas debes considerar las preferencias del perfil del usuarios que tambien se pueden llamar generos de peliculas.
            Si se proporciona información en inglés, tradúcela al español antes de incluirla en tu respuesta.
            Por ejemplo, los títulos, sinopsis, fechas y cualquier dato deben estar en español.
            """,
        }
    ]

    # Llamar al modelo para generar una recomendación
    chat_completion = client.chat.completions.create(
        messages=messages_for_llm,
        model="gpt-4o",
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

        # Redirigir o mostrar un mensaje de éxito
        flash("Perfil actualizado con éxito", "success")
        return redirect(url_for("editar_perfil"))

    return render_template("editar_perfil.html", profile=profile)

if __name__ == "__main__":
    app.run(debug=True)
