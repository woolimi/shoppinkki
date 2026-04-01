"""customer_web configuration."""

import os

CONTROL_SERVICE_HOST = os.getenv('CONTROL_SERVICE_HOST', 'localhost')
CONTROL_SERVICE_PORT = int(os.getenv('CONTROL_SERVICE_PORT', '8080'))
SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-change-me')
DEBUG = os.getenv('FLASK_DEBUG', '1') == '1'
PORT = int(os.getenv('PORT', '8501'))
