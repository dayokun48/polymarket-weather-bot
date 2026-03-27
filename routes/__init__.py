"""Flask routes package"""
from flask import Flask

from .overview  import overview_bp
from .signals   import signals_bp
from .settings  import settings_bp


def register_routes(app: Flask):
    app.register_blueprint(overview_bp)
    app.register_blueprint(signals_bp)
    app.register_blueprint(settings_bp)