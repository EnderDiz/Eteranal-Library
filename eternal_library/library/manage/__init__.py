from flask import Blueprint

bp = Blueprint("library_manage", __name__, url_prefix="/library/manage")

from . import routes  # noqa: E402,F401

__all__ = ["bp"]
