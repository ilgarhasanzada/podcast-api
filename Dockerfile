FROM python:3.12-slim

# Terminal çıxışlarını buferləməmək və .pyc fayllarını yaratmamaq üçün
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Sistem asılılıqları (lazım olarsa)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python asılılıqlarını quraşdırırıq
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Layihə fayllarını kopyalayırıq
COPY . /app/

EXPOSE 8000
