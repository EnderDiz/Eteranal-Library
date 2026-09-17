from flask import Blueprint

bp = Blueprint("tierlists_manage", __name__)

from . import characters, dashboard, games, revisions  # noqa: E402,F401

__all__ = ["bp"]
