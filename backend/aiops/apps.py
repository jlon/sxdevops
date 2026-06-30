from django.apps import AppConfig


class AiopsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'aiops'
    verbose_name = 'AIOps'

    def ready(self):
        from .incident_investigation import register_llm_rca_planner
        from .services import generate_incident_llm_root_cause

        register_llm_rca_planner(generate_incident_llm_root_cause)
