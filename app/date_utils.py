from datetime import date, datetime, timedelta, UTC
from zoneinfo import ZoneInfo
import calendar

from holidays import country_holidays


APP_TIMEZONE = ZoneInfo("Europe/Istanbul")


TURKISH_HOLIDAYS_STATIC = {
    (1, 1): "Yılbaşı",
    (4, 23): "Ulusal Egemenlik ve Çocuk Bayramı",
    (5, 1): "Emek ve Dayanışma Günü",
    (5, 19): "Atatürk'ü Anma, Gençlik ve Spor Bayramı",
    (7, 15): "Demokrasi ve Milli Birlik Günü",
    (8, 30): "Zafer Bayramı",
    (10, 29): "Cumhuriyet Bayramı",
}


def get_easter_year(year):
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def get_ramadan_holiday(year):
    easter = get_easter_year(year)
    return easter - timedelta(days=56)


def get_sacrifice_holiday(year):
    easter = get_easter_year(year)
    return easter + timedelta(days=69)


def get_turkish_holidays(year):
    return {
        day: name
        for day, name in country_holidays("TR", years=[year]).items()
    }


def is_holiday(check_date):
    holidays = get_turkish_holidays(check_date.year)
    return check_date in holidays


def get_holiday_name(check_date):
    holidays = get_turkish_holidays(check_date.year)
    return holidays.get(check_date, None)


def is_weekend(check_date):
    return check_date.weekday() >= 5


def is_non_working_day(check_date):
    return is_weekend(check_date) or is_holiday(check_date)


def get_next_working_day(check_date):
    while is_non_working_day(check_date):
        check_date += timedelta(days=1)
    return check_date


def calculate_due_date(year, month, due_day):
    last_day = calendar.monthrange(year, month)[1]
    actual_day = min(due_day, last_day)
    return date(year, month, actual_day)


def calculate_statement_date(year, month, statement_day):
    last_day = calendar.monthrange(year, month)[1]
    actual_day = min(statement_day, last_day)
    return date(year, month, actual_day)


def calculate_statement_date_for_due(due_date, statement_day):
    statement_date = calculate_statement_date(
        due_date.year,
        due_date.month,
        statement_day,
    )
    if statement_date >= due_date:
        previous_month = due_date.month - 1 or 12
        previous_year = due_date.year - 1 if due_date.month == 1 else due_date.year
        statement_date = calculate_statement_date(
            previous_year,
            previous_month,
            statement_day,
        )
    return statement_date


def get_today():
    return datetime.now(APP_TIMEZONE).date()


def get_utc_now():
    return datetime.now(UTC).replace(tzinfo=None)


def get_app_datetime():
    return datetime.now(APP_TIMEZONE)


def days_until(target_date):
    today = get_today()
    delta = target_date - today
    return delta.days


def format_date_tr(d):
    if d is None:
        return ""
    months_tr = [
        "", "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
        "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"
    ]
    return f"{d.day} {months_tr[d.month]} {d.year}"


def format_date_short(d):
    if d is None:
        return ""
    return f"{d.day:02d}.{d.month:02d}.{d.year}"


def get_current_month_payments(cards):
    today = get_today()
    current_month = today.month
    current_year = today.year

    upcoming = []
    for card in cards:
        if not card.is_active:
            continue

        due_date = calculate_due_date(current_year, current_month, card.due_day)

        if due_date < today:
            if current_month == 12:
                due_date = calculate_due_date(current_year + 1, 1, card.due_day)
            else:
                due_date = calculate_due_date(current_year, current_month + 1, card.due_day)

        days_left = days_until(due_date)
        upcoming.append({
            "card": card,
            "due_date": due_date,
            "days_left": days_left,
        })

    upcoming.sort(key=lambda x: x["days_left"])
    return upcoming
