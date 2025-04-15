# --- app/__init__.py ---

import os
import logging
from logging.handlers import RotatingFileHandler
from flask import Flask, current_app
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_mail import Mail
from itsdangerous import URLSafeTimedSerializer
from datetime import datetime
# --- V V V --- Cloudinary Imports --- V V V ---
import cloudinary
import cloudinary.utils
# --- ^ ^ ^ --- End Cloudinary Imports --- ^ ^ ^ ---

# Initialize extensions
db = SQLAlchemy()
login_manager = LoginManager()
mail = Mail()
serializer = None

# Configure logging formatter
log_formatter = logging.Formatter('%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]')

def create_app(config_class=None):
    """ Create and configure the Flask application. """
    app = Flask(__name__, instance_relative_config=True) # Keep instance folder for db maybe

    # Load Configuration (Remove UPLOAD_FOLDER)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get('SECRET_KEY', 'change_this_dev_secret_key'),
        SECURITY_PASSWORD_SALT=os.environ.get('SECURITY_PASSWORD_SALT', 'change_this_dev_salt'),
        SQLALCHEMY_DATABASE_URI=os.environ.get('DATABASE_URL', f"sqlite:///{os.path.join(app.instance_path, 'site.db')}"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        MAX_CONTENT_LENGTH = 5 * 1024 * 1024, # Keep general upload limit
        MAIL_SERVER=os.environ.get('MAIL_SERVER', 'smtp.example.com'),
        MAIL_PORT=int(os.environ.get('MAIL_PORT', 587)),
        MAIL_USE_TLS=os.environ.get('MAIL_USE_TLS', 'True').lower() in ['true', '1', 't'],
        MAIL_USE_SSL=os.environ.get('MAIL_USE_SSL', 'False').lower() in ['true', '1', 't'],
        MAIL_USERNAME=os.environ.get('MAIL_USERNAME'),
        MAIL_PASSWORD=os.environ.get('MAIL_PASSWORD'),
        MAIL_DEFAULT_SENDER=os.environ.get('MAIL_DEFAULT_SENDER', 'noreply@example.com'),
    )

    # Ensure instance folder exists (for SQLite DB if used locally)
    try: os.makedirs(app.instance_path, exist_ok=True)
    except OSError as e: app.logger.error(f"Error creating instance dir {app.instance_path}: {e}")

    # --- V V V --- Configure Cloudinary SDK --- V V V ---
    try:
        cloudinary.config(
            cloud_name = os.environ.get('CLOUDINARY_CLOUD_NAME'),
            api_key = os.environ.get('CLOUDINARY_API_KEY'),
            api_secret = os.environ.get('CLOUDINARY_API_SECRET'),
            secure=True # Use https URLs
        )
        if not all([cloudinary.config().cloud_name, cloudinary.config().api_key, cloudinary.config().api_secret]):
             app.logger.warning("CLOUDINARY environment variables not fully configured. Uploads will fail.")
        else:
             app.logger.info("Cloudinary SDK configured.")
    except Exception as e:
        app.logger.error(f"Cloudinary configuration error: {e}")
    # --- ^ ^ ^ --- End Cloudinary Config --- ^ ^ ^ ---


    # Initialize Flask Extensions
    try: db.init_app(app); login_manager.init_app(app); mail.init_app(app)
    except Exception as e: app.logger.error(f"Error initializing Flask extensions: {e}")

    # Initialize Serializer
    global serializer
    if not app.config.get('SECRET_KEY') or app.config['SECRET_KEY'] == 'change_this_dev_secret_key': app.logger.warning("Insecure SECRET_KEY.")
    if not app.config.get('SECURITY_PASSWORD_SALT') or app.config['SECURITY_PASSWORD_SALT'] == 'change_this_dev_salt': app.logger.warning("Insecure SALT.")
    serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'])

    # Configure Flask-Login
    login_manager.login_view = 'auth.login'; login_manager.login_message_category = 'info'; login_manager.login_message = "Please log in."
    @login_manager.user_loader
    def load_user(user_id):
        from .models import User
        try: return User.query.get(int(user_id))
        except ValueError: current_app.logger.error(f"Invalid user_id format: {user_id}"); return None
        except Exception as e: current_app.logger.error(f"Error loading user {user_id}: {e}"); return None

    # --- Context Processors ---
    @app.context_processor
    def inject_now(): return {'now': datetime.utcnow}

    # --- V V V --- Add Cloudinary URL Helper --- V V V ---
    @app.context_processor
    def utility_processor():
        def get_cloudinary_raw_url(public_id):
            # Generates a URL for non-image files stored on Cloudinary
            if not public_id: return None
            try:
                # Ensure Cloudinary is configured before trying to generate URL
                if cloudinary.config().cloud_name:
                    # resource_type='raw' for non-image/video files like PDFs
                    # secure=True ensures HTTPS
                    url_tuple = cloudinary.utils.cloudinary_url(public_id, resource_type="raw", secure=True)
                    return url_tuple[0] if url_tuple else None # cloudinary_url returns a tuple (url, options)
                else:
                    current_app.logger.warning("Cloudinary not configured, cannot generate URL.")
                    return None
            except Exception as e:
                current_app.logger.error(f"Error generating Cloudinary URL for {public_id}: {e}")
                return None
        return dict(get_cloudinary_raw_url=get_cloudinary_raw_url)
    # --- ^ ^ ^ --- End Cloudinary URL Helper --- ^ ^ ^ ---

    # Register Blueprints
    try:
        from .views import main_bp, auth_bp, jobs_bp, employers_bp, admin_bp
        app.register_blueprint(main_bp); app.register_blueprint(auth_bp, url_prefix='/auth'); app.register_blueprint(jobs_bp, url_prefix='/jobs'); app.register_blueprint(employers_bp, url_prefix='/employer'); app.register_blueprint(admin_bp, url_prefix='/admin')
        app.logger.info("Blueprints registered.")
    except Exception as e: app.logger.error(f"Error registering blueprints: {e}")

    # Setup Logging
    log_dir = 'logs'; log_file_path = os.path.join(log_dir, 'job_portal.log'); log_level = os.environ.get('LOG_LEVEL', 'INFO').upper(); logging_level = getattr(logging, log_level, logging.INFO)
    if not app.debug and not app.testing:
        if not os.path.exists(log_dir):
            try: os.mkdir(log_dir)
            except OSError as e: app.logger.error(f"Error creating logs directory '{log_dir}': {e}")
        try:
            file_handler = RotatingFileHandler(log_file_path, maxBytes=10240, backupCount=10); file_handler.setFormatter(log_formatter); file_handler.setLevel(logging_level)
            app.logger.addHandler(file_handler); app.logger.setLevel(logging_level)
            app.logger.info(f'Logging configured: {log_file_path}')
        except Exception as e: app.logger.error(f"Failed file logging: {e}")
    else: app.logger.setLevel(logging_level); app.logger.info("Debug/Testing mode: File logging skipped.")

    # Create Database Tables
    with app.app_context():
        try: db.create_all(); app.logger.info("DB tables checked/created (if needed).")
        except Exception as e: app.logger.error(f"Error db.create_all(): {e}"); app.logger.error(f"Check Database URI: {app.config.get('SQLALCHEMY_DATABASE_URI')}")

    # Final Checks
    if not app.config.get('MAIL_USERNAME') or not app.config.get('MAIL_PASSWORD'): app.logger.warning("MAIL config missing. Email disabled.")

    app.logger.info("Flask app creation finished.")
    return app

# --- End of __init__.py ---