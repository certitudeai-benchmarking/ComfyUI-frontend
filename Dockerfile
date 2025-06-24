FROM python:3.12-slim

# Set Env Variables
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# Install system level Dependencies
RUN apt-get update && apt-get install -y \
    git \
    wget \
    curl \
    build-essential \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    libsndfile1 \
    libffi-dev \
    libgmp-dev \
    libmpfr-dev \
    libmpc-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pop
RUN pip install --upgrade pip

# Create working directory
WORKDIR /app

# Copy your entire ComfyUI directory
# This includes custom_nodes, comfy_compat, and all your configurations
COPY . .

RUN pip install -r requirements.txt

EXPOSE 8188

CMD ["python", "main.py", "--listen", "0.0.0.0", "--port", "8188"]