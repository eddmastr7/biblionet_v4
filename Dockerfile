# Imagen base de Python
FROM python:3.12-slim

# Evitar archivos .pyc y usar stdout
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Instalar dependencias del sistema (para mysqlclient)
RUN apt-get update && apt-get install -y \
    build-essential \
    default-libmysqlclient-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Crear carpeta de trabajo
WORKDIR /app

# Copiar requirements e instalarlos
COPY requirements.txt /app/

RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# Copiar TODO el proyecto
COPY . /app/

# Puerto que expone Django
EXPOSE 8000

# Comando por defecto (lo sobreescribimos en docker-compose)
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
