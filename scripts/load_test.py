"""
Проверка нагрузки (раздел 8 ТЗ): поиск рейсов должен отвечать не дольше 2 секунд
при 50 одновременных пользователях.

Скрипт запускает сайт не сам: сначала запустите его, потом в другом окне:

    python scripts/load_test.py                       # 50 пользователей, адрес http://127.0.0.1:8000
    python scripts/load_test.py --users 100 --rounds 5 --url http://127.0.0.1:8000

Каждый «пользователь» входит на сайт под пассажиром, потом несколько раз подряд ищет рейсы
на завтра по разным направлениям, как это делал бы человек. Все пользователи стартуют
одновременно. В конце печатается таблица времени ответа и вердикт «уложились в 2 секунды».
Нужны демо-данные (python manage.py load_demo). Библиотеки ставить не нужно.
"""

import argparse
import http.cookiejar
import re
import statistics
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

DIRECTIONS = [("Минск", "Гомель"), ("Минск", "Пинск"), ("Минск", "Могилёв"), ("Минск", "Бобруйск")]
LIMIT_SECONDS = 2.0


def make_opener():
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def login(opener, base, phone, password):
    page = opener.open(f"{base}/accounts/login/", timeout=30).read().decode()
    token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page).group(1)
    data = urllib.parse.urlencode({"username": phone, "password": password, "csrfmiddlewaretoken": token}).encode()
    request = urllib.request.Request(f"{base}/accounts/login/", data=data, headers={"Referer": f"{base}/accounts/login/"})
    opener.open(request, timeout=30).read()


def user_session(index, args, start, ready, results, errors):
    opener = make_opener()
    try:
        login(opener, args.url, args.phone, args.password)
    except Exception as error:  # без входа пользователь не стартует
        errors.append(f"вход: {error}")
        ready.release()
        return
    ready.release()  # вошёл и ждёт общего старта
    tomorrow = date.today() + timedelta(days=1)
    start.wait()  # все пользователи начинают поиск в один момент
    for round_number in range(args.rounds):
        from_city, to_city = DIRECTIONS[(index + round_number) % len(DIRECTIONS)]
        query = urllib.parse.urlencode({"from_city": from_city, "to_city": to_city, "date": tomorrow.isoformat()})
        began = time.perf_counter()
        try:
            body = opener.open(f"{args.url}/search/?{query}", timeout=60).read().decode()
            elapsed = time.perf_counter() - began
            if "Выбрать" not in body and "не нашли" not in body.lower():
                errors.append("страница поиска без результатов и без сообщения")
            results.append(elapsed)
        except (urllib.error.URLError, OSError) as error:
            errors.append(f"поиск: {error}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--users", type=int, default=50, help="сколько пользователей одновременно")
    parser.add_argument("--rounds", type=int, default=4, help="сколько поисков делает каждый")
    parser.add_argument("--phone", default="+375293333333")
    parser.add_argument("--password", default="demo12345")
    args = parser.parse_args()

    results, errors = [], []
    start = threading.Event()
    ready = threading.Semaphore(0)
    threads = [threading.Thread(target=user_session, args=(i, args, start, ready, results, errors))
               for i in range(args.users)]
    for thread in threads:
        thread.start()
    for _ in threads:  # ждём, пока все пользователи войдут: вход считает хеш пароля и сам небыстрый
        ready.acquire()
    began = time.perf_counter()
    start.set()
    for thread in threads:
        thread.join()
    total = time.perf_counter() - began

    if not results:
        print("Нет ни одного ответа. Проверьте, что сайт запущен и есть демо-данные.", *errors[:5], sep="\n")
        raise SystemExit(2)
    results.sort()
    p95 = results[min(len(results) - 1, int(len(results) * 0.95))]
    print(f"Пользователей: {args.users}, поисков: {len(results)}, ошибок: {len(errors)}, всего времени: {total:.1f} с")
    print(f"Время ответа поиска, секунды: среднее {statistics.mean(results):.2f}, "
          f"медиана {statistics.median(results):.2f}, 95% {p95:.2f}, максимум {results[-1]:.2f}")
    ok = not errors and p95 <= LIMIT_SECONDS
    print(f"Требование ТЗ: 95% ответов не дольше {LIMIT_SECONDS:.0f} с и без ошибок: {'ВЫПОЛНЕНО' if ok else 'НЕ ВЫПОЛНЕНО'}")
    for error in sorted(set(errors))[:5]:
        print("  ошибка:", error)
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
