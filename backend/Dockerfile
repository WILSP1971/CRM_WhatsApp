FROM python:3.11-slim

WORKDIR /app

# Dependencias del sistema
# ffmpeg: transcodificación local a OGG/Opus del clip TTS (Entregable #6,
# SPEC-069, R-88) — hallazgo de SPEC-067: NO estaba instalado (contradecía el
# supuesto de PLAN-008 de que ya venía con el stack STT; faster-whisper usa
# PyAV/FFmpeg embebido, sin binario de sistema, ver
# app/integrations/whatsapp/media_client.py). Sin egress: paquete de Debian,
# nunca invoca red en runtime.
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    curl \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Dependencias Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código de la aplicación
COPY . .

# Hacer ejecutable el script de inicialización del almacén de audio (SPEC-035)
RUN chmod +x /app/app/workers/init_audio_store.sh

# Exponer puerto (definido por variable de entorno en compose)
EXPOSE 8000

# Comando por defecto: arrancar con uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
