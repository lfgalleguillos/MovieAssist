from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
import os

# Cargar variables de entorno
load_dotenv()

# Inicializar SQLAlchemy
db = SQLAlchemy()

def db_config(app):
    # Obtener la URI de conexión desde las variables de entorno
    db_uri = os.getenv("SQLALCHEMY_DATABASE_URI")
    if not db_uri:
        raise ValueError("SQLALCHEMY_DATABASE_URI no está configurada en el archivo .env")

    # Configurar la URI en la aplicación Flask
    app.config["SQLALCHEMY_DATABASE_URI"] = db_uri
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # Inicializar la extensión con la aplicación Flask
    db.init_app(app)

    # Probar la conexión
    print(f"Conectado a la base de datos: {db_uri}")

