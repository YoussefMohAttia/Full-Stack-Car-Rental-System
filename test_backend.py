import os
import tempfile
import unittest
from datetime import datetime, timedelta


class CarRentalAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        os.environ['DB_ENGINE'] = 'sqlite'
        os.environ['SECRET_KEY'] = 'test-secret-key'
        from app import app
        cls.app = app
        cls.app.config.update(TESTING=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def setUp(self):
        filename = f'{self.id().rsplit(".", 1)[-1]}.db'
        os.environ['SQLITE_DATABASE'] = os.path.join(self.temp_dir.name, filename)
        self.client = self.app.test_client()

    def csrf_token(self, path):
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        with self.client.session_transaction() as session:
            return session['_csrf_token']

    def register_and_login(self, email='customer@example.com'):
        token = self.csrf_token('/customer/register')
        response = self.client.post('/customer/register', data={
            'csrf_token': token,
            'fname': 'Test',
            'lname': 'Customer',
            'email': email,
            'password': 'StrongPass123',
            'phone': '01234567890',
        })
        self.assertEqual(response.status_code, 302)
        token = self.csrf_token('/customer/login')
        response = self.client.post('/customer/login', data={
            'csrf_token': token,
            'email': email,
            'password': 'StrongPass123',
        })
        self.assertEqual(response.status_code, 302)

    def test_customer_reservation_and_cancellation(self):
        self.register_and_login()
        response = self.client.get('/customer/search')
        self.assertIn(b'Toyota Camry', response.data)

        token = self.csrf_token('/customer/reserve/ABC123')
        pickup = datetime.now() + timedelta(days=2)
        response = self.client.post('/customer/reserve/ABC123', data={
            'csrf_token': token,
            'pickup_date': pickup.strftime('%Y-%m-%d'),
            'return_date': (pickup + timedelta(days=2)).strftime('%Y-%m-%d'),
        })
        self.assertEqual(response.status_code, 302)

        response = self.client.get('/customer/dashboard')
        self.assertIn(b'Toyota Camry', response.data)
        token = self.csrf_token('/customer/dashboard')
        response = self.client.post('/customer/reservation/cancel/1', data={'csrf_token': token})
        self.assertEqual(response.status_code, 302)

    def test_overlapping_reservations_are_rejected(self):
        from backend import Customer

        customer = Customer()
        registered, _ = customer.register_customer('Test', 'Customer', 'one@example.com', 'StrongPass123', '01234567890')
        self.assertTrue(registered)
        user, _ = customer.login('one@example.com', 'StrongPass123')
        start = datetime.now() + timedelta(days=2)
        self.assertTrue(customer.create_reservation(user['SSN'], 'ABC123', start, start + timedelta(days=6)))
        self.assertFalse(customer.create_reservation(user['SSN'], 'ABC123', start + timedelta(days=2), start + timedelta(days=3)))

    def test_admin_access_and_reports(self):
        response = self.client.post('/admin/cars/add', data={})
        self.assertEqual(response.status_code, 302)
        self.assertIn('/admin/login', response.location)

        token = self.csrf_token('/admin/login')
        response = self.client.post('/admin/login', data={
            'csrf_token': token,
            'email': 'admin@example.com',
            'password': 'adminpass123',
        })
        self.assertEqual(response.status_code, 302)

        from backend import Customer

        customer = Customer()
        registered, _ = customer.register_customer('Report', 'Customer', 'report@example.com', 'StrongPass123', '01234567890')
        self.assertTrue(registered)
        user, _ = customer.login('report@example.com', 'StrongPass123')
        start = datetime.now() + timedelta(days=2)
        self.assertTrue(customer.create_reservation(user['SSN'], 'ABC123', start, start + timedelta(days=2)))

        response = self.client.get('/admin/reports', query_string={
            'start_date': (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d'),
            'end_date': (datetime.now() + timedelta(days=10)).strftime('%Y-%m-%d'),
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Report Customer', response.data)


if __name__ == '__main__':
    unittest.main()
