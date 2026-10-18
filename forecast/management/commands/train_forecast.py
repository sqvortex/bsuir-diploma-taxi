"""
Обучает модель прогноза на истории рейсов, печатает её точность
в сравнении с простым средним и сохраняет модель в файл.

Запуск:  python manage.py train_forecast
Модель стоит переобучать регулярно, например раз в неделю.
"""

from django.core.management.base import BaseCommand, CommandError

from forecast import model


class Command(BaseCommand):
    help = "Обучает модель прогноза свободных мест и сравнивает её с простым средним"

    def add_arguments(self, parser):
        parser.add_argument("--test-days", type=int, default=60,
                            help="сколько последних дней истории отложить для проверки (по умолчанию 60)")

    def handle(self, *args, test_days, **options):
        try:
            result = model.train(test_days=test_days)
        except ValueError as error:
            raise CommandError(str(error))
        path = model.save(result.bundle)
        report = result.report

        self.stdout.write(f"Обучение на рейсах до {report['split_date']}: {report['train_trips']}, "
                          f"проверка на рейсах после: {report['test_trips']}.")
        self.stdout.write("Ошибка прогноза свободных мест к отправлению (MAE — в местах, WAPE — в процентах):")
        self.stdout.write(f"  {'дней до отправления':<22}{'модель':>18}{'простое среднее':>22}")
        rows = [("все", report["model"], report["baseline"])]
        rows += [(str(d), v["model"], v["baseline"]) for d, v in report["by_horizon"].items()]
        for label, ours, base in rows:
            self.stdout.write(
                f"  {label:<22}{ours['mae']:>8} / {ours['wape']:>5}%{base['mae']:>12} / {base['wape']:>5}%"
            )
        self.stdout.write(self.style.SUCCESS(f"Модель сохранена: {path}"))
