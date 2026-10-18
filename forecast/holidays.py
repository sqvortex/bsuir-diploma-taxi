"""
Государственные праздники Республики Беларусь — признак для прогноза.
Перед праздниками людей едет больше, в сами праздники обычно меньше.
"""

from datetime import date, timedelta

# Праздники с постоянной датой: (месяц, день)
FIXED_HOLIDAYS = [
    (1, 1), (1, 2),  # Новый год
    (1, 7),          # Рождество Христово (православное)
    (3, 8),          # День женщин
    (5, 1),          # Праздник труда
    (5, 9),          # День Победы
    (7, 3),          # День Независимости
    (11, 7),         # День Октябрьской революции
    (12, 25),        # Рождество Христово (католическое)
]


def orthodox_easter(year):
    """Дата православной Пасхи (алгоритм Гаусса по юлианскому календарю, перевод в григорианский)."""
    a, b, c = year % 4, year % 7, year % 19
    d = (19 * c + 15) % 30
    e = (2 * a + 4 * b - d + 34) % 7
    month, day = divmod(d + e + 114, 31)
    julian = date(year, month, day + 1)
    return julian + timedelta(days=13)  # разница календарей в 1900–2099 годах


def holidays(year):
    """Все праздничные дни года, включая Радуницу (9-й день после Пасхи)."""
    days = {date(year, month, day) for month, day in FIXED_HOLIDAYS}
    days.add(orthodox_easter(year) + timedelta(days=9))
    return days


_cache = {}


def is_holiday(day):
    if day.year not in _cache:
        _cache[day.year] = holidays(day.year)
    return day in _cache[day.year]


def is_pre_holiday(day):
    """Канун праздника: завтра праздник, а сегодня ещё нет."""
    return not is_holiday(day) and is_holiday(day + timedelta(days=1))
