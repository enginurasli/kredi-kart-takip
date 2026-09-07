import os
import sys
import json
import pytest
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models import User, Card, Payment, Notification, Setting
from app.date_utils import (
    is_holiday, is_weekend, is_non_working_day, get_next_working_day,
    format_date_tr, format_date_short, days_until, calculate_due_date
)
from app.notifications import create_payment_notification, dismiss_notification


class TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SECRET_KEY = 'test-secret'


@pytest.fixture
def app():
    app = create_app(config_class=TestConfig)

    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def auth_client(client):
    client.post('/register', data={
        'username': 'testuser',
        'email': 'test@test.com',
        'password': 'test1234',
        'password2': 'test1234'
    }, follow_redirects=True)

    client.post('/login', data={
        'username': 'testuser',
        'password': 'test1234'
    }, follow_redirects=True)

    return client


class TestDateUtils:
    def test_is_weekend_saturday(self):
        sat = date(2026, 8, 22)
        assert is_weekend(sat) is True

    def test_is_weekend_sunday(self):
        sun = date(2026, 8, 23)
        assert is_weekend(sun) is True

    def test_is_weekend_monday(self):
        mon = date(2026, 8, 24)
        assert is_weekend(mon) is False

    def test_is_holiday_national_sovereignty(self):
        holiday = date(2026, 4, 23)
        assert is_holiday(holiday) is True

    def test_is_holiday_not_holiday(self):
        regular = date(2026, 8, 17)
        assert is_holiday(regular) is False

    def test_is_non_working_day_weekend(self):
        sat = date(2026, 8, 22)
        assert is_non_working_day(sat) is True

    def test_is_non_working_day_holiday(self):
        holiday = date(2026, 4, 23)
        assert is_non_working_day(holiday) is True

    def test_get_next_working_day_from_weekend(self):
        sat = date(2026, 8, 22)
        next_day = get_next_working_day(sat)
        assert next_day == date(2026, 8, 24)

    def test_get_next_working_day_from_weekday(self):
        mon = date(2026, 8, 24)
        next_day = get_next_working_day(mon)
        assert next_day == mon

    def test_format_date_tr(self):
        d = date(2026, 8, 25)
        assert format_date_tr(d) == "25 Ağustos 2026"

    def test_format_date_short(self):
        d = date(2026, 8, 25)
        assert format_date_short(d) == "25.08.2026"

    def test_calculate_due_date_normal(self):
        due = calculate_due_date(2026, 8, 25)
        assert due == date(2026, 8, 25)

    def test_calculate_due_date_february_30(self):
        due = calculate_due_date(2026, 2, 30)
        assert due == date(2026, 2, 28)

    def test_days_until_future(self):
        future = date.today() + timedelta(days=5)
        assert days_until(future) == 5

    def test_days_until_past(self):
        past = date.today() - timedelta(days=3)
        assert days_until(past) == -3


class TestAuth:
    def test_register_success(self, client):
        response = client.post('/register', data={
            'username': 'newuser',
            'email': 'new@test.com',
            'password': 'pass1234',
            'password2': 'pass1234'
        }, follow_redirects=True)
        assert response.status_code == 200

    def test_register_password_mismatch(self, client):
        response = client.post('/register', data={
            'username': 'user2',
            'email': 'user2@test.com',
            'password': 'pass1234',
            'password2': 'pass5678'
        }, follow_redirects=True)
        assert response.status_code == 200

    def test_login_success(self, client):
        client.post('/register', data={
            'username': 'logintest',
            'email': 'login@test.com',
            'password': 'test1234',
            'password2': 'test1234'
        }, follow_redirects=True)

        response = client.post('/login', data={
            'username': 'logintest',
            'password': 'test1234'
        }, follow_redirects=True)
        assert response.status_code == 200

    def test_login_wrong_password(self, client):
        client.post('/register', data={
            'username': 'wrongpass',
            'email': 'wrong@test.com',
            'password': 'test1234',
            'password2': 'test1234'
        }, follow_redirects=True)

        response = client.post('/login', data={
            'username': 'wrongpass',
            'password': 'wrongpassword'
        }, follow_redirects=True)
        assert response.status_code == 200

    def test_logout(self, auth_client):
        response = auth_client.get('/logout', follow_redirects=True)
        assert response.status_code == 200


class TestCardCRUD:
    def test_create_card(self, auth_client):
        response = auth_client.post('/api/cards',
            data=json.dumps({
                'bank_name': 'Garanti',
                'card_name': 'Bonus',
                'statement_day': 15,
                'due_day': 25,
                'current_balance': 18750,
                'currency': 'TRY',
                'reminder_days': 2,
                'is_active': True
            }),
            content_type='application/json'
        )
        assert response.status_code == 201
        data = json.loads(response.data)
        assert data['bank_name'] == 'Garanti'
        assert data['card_name'] == 'Bonus'

    def test_get_cards(self, auth_client):
        auth_client.post('/api/cards',
            data=json.dumps({
                'bank_name': 'Yapı Kredi',
                'card_name': 'World',
                'statement_day': 10,
                'due_day': 20,
                'current_balance': 5000,
                'currency': 'TRY',
                'reminder_days': 3
            }),
            content_type='application/json'
        )

        response = auth_client.get('/api/cards')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert len(data) == 1

    def test_update_card(self, auth_client):
        auth_client.post('/api/cards',
            data=json.dumps({
                'bank_name': 'Akbank',
                'card_name': 'Axess',
                'statement_day': 5,
                'due_day': 15,
                'current_balance': 3000,
                'currency': 'TRY',
                'reminder_days': 2
            }),
            content_type='application/json'
        )

        response = auth_client.put('/api/cards/1',
            data=json.dumps({
                'current_balance': 4500,
                'card_name': 'Axess Platinum'
            }),
            content_type='application/json'
        )
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['current_balance'] == 4500
        assert data['card_name'] == 'Axess Platinum'

    def test_delete_card(self, auth_client):
        auth_client.post('/api/cards',
            data=json.dumps({
                'bank_name': 'İş Bankası',
                'card_name': 'Maximum',
                'statement_day': 1,
                'due_day': 10,
                'current_balance': 2000,
                'currency': 'TRY',
                'reminder_days': 2
            }),
            content_type='application/json'
        )

        response = auth_client.delete('/api/cards/1')
        assert response.status_code == 200

        response = auth_client.get('/api/cards')
        data = json.loads(response.data)
        assert len(data) == 0


class TestPayments:
    def test_mark_paid(self, auth_client):
        auth_client.post('/api/cards',
            data=json.dumps({
                'bank_name': 'QNB',
                'card_name': 'Finans',
                'statement_day': 10,
                'due_day': 20,
                'current_balance': 7500,
                'currency': 'TRY',
                'reminder_days': 2
            }),
            content_type='application/json'
        )

        auth_client.get('/api/payments/upcoming')

        response = auth_client.post('/api/payments/1/paid')
        assert response.status_code == 200

        data = json.loads(response.data)
        assert data['is_paid'] is True


class TestNotifications:
    def test_notification_creation(self, app):
        with app.app_context():
            user = User(username='notifuser', email='notif@test.com')
            user.set_password('test1234')
            db.session.add(user)
            db.session.commit()

            card = Card(
                user_id=user.id,
                bank_name='Test Bank',
                card_name='Test Card',
                statement_day=15,
                due_day=25,
                current_balance=10000,
                currency='TRY',
                reminder_days=2
            )
            db.session.add(card)
            db.session.commit()

            due_date = date.today() + timedelta(days=5)
            payment = Payment(
                card_id=card.id,
                amount=10000,
                currency='TRY',
                due_date=due_date,
                statement_date=due_date - timedelta(days=10),
                month=due_date.month,
                year=due_date.year
            )
            db.session.add(payment)
            db.session.commit()

            notif = create_payment_notification(payment, reminder_days=2)
            assert notif is not None
            assert notif.status == 'pending'

    def test_no_duplicate_notification(self, app):
        with app.app_context():
            user = User(username='dupuser', email='dup@test.com')
            user.set_password('test1234')
            db.session.add(user)
            db.session.commit()

            card = Card(
                user_id=user.id,
                bank_name='Test Bank',
                card_name='Test Card',
                statement_day=15,
                due_day=25,
                current_balance=10000,
                currency='TRY',
                reminder_days=2
            )
            db.session.add(card)
            db.session.commit()

            due_date = date.today() + timedelta(days=5)
            payment = Payment(
                card_id=card.id,
                amount=10000,
                currency='TRY',
                due_date=due_date,
                statement_date=due_date - timedelta(days=10),
                month=due_date.month,
                year=due_date.year
            )
            db.session.add(payment)
            db.session.commit()

            notif1 = create_payment_notification(payment, reminder_days=2)
            notif2 = create_payment_notification(payment, reminder_days=2)

            assert notif1 is not None
            assert notif2 is None

    def test_dismiss_notification(self, app):
        with app.app_context():
            user = User(username='dismissuser', email='dismiss@test.com')
            user.set_password('test1234')
            db.session.add(user)
            db.session.commit()

            card = Card(
                user_id=user.id,
                bank_name='Test Bank',
                card_name='Test Card',
                statement_day=15,
                due_day=25,
                current_balance=10000,
                currency='TRY',
                reminder_days=2
            )
            db.session.add(card)
            db.session.commit()

            due_date = date.today() + timedelta(days=5)
            payment = Payment(
                card_id=card.id,
                amount=10000,
                currency='TRY',
                due_date=due_date,
                statement_date=due_date - timedelta(days=10),
                month=due_date.month,
                year=due_date.year
            )
            db.session.add(payment)
            db.session.commit()

            notif = create_payment_notification(payment, reminder_days=2)
            assert notif is not None

            result = dismiss_notification(notif.id, user.id)
            assert result is True

            updated = db.session.get(Notification, notif.id)
            assert updated.status == 'dismissed'
            assert updated.dismissed_at is not None


class TestAPIEndpoints:
    def test_dashboard(self, auth_client):
        response = auth_client.get('/api/dashboard')
        assert response.status_code == 200

    def test_upcoming_payments(self, auth_client):
        response = auth_client.get('/api/payments/upcoming')
        assert response.status_code == 200

    def test_settings_get(self, auth_client):
        response = auth_client.get('/api/settings')
        assert response.status_code == 200

    def test_settings_update(self, auth_client):
        response = auth_client.put('/api/settings',
            data=json.dumps({
                'notifications_enabled': False,
                'default_reminder_days': 5
            }),
            content_type='application/json'
        )
        assert response.status_code == 200


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
