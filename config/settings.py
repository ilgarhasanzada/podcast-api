"""
Django settings for config project.
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / 'apps'))

# Load environment variables from .env file
load_dotenv(BASE_DIR / '.env')

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-dev-secret-key-podcast-api-12345')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.getenv('DEBUG', 'True').lower() in ('true', '1', 'yes')

ALLOWED_HOSTS = [host.strip() for host in os.getenv('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',') if host.strip()]


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Third party apps
    'rest_framework',
    'django_filters',
    'drf_spectacular',

    # Local apps
    'apps.common',
    'apps.podcasts',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


# Database
# https://docs.djangoproject.com/en/5.2/ref/settings/#databases

DB_ENGINE = os.getenv('DB_ENGINE', 'sqlite').lower()

if DB_ENGINE == 'postgresql':
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.getenv('DB_NAME', 'podcast_db'),
            'USER': os.getenv('DB_USER', 'podcast_user'),
            'PASSWORD': os.getenv('DB_PASSWORD', 'podcast_password'),
            'HOST': os.getenv('DB_HOST', 'localhost'),
            'PORT': os.getenv('DB_PORT', '5432'),
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }


# Password validation
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.2/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.2/howto/static-files/

STATIC_URL = 'static/'

# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# Django REST Framework Settings
REST_FRAMEWORK = {
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ],
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
}

# drf-spectacular (OpenAPI / Swagger) Settings
SPECTACULAR_SETTINGS = {
    'TITLE': 'Podcast Aggregation & Charts API',
    'DESCRIPTION': 'RESTful API documentation for podcast aggregation, international chart rankings, rating enrichment, and episode management.',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'COMPONENT_SPLIT_REQUEST': True,
    'PREPROCESSING_HOOKS': [
        'apps.common.utils.exclude_slashless_duplicate_routes',
    ],
}

# Cache Settings (High-performance caching with Redis)
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': os.getenv('REDIS_CACHE_URL', os.getenv('CELERY_BROKER_URL', 'redis://localhost:6379/1')),
    }
}


# Celery Settings
CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = os.getenv('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE
CELERY_WORKER_PREFETCH_MULTIPLIER = 1  # Fair task distribution, prevents worker starvation
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_SOFT_TIME_LIMIT = 60
CELERY_TASK_TIME_LIMIT = 90
CELERY_WORKER_SEND_TASK_EVENTS = True
CELERY_TASK_SEND_SENT_EVENT = True
CELERY_TASK_TRACK_STARTED = True

# Celery Beat Periodic Tasks
from celery.schedules import crontab

CELERY_BEAT_SCHEDULE = {
    # 1. Daily scraping at 04:00 UTC for rankings and episodes across all active countries
    'daily-podcast-chart-scraping': {
        'task': 'apps.podcasts.tasks.daily_chart_scraping_task',
        'schedule': crontab(hour=4, minute=0),
        'kwargs': {'countries': None, 'limit': 50, 'fetch_episodes_for_top': None},
    },
    # 2. Weekly country discovery on Sundays at 03:00 UTC (Apple storefronts & Spotify markets)
    'weekly-country-discovery': {
        'task': 'apps.podcasts.tasks.discover_and_cache_countries_task',
        'schedule': crontab(hour=3, minute=0, day_of_week=0),
    },
    # 3. Weekly category discovery on Sundays at 03:30 UTC (Apple Podcasts iTunes genre taxonomy)
    'weekly-category-discovery': {
        'task': 'apps.podcasts.tasks.discover_and_sync_categories_task',
        'schedule': crontab(hour=3, minute=30, day_of_week=0),
    },
    # 4. Daily rating enrichment at 05:00 UTC for podcasts lacking ratings
    'daily-rating-enrichment': {
        'task': 'apps.podcasts.tasks.enrich_all_ratings_task',
        'schedule': crontab(hour=5, minute=0),
        'kwargs': {'limit': 50},
    },
    # 5. Periodic task every 30 minutes to asynchronously sync missing podcast episodes
    'sync-missing-episodes': {
        'task': 'apps.podcasts.tasks.sync_missing_episodes_task',
        'schedule': crontab(minute='*/30'),
        'kwargs': {'batch_size': 50, 'max_episodes': None},
    },
    # 6. Periodic refresh every 6 hours to check new releases for existing podcasts (Technical Specification 2.3)
    'periodic-refresh-all-episodes': {
        'task': 'apps.podcasts.tasks.sync_all_existing_podcasts_episodes_task',
        'schedule': crontab(hour='*/6', minute=15),
        'kwargs': {'batch_size': 100, 'max_episodes': None},
    },
}

