"""
Автоматическое создание рейсов по шаблонам расписания (ФТ-12).

Пример: шаблон «Минск – Гомель, 07:30, дни 12345» за неделю
превращается в 5 рейсов: с понедельника по пятницу в 07:30.

Функцию можно вызывать сколько угодно раз: если рейс на это время
уже есть, второй не создаётся (это защищает и уникальное ограничение
в базе: маршрут + время отправления).
"""

from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.db.models import Q

from .models import ScheduleTemplate, Trip


@dataclass
class GenerationResult:
    created: int = 0   # сколько новых рейсов создано
    existing: int = 0  # сколько рейсов уже было и пропущено


def active_templates(date_from, date_to):
    """Шаблоны действующих маршрутов, срок которых пересекается с периодом."""
    return (
        ScheduleTemplate.objects.filter(route__is_active=True, valid_from__lte=date_to)
        .filter(Q(valid_to__isnull=True) | Q(valid_to__gte=date_from))
        .select_related("route", "default_vehicle", "default_driver")
    )


@transaction.atomic
def generate_trips(date_from, date_to, templates=None):
    """Создаёт рейсы по шаблонам на каждый день с date_from по date_to включительно."""
    if templates is None:
        templates = active_templates(date_from, date_to)

    result = GenerationResult()
    for template in templates:
        day = date_from
        while day <= date_to:
            if template.runs_on(day):
                _, created = Trip.objects.get_or_create(
                    route=template.route,
                    departure_at=template.departure_on(day),
                    defaults={
                        "template": template,
                        "vehicle": template.default_vehicle,
                        "driver": template.default_driver,
                    },
                )
                if created:
                    result.created += 1
                else:
                    result.existing += 1
            day += timedelta(days=1)
    return result
