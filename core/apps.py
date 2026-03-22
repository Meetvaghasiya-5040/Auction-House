from django.apps import AppConfig

class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'

    def ready(self):
        print("====== CORE APP IS READY, IMPORTING SIGNALS ======")
        import core.signals
