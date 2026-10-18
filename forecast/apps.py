import sys

from django.apps import AppConfig

# Команды, которым модель при старте не нужна: не тратим на неё время.
SKIP_WARMUP = {"migrate", "makemigrations", "collectstatic", "test", "generate_history", "train_forecast"}


class ForecastConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "forecast"
    verbose_name = "Прогноз свободных мест"

    def ready(self):
        """
        Загружаем библиотеки и обученную модель при запуске сайта, а не при первом поиске:
        иначе первый посетитель ждал бы несколько секунд, пока загрузятся pandas и scikit-learn.
        """
        if len(sys.argv) > 1 and sys.argv[1] in SKIP_WARMUP or "pytest" in sys.modules:
            return
        from . import model
        try:
            model.load()
        except Exception:  # повреждённый файл модели не должен ломать запуск сайта
            pass
