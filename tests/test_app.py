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
from app.auth import _issue_reset_token
from app.date_utils import get_utc_now


class TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SECRET_KEY = 'test-secret'
    ENABLE_SCHEDULER = False
    TRUST_PROXY = False


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
        response = auth_client.post('/logout', follow_redirects=True)
        assert response.status_code == 200


    def test_password_reset_flow(self, app, client):
        client.post('/register', data={
            'username': 'resetuser',
            'email': 'reset@test.com',
            'password': 'oldpass123',
            'password2': 'oldpass123'
        }, follow_redirects=True)

        with app.app_context():
            user = User.query.filter_by(username='resetuser').first()
            token = _issue_reset_token(user)
            db.session.commit()

        response = client.post(f'/reset-password/{token}', data={
            'password': 'newpass123',
            'password2': 'newpass123'
        }, follow_redirects=True)
        assert response.status_code == 200

        client.post('/logout', follow_redirects=True)
        client.post('/login', data={
            'username': 'resetuser',
            'password': 'newpass123'
        }, follow_redirects=True)
        assert b'Hesab\xc4\xb1n\xc4\xb1z' in client.get('/').data or client.get('/').status_code == 200

    def test_forgot_password_sends_neutral_response(self, app, client):
        """Kullanıcı var/yok bilgisi sızdırılmamalı."""
        client.post('/register', data={
            'username': 'resetuser3',
            'email': 'reset3@test.com',
            'password': 'oldpass123',
            'password2': 'oldpass123'
        }, follow_redirects=True)

        valid = client.post('/forgot-password', data={
            'username': 'resetuser3',
            'email': 'reset3@test.com'
        }, follow_redirects=True)
        invalid = client.post('/forgot-password', data={
            'username': 'resetuser3',
            'email': 'yanlis@test.com'
        }, follow_redirects=True)
        unknown = client.post('/forgot-password', data={
            'username': 'yokboyle',
            'email': 'yok@test.com'
        }, follow_redirects=True)

        valid_text = valid.data.decode('utf-8')
        invalid_text = invalid.data.decode('utf-8')
        unknown_text = unknown.data.decode('utf-8')
        marker = 'sıfırlama bağlantısı e-postanıza gönderildi'

        assert marker in valid_text
        assert marker in invalid_text
        assert marker in unknown_text
        # Üç yanıt da aynı olmalı; "eşleşmiyor" gibi ipucu vermemeli.
        for response_text in (valid_text, invalid_text, unknown_text):
            assert 'eşleşmiyor' not in response_text
            assert 'bulunamadı' not in response_text

    def test_reset_token_is_required(self, app, client):
        """E-posta doğrulaması olmadan sıfırlama yapılamaz."""
        client.post('/register', data={
            'username': 'resetuser4',
            'email': 'reset4@test.com',
            'password': 'oldpass123',
            'password2': 'oldpass123'
        }, follow_redirects=True)

        response = client.post('/forgot-password', data={
            'username': 'resetuser4',
            'email': 'reset4@test.com'
        }, follow_redirects=True)
        assert response.status_code == 200

        # Oturum bilgisi olmadan doğrudan sıfırlama denemesi reddedilmeli.
        response = client.post('/reset-password/guesser-token', data={
            'password': 'hacked123',
            'password2': 'hacked123'
        }, follow_redirects=True)
        assert b'ge\xc3\xa7ersiz' in response.data

        with app.app_context():
            user = User.query.filter_by(username='resetuser4').first()
            assert user.check_password('oldpass123')

    def test_reset_token_is_single_use(self, app, client):
        client.post('/register', data={
            'username': 'resetuser5',
            'email': 'reset5@test.com',
            'password': 'oldpass123',
            'password2': 'oldpass123'
        }, follow_redirects=True)

        with app.app_context():
            user = User.query.filter_by(username='resetuser5').first()
            token = _issue_reset_token(user)
            db.session.commit()

        client.post(f'/reset-password/{token}', data={
            'password': 'firstpass123',
            'password2': 'firstpass123'
        }, follow_redirects=True)

        # Aynı token ikinci kez kullanılamamalı.
        response = client.post(f'/reset-password/{token}', data={
            'password': 'secondpass123',
            'password2': 'secondpass123'
        }, follow_redirects=True)
        assert b'ge\xc3\xa7ersiz' in response.data

        with app.app_context():
            user = User.query.filter_by(username='resetuser5').first()
            assert user.check_password('firstpass123')

    def test_expired_token_is_rejected(self, app, client):
        client.post('/register', data={
            'username': 'resetuser6',
            'email': 'reset6@test.com',
            'password': 'oldpass123',
            'password2': 'oldpass123'
        }, follow_redirects=True)

        with app.app_context():
            user = User.query.filter_by(username='resetuser6').first()
            token = _issue_reset_token(user)
            user.reset_token_expires_at = get_utc_now().timestamp() - 10
            db.session.commit()

        response = client.post(f'/reset-password/{token}', data={
            'password': 'expiredpass1',
            'password2': 'expiredpass1'
        }, follow_redirects=True)
        assert b'ge\xc3\xa7ersiz' in response.data


class TestOpenRedirect:
    def test_next_parameter_rejects_external_host(self, client):
        client.post('/register', data={
            'username': 'redir', 'email': 'redir@test.com',
            'password': 'pass1234', 'password2': 'pass1234'
        }, follow_redirects=True)

        response = client.post('/login?next=//evil.com/steal', data={
            'username': 'redir', 'password': 'pass1234'
        })
        assert response.status_code == 302
        assert 'evil.com' not in response.headers['Location']

        response = client.post('/login?next=https://evil.com/steal', data={
            'username': 'redir', 'password': 'pass1234'
        })
        assert 'evil.com' not in response.headers['Location']

    def test_next_parameter_allows_internal_path(self, client):
        client.post('/register', data={
            'username': 'redir2', 'email': 'redir2@test.com',
            'password': 'pass1234', 'password2': 'pass1234'
        }, follow_redirects=True)
        response = client.post('/login?next=/cards', data={
            'username': 'redir2', 'password': 'pass1234'
        })
        assert response.status_code == 302
        assert response.headers['Location'].endswith('/cards')


class TestLogoutIsPostOnly:
    def test_get_logout_is_rejected(self, auth_client):
        response = auth_client.get('/logout')
        assert response.status_code == 405

    def test_post_logout_ends_session(self, auth_client):
        response = auth_client.post('/logout', follow_redirects=True)
        assert response.status_code == 200
        response = auth_client.get('/api/cards')
        assert response.status_code == 401


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

            # Aynı satır bulunur; yeniden üretilmez, mevcut kayıt tazelenir.
            assert notif1 is not None
            assert notif2 is not None
            assert notif1.id == notif2.id
            assert db.session.get(Notification, notif1.id) is not None
            assert Notification.query.count() == 1

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


def add_card(client, due_day=20, balance=1000, reminder_days=2, currency='TRY',
             card_name='Bonus', **extra):
    payload = {
        'bank_name': 'Garanti',
        'card_name': card_name,
        'statement_day': 5,
        'due_day': due_day,
        'current_balance': balance,
        'currency': currency,
        'reminder_days': reminder_days,
    }
    payload.update(extra)
    response = client.post('/api/cards', data=json.dumps(payload), content_type='application/json')
    assert response.status_code == 201
    return response.get_json()


class TestDashboardCounts:
    """KOD2: unpaid_count / next_payment / toplam doğru hesaplanmalı."""

    def test_unpaid_count_counts_unpaid_only(self, auth_client):
        for due_day in (10, 15, 20, 25, 30):
            add_card(auth_client, due_day=due_day)

        dashboard = auth_client.get('/api/dashboard').get_json()
        assert dashboard['unpaid_count'] == 5
        assert dashboard['total_month'] == 5000.0

        upcoming = auth_client.get('/api/payments/upcoming').get_json()
        auth_client.post(f"/api/payments/{upcoming[0]['payment_id']}/paid")

        dashboard = auth_client.get('/api/dashboard').get_json()
        assert dashboard['unpaid_count'] == 4
        assert dashboard['total_month'] == 4000.0

    def test_paid_card_is_not_next_payment(self, auth_client):
        add_card(auth_client, due_day=30, card_name='Yakindaki')
        add_card(auth_client, due_day=10, card_name='Uzaktaki')

        upcoming = auth_client.get('/api/payments/upcoming').get_json()
        nearest = upcoming[0]
        auth_client.post(f"/api/payments/{nearest['payment_id']}/paid")

        dashboard = auth_client.get('/api/dashboard').get_json()
        assert dashboard['unpaid_count'] == 1
        assert dashboard['next_payment']['card_name'] == 'Garanti Uzaktaki'

    def test_all_paid_clears_next_payment(self, auth_client):
        add_card(auth_client)
        for item in auth_client.get('/api/payments/upcoming').get_json():
            auth_client.post(f"/api/payments/{item['payment_id']}/paid")

        dashboard = auth_client.get('/api/dashboard').get_json()
        assert dashboard['unpaid_count'] == 0
        assert dashboard['next_payment'] is None
        assert dashboard['total_month'] == 0.0


class TestPaymentsListing:
    """KOD3: Ödemeler sayfası vade tarihine göre listelenmeli, ay bazlı boş kalmamalı."""

    def test_payments_list_not_empty_for_rolled_over_cards(self, auth_client):
        # due_day bu ayın içinde geçmiş -> vade bir sonraki aya kayar
        for due_day in (1, 10, 15):
            add_card(auth_client, due_day=due_day)

        payments = auth_client.get('/api/payments').get_json()
        assert len(payments) > 0

        upcoming_names = {i['card_name'] for i in auth_client.get('/api/payments/upcoming').get_json()}
        listed_names = {p['card_name'] for p in payments}
        assert upcoming_names.issubset(listed_names)

    def test_payments_include_paid_with_badge(self, auth_client):
        add_card(auth_client)
        upcoming = auth_client.get('/api/payments/upcoming').get_json()
        auth_client.post(f"/api/payments/{upcoming[0]['payment_id']}/paid")

        payments = auth_client.get('/api/payments').get_json()
        assert any(p['is_paid'] for p in payments)

    def test_payments_sorted_by_due_date(self, auth_client):
        for due_day in (5, 25, 15):
            add_card(auth_client, due_day=due_day)

        payments = auth_client.get('/api/payments').get_json()
        due_dates = [p['due_date'] for p in payments]
        assert due_dates == sorted(due_dates)


class TestPaymentSync:
    """KOD4: Ödeme kaydı kartın güncel bakiyesi ve para birimini yansıtmalı."""

    def test_balance_update_syncs_unpaid_payment(self, app, auth_client):
        add_card(auth_client, balance=500)
        with app.app_context():
            payment = Payment.query.filter_by(is_paid=False).first()
            payment_id = payment.id
            assert payment.amount == 500.0

        auth_client.put('/api/cards/1',
            data=json.dumps({'current_balance': 9999}),
            content_type='application/json')

        with app.app_context():
            assert db.session.get(Payment, payment_id).amount == 9999.0

    def test_currency_update_syncs_unpaid_payment(self, app, auth_client):
        add_card(auth_client, currency='TRY')
        auth_client.put('/api/cards/1',
            data=json.dumps({'currency': 'USD'}),
            content_type='application/json')

        with app.app_context():
            payments = Payment.query.filter_by(is_paid=False).all()
            assert payments
            assert all(p.currency == 'USD' for p in payments)

    def test_paid_payment_amount_is_never_overwritten(self, app, auth_client):
        add_card(auth_client, balance=500)
        upcoming = auth_client.get('/api/payments/upcoming').get_json()
        paid_id = upcoming[0]['payment_id']
        auth_client.post(f"/api/payments/{paid_id}/paid")

        auth_client.put('/api/cards/1',
            data=json.dumps({'current_balance': 3000}),
            content_type='application/json')

        with app.app_context():
            assert db.session.get(Payment, paid_id).amount == 500.0

    def test_notification_message_refreshes_on_update(self, app, auth_client):
        add_card(auth_client, balance=500)
        with app.app_context():
            before = Notification.query.filter_by(status='pending').first().message
            assert '500.00' in before

        auth_client.put('/api/cards/1',
            data=json.dumps({'current_balance': 2500}),
            content_type='application/json')

        with app.app_context():
            after = Notification.query.filter_by(status='pending').first().message
            assert '2,500.00' in after


class TestReminderLifecycle:
    """KOD1/KOD5: Ödeme kaydı bildirim tercihinden bağımsız; tek canlı hatırlatma."""

    def test_payments_created_even_when_notifications_disabled(self, app, auth_client):
        auth_client.put('/api/settings',
            data=json.dumps({'notifications_enabled': False}),
            content_type='application/json')

        add_card(auth_client)

        with app.app_context():
            assert Payment.query.count() > 0
            assert Notification.query.count() == 0

        upcoming = auth_client.get('/api/payments/upcoming').get_json()
        assert upcoming
        assert upcoming[0]['payment_id'] is not None

    def test_reenabling_notifications_creates_reminders(self, app, auth_client):
        auth_client.put('/api/settings',
            data=json.dumps({'notifications_enabled': False}),
            content_type='application/json')
        add_card(auth_client)
        auth_client.put('/api/settings',
            data=json.dumps({'notifications_enabled': True}),
            content_type='application/json')

        from app.notifications import generate_notifications_for_upcoming_payments
        with app.app_context():
            generate_notifications_for_upcoming_payments(1)
            assert Notification.query.filter_by(status='pending').count() > 0

    def test_changing_reminder_days_cancels_old_reminder(self, app, auth_client):
        add_card(auth_client, reminder_days=2)
        with app.app_context():
            assert Notification.query.filter_by(reminder_type='2_days').count() > 0

        auth_client.put('/api/cards/1',
            data=json.dumps({'reminder_days': 7}),
            content_type='application/json')

        with app.app_context():
            assert Notification.query.filter_by(
                reminder_type='2_days', status='pending').count() == 0
            assert Notification.query.filter_by(
                reminder_type='7_days', status='pending').count() > 0

    def test_exactly_one_pending_reminder_per_payment(self, app, auth_client):
        add_card(auth_client, reminder_days=2)
        auth_client.put('/api/cards/1',
            data=json.dumps({'reminder_days': 9}),
            content_type='application/json')
        auth_client.put('/api/cards/1',
            data=json.dumps({'reminder_days': 3}),
            content_type='application/json')

        with app.app_context():
            pending = Notification.query.filter_by(status='pending').all()
            payment_ids = [n.payment_id for n in pending]
            assert len(payment_ids) == len(set(payment_ids))


class TestTemplateScripts:
    """KOD0: Şablon içi JS tekrarı hata üretmemeli."""

    def _inline_scripts(self, name):
        import re
        import pathlib
        path = pathlib.Path(__file__).resolve().parent.parent / 'app' / 'templates' / name
        source = path.read_text(encoding='utf-8')
        scripts = re.findall(r'<script>(.*?)</script>', source, re.S)
        return [s for s in scripts if 'const' in s or 'function' in s]

    def test_no_duplicate_declarations(self):
        import re
        for template in ('dashboard.html', 'cards.html', 'card_detail.html',
                         'card_form.html', 'payments.html', 'settings.html',
                         'notifications.html'):
            for script in self._inline_scripts(template):
                code = re.sub(r'\{\{.*?\}\}', 'null', script)
                # Tarayıcı kapsam kurallarına uygun: fonksiyon gövdeleri
                # ayrı blok kapsamıdır, aynı isim farklı fonksiyonda kullanılabilir.
                blocks = re.split(r'\bfunction\b|=>\s*\{', code)
                for block in blocks:
                    for name in set(re.findall(r'\bconst\s+([A-Za-z_$][\w$]*)\s*=', block)):
                        count = len(re.findall(r'\bconst\s+' + re.escape(name) + r'\s*=', block))
                        assert count == 1, (
                            f"{template}: '{name}' ayni blok kapsaminda {count} kez const ile tanimli"
                        )

    def test_dashboard_loads_dashboard_once(self):
        for script in self._inline_scripts('dashboard.html'):
            assert script.count("fetchJson('/api/dashboard')") <= 1, (
                "dashboard.html /api/dashboard'i birden fazla kez cekiyor"
            )

    def test_dashboard_page_renders(self, auth_client):
        response = auth_client.get('/')
        assert response.status_code == 200
        assert b'loadDashboard' in response.data

    def test_service_worker_served_without_caching(self, client):
        """Render yeniden deploy edince telefon eski sürümde kalmasın."""
        response = client.get('/sw.js')
        assert response.status_code == 200
        assert 'javascript' in response.headers['Content-Type']
        assert 'no-cache' in response.headers.get('Cache-Control', ''), (
            "sw.js no-cache olmazsa tarayıcı yeni service worker'i hiç indirmez"
        )


def _read_png(path):
    """PNG'yi bağımlılıksız okur; alfa kanalı dahil RGBA piksel döner."""
    import struct
    import zlib

    data = path.read_bytes()
    assert data[:8] == b'\x89PNG\r\n\x1a\n', f'{path.name}: PNG imzasi gecersiz'
    pos, idat, ihdr = 8, b'', None
    while pos < len(data):
        length = struct.unpack('>I', data[pos:pos + 4])[0]
        chunk_type = data[pos + 4:pos + 8]
        chunk_data = data[pos + 8:pos + 8 + length]
        if chunk_type == b'IHDR':
            ihdr = struct.unpack('>IIBBBBB', chunk_data)
        elif chunk_type == b'IDAT':
            idat += chunk_data
        pos += 12 + length

    width, height, depth, color_type = ihdr[0], ihdr[1], ihdr[2], ihdr[3]
    assert depth == 8 and color_type == 6, f'{path.name}: 8-bit RGBA degil'

    raw = zlib.decompress(idat)
    stride = width * 4
    rows, prev, i = [], bytearray(stride), 0
    for _ in range(height):
        filt = raw[i]
        i += 1
        line = bytearray(raw[i:i + stride])
        i += stride
        for x in range(stride):
            a = line[x - 4] if x >= 4 else 0
            b = prev[x]
            c = prev[x - 4] if x >= 4 else 0
            if filt == 1:
                line[x] = (line[x] + a) & 255
            elif filt == 2:
                line[x] = (line[x] + b) & 255
            elif filt == 3:
                line[x] = (line[x] + (a + b) // 2) & 255
            elif filt == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[x] = (line[x] + pred) & 255
        prev = line
        rows.append([tuple(line[x * 4:x * 4 + 4]) for x in range(width)])
    return width, height, rows


class TestAppIcons:
    """KOD13: PWA ikonlari gercek bir cizim olmali, tek renk kare degil."""

    @staticmethod
    def _icon_dir():
        import pathlib
        return pathlib.Path(__file__).resolve().parent.parent / 'app' / 'static' / 'icons'

    def test_icons_are_valid_rgba_png(self):
        for name in ('icon-192', 'icon-512'):
            path = self._icon_dir() / f'{name}.png'
            assert path.exists(), f'{name}.png eksik'
            width, height, pixels = _read_png(path)
            assert (width, height) == (int(name.split('-')[1]),) * 2
            assert pixels[0][0][3] == 0, f'{name}.png kose saydam olmali'

    def test_icons_are_not_flat_squares(self):
        """Eski ikon tek renk kareydi; simdi farkli renkler icermeli."""
        for name in ('icon-192', 'icon-512'):
            _, _, pixels = _read_png(self._icon_dir() / f'{name}.png')
            colors = {p[:3] for row in pixels for p in row if p[3] > 200}
            assert len(colors) > 20, (
                f'{name}.png sadece {len(colors)} renk iceriyor; '
                'tek renk kare uretilmis olabilir'
            )

    def test_card_elements_present(self):
        """Manyetik serit, cip ve beyaz detay cizilmis olmali."""
        _, _, pixels = _read_png(self._icon_dir() / 'icon-192.png')
        stripe = sum(
            1 for row in pixels for p in row
            if p[3] > 200 and abs(p[0] - 232) < 9 and abs(p[1] - 234) < 9
            and abs(p[2] - 237) < 9
        )
        chip = sum(
            1 for row in pixels for p in row
            if p[3] > 200 and 195 < p[0] < 252 and p[1] > 155 and p[2] < 150
        )
        white = sum(
            1 for row in pixels for p in row
            if p[3] > 200 and p[0] > 245 and p[1] > 245 and p[2] > 245
        )
        assert stripe > 200, f'manyetik serit yok ({stripe} piksel)'
        assert chip > 100, f'cip yok ({chip} piksel)'
        assert white > 20, f'beyaz detay yok ({white} piksel)'

    def test_maskable_icons_are_fully_opaque(self):
        """Android maskesi saydam koseyi kirpar; maske ikonu dolu olmali."""
        for name in ('icon-maskable-192', 'icon-maskable-512'):
            path = self._icon_dir() / f'{name}.png'
            assert path.exists(), f'{name}.png eksik'
            width, _, pixels = _read_png(path)
            assert pixels[0][0][3] == 255, f'{name}.png kose saydam'
            opaque = sum(1 for row in pixels for p in row if p[3] > 200)
            assert opaque == width * width, f'{name}.png tam kapali degil'

    @staticmethod
    def _relative_luminance(color):
        def channel(value):
            value /= 255
            if value <= 0.03928:
                return value / 12.92
            return ((value + 0.055) / 1.055) ** 2.4
        return (
            0.2126 * channel(color[0])
            + 0.7152 * channel(color[1])
            + 0.0722 * channel(color[2])
        )

    @classmethod
    def _contrast(cls, first, second):
        lum_a = cls._relative_luminance(first)
        lum_b = cls._relative_luminance(second)
        hi, lo = max(lum_a, lum_b), min(lum_a, lum_b)
        return (hi + 0.05) / (lo + 0.05)

    def test_maskable_card_is_visible_against_its_background(self):
        """KOD14: maske ikonunda kart zeminde kaybolmamali.

        Zemin mavi oldugu icin kart once de maviydi ve ikon duz bir mavi
        kareye donusuyordu. Kart ile zemin kontrasti en az 1.6 olmali.
        """
        for name in ('icon-maskable-192', 'icon-maskable-512'):
            width, height, pixels = _read_png(self._icon_dir() / f'{name}.png')
            background = pixels[2][2][:3]
            # Kart govdesinin sol-alt bolgesi: serit ve cip bu alanda degil.
            card = pixels[int(height * 0.70)][int(width * 0.50)][:3]
            ratio = self._contrast(card, background)
            assert ratio >= 1.6, (
                f'{name}.png kart zeminde kayboluyor: kontrast {ratio:.2f}:1 '
                f'(kart {card}, zemin {background})'
            )

    def test_maskable_details_contrast_with_card(self):
        """Serit, cip ve beyaz detay kart uzerinde okunabilir olmali."""
        for name in ('icon-maskable-192', 'icon-maskable-512'):
            width, height, pixels = _read_png(self._icon_dir() / f'{name}.png')
            card = pixels[int(height * 0.70)][int(width * 0.50)][:3]

            def most_common(predicate):
                counts = {}
                for row in pixels:
                    for p in row:
                        if p[3] > 200 and predicate(p):
                            counts[p[:3]] = counts.get(p[:3], 0) + 1
                assert counts, f'{name}.png beklenen detay bulunamadi'
                return max(counts, key=counts.get)

            stripe = most_common(
                lambda p: abs(p[0] - 232) < 10 and abs(p[1] - 234) < 10
                and abs(p[2] - 237) < 10
            )
            chip = most_common(lambda p: 195 < p[0] < 252 and p[1] > 155 and p[2] < 150)
            white = most_common(lambda p: min(p) > 245)

            for label, color, minimum in (
                ('serit', stripe, 3.0),
                ('cip', chip, 2.0),
                ('beyaz', white, 3.0),
            ):
                ratio = self._contrast(color, card)
                assert ratio >= minimum, (
                    f'{name}.png {label} kart uzerinde okunmuyor: {ratio:.2f}:1'
                )

    def test_maskable_content_inside_safe_zone(self):
        """Guvenli alan disindaki icerik Android maskesinde kirpilir."""
        for name in ('icon-maskable-192', 'icon-maskable-512'):
            width, _, pixels = _read_png(self._icon_dir() / f'{name}.png')
            center = (width - 1) / 2
            safe_radius_sq = (min(width, width) * 0.4) ** 2
            inside = 0
            for y, row in enumerate(pixels):
                for x, p in enumerate(row):
                    if p[3] > 200 and (x - center) ** 2 + (y - center) ** 2 <= safe_radius_sq:
                        inside += 1
            assert inside / (width * width) > 0.15, (
                f'{name}.png guvenli alanda yeterli icerik yok '
                f'({inside / (width * width):.1%})'
            )

    def test_manifest_declares_both_purposes(self, client):
        import json as json_module
        response = client.get('/static/manifest.json')
        assert response.status_code == 200
        manifest = json_module.loads(response.data)
        purposes = {icon.get('purpose') for icon in manifest['icons']}
        assert 'any' in purposes, 'manifest any ikonu icermiyor'
        assert 'maskable' in purposes, 'manifest maskable ikonu icermiyor'
        for icon in manifest['icons']:
            src = icon['src']
            assert src.startswith('/static/'), f"manifest yolu beklenmedik: {src}"
            path = self._icon_dir().parent / src[len('/static/'):]
            assert path.exists(), f"manifest ikonu eksik: {src}"


class TestServiceWorkerStaleness:
    """KOD10: Eski service worker yeni kodun görünmesini engellemesin."""

    @staticmethod
    def _sw_source():
        import pathlib
        path = pathlib.Path(__file__).resolve().parent.parent / 'app' / 'static' / 'js' / 'sw.js'
        return path.read_text(encoding='utf-8')

    @staticmethod
    def _app_source():
        import pathlib
        path = pathlib.Path(__file__).resolve().parent.parent / 'app' / 'static' / 'js' / 'app.js'
        return path.read_text(encoding='utf-8')

    def test_cache_name_bumped(self):
        """Cache adı değişmeden eski varlıklar temizlenmez."""
        import re
        source = self._sw_source()
        match = re.search(r"CACHE_NAME\s*=\s*'([^']+)'", source)
        assert match, 'CACHE_NAME tanimli degil'
        assert match.group(1) == 'kart-takip-v5', (
            f"Cache adi {match.group(1)}; varliklarin yenilenmesi icin artirilmali"
        )

    def test_install_calls_skip_waiting(self):
        install_block = self._sw_source().split("addEventListener('install'")[1]
        assert 'skipWaiting' in install_block.split("addEventListener('activate'")[0], (
            'install icinde skipWaiting yok; yeni SW beklemede kalir'
        )

    def test_static_assets_prefer_network(self):
        """Static varliklar onbellekten sunulmamali, aksi halde eski JS kalir."""
        source = self._sw_source()
        static_handler = source.split('if (isStaticAsset(url)) {')[1]
        # İlk dönüş ağdan gelen yanıt olmalı; önbellek yalnızca ağ başarısızsa.
        assert 'const network = await fetch(request);' in static_handler
        assert 'if (cached) return cached;' in static_handler
        assert static_handler.index('const network = await fetch(request);') < \
            static_handler.index('if (cached) return cached;')

    def test_activate_claims_clients(self):
        activate_block = self._sw_source().split("addEventListener('activate'")[1]
        assert 'clients.claim' in activate_block, (
            'activate icinde clients.claim yok; acik sekmeler yeni SW ile baglanmaz'
        )

    def test_app_reloads_on_controller_change(self):
        source = self._app_source()
        assert "addEventListener('controllerchange'" in source, (
            'controllerchange dinleyicisi yok; eski sayfa yeni kodla baglanmaz'
        )
        assert 'window.location.reload()' in source

    def test_app_checks_for_updates_on_load(self):
        source = self._app_source()
        assert 'reg.update()' in source, (
            'reg.update() cagrisi yok; acik sekme yeni surumu kontrol etmez'
        )


class TestPushKeyDurability:
    """KOD7: VAPID anahtarı ortam değişkeninden okunabilmeli (kalıcı disk yok)."""

    def test_env_keys_take_precedence(self, monkeypatch):
        from py_vapid import Vapid
        import app.vapid_keys as vapid_keys

        vapid = Vapid()
        vapid.generate_keys()
        monkeypatch.setenv("VAPID_PRIVATE_KEY", vapid.private_pem().decode())
        monkeypatch.setenv("VAPID_PUBLIC_KEY", "env-public-key")

        keys = vapid_keys.get_vapid_keys()
        assert keys["public_key"] == "env-public-key"

    def test_der_key_derives_from_env(self, monkeypatch):
        from py_vapid import Vapid
        import app.vapid_keys as vapid_keys

        vapid = Vapid()
        vapid.generate_keys()
        monkeypatch.setenv("VAPID_PRIVATE_KEY", vapid.private_pem().decode())
        monkeypatch.setenv("VAPID_PUBLIC_KEY", "env-public-key")
        monkeypatch.delenv("VAPID_PRIVATE_KEY_DER_B64", raising=False)

        der_b64 = vapid_keys.get_private_key_der_b64()
        # py_vapid bu biçimi imzalama için kabul etmeli.
        Vapid.from_string(private_key=der_b64)

    def test_scheduler_enabled_by_default(self):
        import config
        assert config.Config.ENABLE_SCHEDULER is True

    def test_scheduler_can_be_disabled(self, monkeypatch):
        monkeypatch.setenv("ENABLE_SCHEDULER", "false")
        import importlib
        import config
        importlib.reload(config)
        try:
            assert config.Config.ENABLE_SCHEDULER is False
        finally:
            monkeypatch.delenv("ENABLE_SCHEDULER")
            importlib.reload(config)


class TestVapidKeyPersistence:
    """KOD12: VAPID anahtari disk degil veritabaninda saklanmali.

    Render her deploy'da dosya sistemini sifirladigi icin diskteki anahtar
    kaybolur ve telefondaki push abonelikleri gecersizlesir.
    """

    @pytest.fixture
    def clean_vapid(self, app, monkeypatch):
        import app.vapid_keys as vapid_keys
        monkeypatch.delenv("VAPID_PRIVATE_KEY", raising=False)
        monkeypatch.delenv("VAPID_PUBLIC_KEY", raising=False)
        monkeypatch.delenv("VAPID_PRIVATE_KEY_DER_B64", raising=False)
        monkeypatch.setattr(vapid_keys, "_cached_keys", None, raising=False)
        monkeypatch.setattr(vapid_keys, "KEYS_FILE", "/nonexistent/vapid_keys.json")
        yield
        monkeypatch.setattr(vapid_keys, "_cached_keys", None, raising=False)

    def test_generated_key_is_stored_in_database(self, app, clean_vapid):
        import app.vapid_keys as vapid_keys
        from app.models import AppSetting

        keys = vapid_keys.get_vapid_keys()
        assert keys.get("private_key") and keys.get("public_key")

        row = AppSetting.query.filter_by(key="vapid_keys").first()
        assert row is not None, 'VAPID anahtari veritabanina yazilmadi'
        assert keys["public_key"] in row.value

    def test_key_survives_cache_reset(self, app, clean_vapid):
        """Yeni surec (restart) ayni anahtari okumali."""
        import app.vapid_keys as vapid_keys

        first = vapid_keys.get_vapid_keys()["public_key"]
        vapid_keys._cached_keys = None
        second = vapid_keys.get_vapid_keys()["public_key"]
        assert first == second, 'Restart sonrasi VAPID anahtari degisti'

    def test_database_key_wins_over_disk(self, app, clean_vapid, monkeypatch):
        import json

        import app.vapid_keys as vapid_keys
        from app.models import AppSetting

        vapid_keys._save_keys_to_db({
            "private_key": "db-private",
            "public_key": "db-public",
        })
        # Diskte farkli bir anahtar olsa da veritabani oncelikli olmali.
        monkeypatch.setattr(
            vapid_keys, "_load_keys",
            lambda: {"private_key": "disk-private", "public_key": "disk-public"},
        )
        vapid_keys._cached_keys = None

        keys = vapid_keys.get_vapid_keys()
        assert keys["public_key"] == "db-public"
        assert AppSetting.query.filter_by(key="vapid_keys").first() is not None
        assert json.loads(AppSetting.query.first().value)["public_key"] == "db-public"

    def test_env_key_not_persisted_to_database(self, app, clean_vapid, monkeypatch):
        """Ortam anahtari varsa veritabanina yazilmaz; kaynak ortamda kalir."""
        import app.vapid_keys as vapid_keys
        from app.models import AppSetting

        monkeypatch.setenv("VAPID_PRIVATE_KEY", "env-private")
        monkeypatch.setenv("VAPID_PUBLIC_KEY", "env-public")

        keys = vapid_keys.get_vapid_keys()
        assert keys["public_key"] == "env-public"
        assert AppSetting.query.filter_by(key="vapid_keys").first() is None

    def test_corrupt_database_value_is_ignored(self, app, clean_vapid):
        import app.vapid_keys as vapid_keys
        from app.models import AppSetting

        db.session.add(AppSetting(key="vapid_keys", value="{bozuk json"))
        db.session.commit()
        vapid_keys._cached_keys = None

        keys = vapid_keys.get_vapid_keys()
        assert keys.get("public_key"), 'Bozuk kayit yeni anahtar uretmeyi engellememeli'


class TestTheme:
    """KOD9: Tema ayarı kaydedilip sayfaya uygulanmalı."""

    def test_dark_theme_is_applied_to_pages(self, auth_client):
        import re

        def theme():
            html = auth_client.get('/').data.decode()
            match = re.search(r'data-theme="(\w+)"', html)
            return match.group(1) if match else None

        assert theme() == 'light'

        auth_client.put('/api/settings',
            data=json.dumps({'theme': 'dark'}),
            content_type='application/json')
        assert theme() == 'dark'

        auth_client.put('/api/settings',
            data=json.dumps({'theme': 'light'}),
            content_type='application/json')
        assert theme() == 'light'

    def test_theme_applies_to_other_pages(self, auth_client):
        auth_client.put('/api/settings',
            data=json.dumps({'theme': 'dark'}),
            content_type='application/json')
        for path in ('/cards', '/payments', '/settings', '/notifications'):
            assert b'data-theme="dark"' in auth_client.get(path).data, path

    def test_anon_pages_render(self, client):
        assert client.get('/login').status_code == 200
        assert client.get('/register').status_code == 200
        assert client.get('/forgot-password').status_code == 200

    def test_css_defines_dark_theme_variables(self):
        import pathlib
        css = (pathlib.Path(__file__).resolve().parent.parent /
               'app' / 'static' / 'css' / 'style.css').read_text(encoding='utf-8')
        assert '[data-theme="dark"]' in css
        assert '--card-bg' in css


class TestNotificationLifecycle:
    """KOD10: Geçersiz hatırlatmalar iptal edilmeli, eski kayıtlar temizlenmeli."""

    def test_deactivating_card_cancels_pending(self, app, auth_client):
        add_card(auth_client)
        with app.app_context():
            assert Notification.query.filter_by(status='pending').count() > 0

            Card.query.first().is_active = False
            db.session.commit()
            from app.notifications import generate_notifications_for_upcoming_payments
            generate_notifications_for_upcoming_payments(1)

            assert Notification.query.filter_by(status='pending').count() == 0

    def test_past_due_unpaid_cancels_pending(self, app, auth_client):
        add_card(auth_client)
        with app.app_context():
            from app.notifications import cancel_stale_notifications
            payment = Payment.query.filter_by(is_paid=False).first()
            payment.due_date = date.today() - timedelta(days=5)
            db.session.commit()

            cancel_stale_notifications(1)
            assert Notification.query.filter_by(
                payment_id=payment.id, status='pending').count() == 0

    def test_paid_payment_cancels_pending(self, app, auth_client):
        add_card(auth_client)
        with app.app_context():
            from app.notifications import cancel_stale_notifications
            payment = Payment.query.filter_by(is_paid=False).first()
            payment.is_paid = True
            db.session.commit()

            cancel_stale_notifications(1)
            assert Notification.query.filter_by(
                payment_id=payment.id, status='pending').count() == 0

    def test_deleting_card_removes_notifications(self, app, auth_client):
        add_card(auth_client)
        with app.app_context():
            assert Notification.query.count() > 0

        auth_client.delete('/api/cards/1')

        with app.app_context():
            assert Notification.query.count() == 0

    def test_purge_removes_old_terminal_only(self, app, auth_client):
        from datetime import datetime
        add_card(auth_client)
        with app.app_context():
            from app.notifications import purge_old_notifications
            payment = Payment.query.first()
            old = Notification(
                payment_id=payment.id, user_id=1, reminder_type='old',
                message='eski', status='completed',
                scheduled_at=datetime(2020, 1, 1), created_at=datetime(2020, 1, 1),
            )
            db.session.add(old)
            db.session.commit()
            old_id = old.id
            pending_before = Notification.query.filter_by(status='pending').count()

            removed = purge_old_notifications(days=180)
            assert removed >= 1
            assert db.session.execute(
                db.select(Notification.id).where(Notification.id == old_id)
            ).first() is None
            # Bekleyen hatırlatmalar korunmalı.
            assert Notification.query.filter_by(status='pending').count() == pending_before

    def test_purge_keeps_session_usable(self, app, auth_client):
        """Toplu silme sonrası aynı oturumda API hata vermemeli (KOD10)."""
        from datetime import datetime
        add_card(auth_client)
        with app.app_context():
            from app.notifications import purge_old_notifications
            payment = Payment.query.first()
            old = Notification(
                payment_id=payment.id, user_id=1, reminder_type='old2',
                message='eski', status='dismissed',
                scheduled_at=datetime(2020, 1, 1), created_at=datetime(2020, 1, 1),
            )
            db.session.add(old)
            db.session.commit()
            purge_old_notifications(days=180)

        # Aynı istemci oturumunda API çağrıları çalışmaya devam etmeli.
        assert auth_client.get('/api/notifications').status_code == 200
        assert auth_client.get('/api/dashboard').status_code == 200
        assert auth_client.get('/api/payments').status_code == 200

    def test_cleanup_endpoint(self, app, auth_client):
        add_card(auth_client)
        response = auth_client.post('/api/notifications/cleanup')
        assert response.status_code == 200
        assert 'temizlendi' in response.get_json()['message']


class TestDatabaseUrl:
    """Render'ın postgres:// ve postgresql:// biçimleri psycopg2 sürücüsüne bağlanmalı."""

    def _uri(self, value, monkeypatch):
        monkeypatch.setenv('DATABASE_URL', value)
        import importlib

        import config as config_module
        importlib.reload(config_module)
        return config_module.Config.SQLALCHEMY_DATABASE_URI

    def test_postgres_scheme_uses_psycopg2_driver(self, monkeypatch):
        uri = self._uri('postgres://user:pw@host:5432/db', monkeypatch)
        assert uri == 'postgresql+psycopg2://user:pw@host:5432/db'

    def test_postgresql_scheme_uses_psycopg2_driver(self, monkeypatch):
        uri = self._uri('postgresql://user:pw@host:5432/db', monkeypatch)
        assert uri == 'postgresql+psycopg2://user:pw@host:5432/db'

    def test_query_params_are_preserved(self, monkeypatch):
        uri = self._uri('postgres://u:p@h:5432/db?sslmode=require', monkeypatch)
        assert uri.endswith('?sslmode=require')

    def test_sqlite_url_is_untouched(self, monkeypatch):
        monkeypatch.delenv('DATABASE_URL', raising=False)
        import importlib

        import config as config_module
        importlib.reload(config_module)
        assert config_module.Config.SQLALCHEMY_DATABASE_URI.startswith('sqlite:///')

    def test_driver_is_importable(self, monkeypatch):
        """Render'da psycopg2-binary kurulu; sürücü adı yanlışsa import hatası verir.

        create_engine bağlantı kurmadan sürücüyü import eder, yani Render'daki
        ModuleNotFoundError'ın çıktığı yeri birebir yeniden üretir.
        """
        pytest.importorskip('psycopg2')
        uri = self._uri('postgres://u:p@h:5432/db', monkeypatch)
        from sqlalchemy import create_engine

        engine = create_engine(uri)
        assert engine.dialect.driver == 'psycopg2'
        assert engine.dialect.dbapi is not None

    def test_plain_postgresql_url_would_break_on_sqlalchemy_21(self, monkeypatch):
        """SQLAlchemy 2.1 varsayılanı psycopg3 kullanıyor; bu yüzden pin şart."""
        import sqlalchemy

        from sqlalchemy.dialects import postgresql

        assert sqlalchemy.__version__.startswith('2.0'), (
            f'SQLAlchemy {sqlalchemy.__version__} kurulu; 2.1 psycopg3 '
            'gerektirdiği için requirements.txt içindeki pin kontrol edilmeli'
        )
        assert postgresql.psycopg2 is not None


class TestProxyHeaders:
    """KOD11: Render gibi ters vekil arkasinda https URL uretilmeli."""

    def test_https_scheme_behind_proxy(self):
        class ProxyConfig(TestConfig):
            TRUST_PROXY = True

        app = create_app(config_class=ProxyConfig)
        with app.app_context():
            db.create_all()
        try:
            with app.test_client() as client:
                response = client.post(
                    '/forgot-password',
                    data={'username': 'yok', 'email': 'yok@bod.com'},
                    headers={'X-Forwarded-Proto': 'https',
                             'X-Forwarded-Host': 'kredi-kart-takip.onrender.com'},
                )
                assert response.status_code == 200
        finally:
            with app.app_context():
                db.session.remove()
                db.drop_all()

    def test_reset_email_uses_https_when_proxied(self):
        """Sifre sifirlama baglantisi http:// olmamali.

        ProxyFix yalnizca wsgi_app katmaninda calisir; bu yuzden istek
        test_client uzerinden gonderilmelidir.
        """
        class ProxyConfig(TestConfig):
            TRUST_PROXY = True

        app = create_app(config_class=ProxyConfig)
        captured = {}

        with app.app_context():
            from app.models import User
            user = User(username='proxyuser', email='proxy@example.com')
            user.set_password('pw')
            db.session.add(user)
            db.session.commit()

            original_warning = app.logger.warning
            app.logger.warning = lambda msg, *a: captured.update(url=str(a[0]) if a else msg)
            try:
                client = app.test_client()
                response = client.post(
                    '/forgot-password',
                    data={'username': 'proxyuser', 'email': 'proxy@example.com'},
                    headers={'X-Forwarded-Proto': 'https',
                             'X-Forwarded-Host': 'kredi-kart-takip.onrender.com'},
                )
                assert response.status_code == 200
            finally:
                app.logger.warning = original_warning
                db.session.rollback()

        assert captured, 'Sifre sifirlama baglantisi loglanmadi'
        assert captured['url'].startswith('https://kredi-kart-takip.onrender.com/'), (
            f"Sifre sifirlama baglantisi yanlis: {captured['url']}"
        )


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
