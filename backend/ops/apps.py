from pathlib import Path

from django.apps import AppConfig


class OpsConfig(AppConfig):
    name = 'ops'
    path = str(Path(__file__).resolve().parent)
