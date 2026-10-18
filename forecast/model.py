"""
Модель прогноза свободных мест (алгоритм 4 из ТЗ).

Модель — градиентный бустинг из scikit-learn (HistGradientBoostingRegressor).
Она учится на истории выполненных рейсов предсказывать, сколько мест на перегоне
будет занято к отправлению. Свободные места = вместимость − прогноз.

Точность проверяется честно: модель учится на рейсах до даты X,
а проверяется на рейсах после X, которых она не видела. С ней сравнивается
простое среднее — средняя загрузка таких же рейсов (тот же маршрут, перегон,
день недели и время) за 4 прошлые недели.

Обученная модель сохраняется в файл settings.FORECAST_MODEL_PATH.
"""

import math
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from sklearn.ensemble import HistGradientBoostingRegressor
from threadpoolctl import threadpool_limits

from transport.models import Trip

from .dataset import FEATURES, current_table, training_table

REPORT_HORIZONS = [0, 1, 3, 7, 14]


# ---------- Обучение и проверка ----------

def make_regressor():
    return HistGradientBoostingRegressor(
        max_iter=300, learning_rate=0.08, max_leaf_nodes=31,
        # Маршрут — категория (номер маршрута не «больше» и не «меньше» другого).
        categorical_features=[FEATURES.index("route")],
        random_state=0,
    )


def to_matrix(table, routes):
    """Признаки в виде чисел. Маршрут кодируется номером в списке routes, неизвестный — пропуск."""
    matrix = table[FEATURES].astype(float).copy()
    codes = {route: index for index, route in enumerate(routes)}
    matrix["route"] = table["route"].map(codes).astype(float)
    return matrix


def simple_mean(table, weeks=4):
    """
    Простое среднее: загрузка перегона в таких же рейсах (маршрут, перегон, день недели,
    время отправления) за прошлые недели. Считается по таблице с ответами, только по прошлому.
    """
    finals = table[table["days_before"] == 0].sort_values("departure")
    keys = ["route", "leg", "weekday", "minutes"]
    finals = finals.assign(mean=finals.groupby(keys)["target"].transform(
        lambda s: s.shift(1).rolling(weeks, min_periods=1).mean()
    ))
    return table.merge(finals[["trip", "leg", "mean"]], on=["trip", "leg"], how="left")["mean"]


def metrics(true_free, pred_free):
    """MAE — средняя ошибка в местах; WAPE — сумма ошибок / сумма свободных мест, в процентах."""
    error = np.abs(np.asarray(true_free) - np.asarray(pred_free))
    total = float(np.sum(true_free))
    return {
        "mae": round(float(error.mean()), 2),
        "wape": round(100 * float(error.sum()) / total, 1) if total else None,
    }


@dataclass
class TrainResult:
    bundle: dict
    report: dict = field(default_factory=dict)


def train(test_days=60, now=None):
    """
    1) Строит таблицу по всем выполненным рейсам.
    2) Учит модель на рейсах до даты X = сегодня − test_days и проверяет на рейсах после X.
    3) Сравнивает с простым средним.
    4) Переобучает модель на всех данных — её и сохраняем для работы сайта.
    """
    now = now or timezone.now()
    table = training_table(Trip.objects.filter(status=Trip.Status.COMPLETED, departure_at__lt=now))
    if table.empty:
        raise ValueError("Нет истории рейсов. Сначала запустите: python manage.py generate_history")
    table = table.assign(free=table["capacity"] - table["target"])
    table["baseline"] = simple_mean(table)
    routes = sorted(table["route"].unique().tolist())

    split = now - timedelta(days=test_days)
    train_part = table[table["departure"] < split]
    test_part = table[(table["departure"] >= split) & table["baseline"].notna()]
    if train_part.empty or test_part.empty:
        raise ValueError("Мало истории: нужно больше дней, чем test_days.")

    model = make_regressor().fit(to_matrix(train_part, routes), train_part["target"])
    predicted = np.maximum(model.predict(to_matrix(test_part, routes)), test_part["sold"])
    test_part = test_part.assign(pred=predicted)

    report = {
        "split_date": timezone.localdate(split).isoformat(),
        "train_trips": int(train_part["trip"].nunique()),
        "test_trips": int(test_part["trip"].nunique()),
        "model": metrics(test_part["free"], test_part["capacity"] - test_part["pred"]),
        "baseline": metrics(test_part["free"], test_part["capacity"] - test_part["baseline"]),
        "by_horizon": {},
    }
    # Разброс ошибки для каждого «дней до отправления»: 80% ошибок не больше этого числа мест.
    spread = {}
    for days, part in test_part.groupby("days_before"):
        errors = np.abs(part["target"] - part["pred"])
        spread[int(days)] = float(np.quantile(errors, 0.8))
        if days in REPORT_HORIZONS:
            report["by_horizon"][int(days)] = {
                "model": metrics(part["free"], part["capacity"] - part["pred"]),
                "baseline": metrics(part["free"], part["capacity"] - part["baseline"]),
            }

    final_model = make_regressor().fit(to_matrix(table, routes), table["target"])
    bundle = {
        "model": final_model,
        "routes": routes,
        "spread": spread,
        "report": report,
        "trained_at": now,
        "trips": int(table["trip"].nunique()),
    }
    return TrainResult(bundle=bundle, report=report)


def save(bundle, path=None):
    path = Path(path or settings.FORECAST_MODEL_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, path)
    return path


_cache = {"key": None, "bundle": None}


def load():
    """Обученная модель из файла или None, если её ещё не обучали. Файл читается один раз."""
    path = Path(settings.FORECAST_MODEL_PATH)
    if not path.exists():
        return None
    key = (str(path), path.stat().st_mtime)
    if _cache["key"] != key:
        _cache["key"], _cache["bundle"] = key, joblib.load(path)
    return _cache["bundle"]


# ---------- Прогноз для будущих рейсов ----------

@dataclass
class LegForecast:
    leg: int
    sold: int          # продано сейчас
    expected: float    # ожидается занятых мест к отправлению
    low: float         # нижняя граница (с учётом разброса ошибки)
    high: float        # верхняя граница


@dataclass
class TripForecast:
    trip_id: int
    capacity: int
    days_before: int
    legs: list

    def _legs_between(self, from_order=None, to_order=None):
        """Перегоны участка «с остановки from_order до остановки to_order»."""
        start = from_order or 1
        end = to_order or len(self.legs) + 1
        return [leg for leg in self.legs if start <= leg.leg < end] or self.legs

    def peak(self, from_order=None, to_order=None):
        """Самый загруженный перегон участка: он и ограничивает число свободных мест."""
        return max(self._legs_between(from_order, to_order), key=lambda leg: leg.expected)

    def free_range(self, from_order=None, to_order=None):
        """Сколько мест останется к отправлению: (от, до) — диапазон для пассажира."""
        legs = self._legs_between(from_order, to_order)
        high_load = max(leg.high for leg in legs)
        low_load = max(leg.low for leg in legs)
        free_now = self.capacity - max(leg.sold for leg in legs)
        low = max(self.capacity - math.ceil(high_load), 0)
        high = min(max(self.capacity - math.floor(low_load), 0), free_now)
        return min(low, high), high

    @property
    def expected_load(self):
        return self.peak().expected

    @property
    def load_percent(self):
        return round(100 * self.expected_load / self.capacity) if self.capacity else 0


def predict(trips, now=None, bundle=None):
    """Прогноз для рейсов trips (QuerySet). Возвращает {id рейса: TripForecast} или {}, если модели нет."""
    bundle = bundle or load()
    if bundle is None:
        return {}
    table = current_table(trips, now=now)
    if table.empty:
        return {}
    # Для нескольких строк один поток быстрее: потоки OpenMP не мешают друг другу,
    # когда сайт обслуживает много запросов одновременно.
    with threadpool_limits(1):
        raw = bundle["model"].predict(to_matrix(table, bundle["routes"]))
    # Уже проданные места никуда не денутся (почти): прогноз не может быть меньше проданного.
    # И не может быть больше вместимости: больше мест, чем в машине, не продать.
    table = table.assign(expected=np.clip(np.maximum(raw, table["sold"]), 0, table["capacity"]))

    result = {}
    for trip_id, part in table.groupby("trip"):
        days = int(part["days_before"].iloc[0])
        spread = bundle["spread"].get(days, max(bundle["spread"].values()))
        capacity = int(part["capacity"].iloc[0])
        legs = [
            LegForecast(
                leg=int(row.leg), sold=int(row.sold), expected=float(row.expected),
                low=max(float(row.expected) - spread, float(row.sold)),
                high=float(row.expected) + spread,
            )
            for row in part.sort_values("leg").itertuples()
        ]
        result[int(trip_id)] = TripForecast(trip_id=int(trip_id), capacity=capacity, days_before=days, legs=legs)
    return result


def predict_cached(trips, now=None):
    """
    То же, что predict, но готовые прогнозы рейсов 60 секунд лежат в кеше. Нужно для страницы
    поиска: её открывают много людей сразу, а прогноз на одну минуту почти не меняется.
    Прогнозы пассажиру показываются вместе с реальным числом свободных мест, поэтому
    устаревшие на минуту данные не дают лишнего (см. core/views.py, add_forecast).
    """
    bundle = load()
    if bundle is None:
        return {}
    trips = list(trips)
    stamp = bundle["trained_at"].timestamp()
    key = lambda trip: f"forecast:{stamp}:{trip.pk}:{trip.departure_at.timestamp()}"  # noqa: E731
    found = cache.get_many([key(trip) for trip in trips])
    result = {trip.pk: found[key(trip)] for trip in trips if key(trip) in found}
    missing = [trip for trip in trips if trip.pk not in result]
    if missing:
        fresh = predict(Trip.objects.filter(pk__in=[trip.pk for trip in missing]), now=now, bundle=bundle)
        cache.set_many({key(trip): fresh[trip.pk] for trip in missing if trip.pk in fresh},
                       settings.FORECAST_CACHE_SECONDS)
        result.update(fresh)
    return result
