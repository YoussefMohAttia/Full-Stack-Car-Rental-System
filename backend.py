from datetime import datetime
from typing import Dict, List, Optional, Tuple
import os
from pathlib import Path
import sqlite3
import hmac
import mysql.connector
from mysql.connector import Error
import re
import bcrypt


class SQLiteCursor:
    """Small compatibility layer for the MySQL-style queries used by this app."""

    def __init__(self, cursor):
        self.cursor = cursor

    def execute(self, query, params=None):
        query = query.replace('%s', '?').replace('NOW()', 'CURRENT_TIMESTAMP')
        query = re.sub(
            r'DATEDIFF\(([^,]+),\s*([^)]+)\)',
            r'CAST(julianday(\1) - julianday(\2) AS INTEGER)',
            query,
        )
        normalized_params = tuple(
            value.isoformat(sep=' ') if isinstance(value, datetime) else value
            for value in (params or ())
        )
        self.cursor.execute(query, normalized_params)
        return self

    def fetchone(self):
        row = self.cursor.fetchone()
        return dict(row) if row else None

    def fetchall(self):
        return [dict(row) for row in self.cursor.fetchall()]

    @property
    def lastrowid(self):
        return self.cursor.lastrowid

    def close(self):
        self.cursor.close()


def initialize_sqlite_database(db):
    db.executescript("""
        PRAGMA foreign_keys = ON;

        CREATE TABLE IF NOT EXISTS offices (
            office_id INTEGER PRIMARY KEY AUTOINCREMENT,
            country TEXT NOT NULL,
            phone TEXT
        );
        CREATE TABLE IF NOT EXISTS cars (
            plate_id TEXT PRIMARY KEY,
            model TEXT NOT NULL,
            year INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            office_id INTEGER NOT NULL,
            price_per_day REAL NOT NULL,
            FOREIGN KEY (office_id) REFERENCES offices(office_id) ON DELETE RESTRICT
        );
        CREATE TABLE IF NOT EXISTS customers (
            SSN INTEGER PRIMARY KEY AUTOINCREMENT,
            fname TEXT NOT NULL,
            lname TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password BLOB NOT NULL,
            phone TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS reservations (
            reservation_id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_ssn INTEGER NOT NULL,
            plate_id TEXT NOT NULL,
            reservation_date TEXT NOT NULL,
            pickup_date TEXT NOT NULL,
            return_date TEXT NOT NULL,
            actual_return_date TEXT,
            cancellation_date TEXT,
            price REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (customer_ssn) REFERENCES customers(SSN) ON DELETE RESTRICT,
            FOREIGN KEY (plate_id) REFERENCES cars(plate_id) ON DELETE RESTRICT
        );
        CREATE TABLE IF NOT EXISTS admin (
            admin_ssn INTEGER PRIMARY KEY AUTOINCREMENT,
            fname TEXT NOT NULL,
            lname TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS payments (
            payment_id INTEGER PRIMARY KEY AUTOINCREMENT,
            reservation_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            payment_date TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (reservation_id) REFERENCES reservations(reservation_id) ON DELETE RESTRICT
        );
    """)

    db.executemany(
        "INSERT OR IGNORE INTO offices (office_id, country, phone) VALUES (?, ?, ?)",
        [(1, 'Egypt', '123-456-7890'), (2, 'Germany', '123-456-7891')],
    )
    db.executemany(
        """INSERT OR IGNORE INTO cars
        (plate_id, model, year, status, office_id, price_per_day)
        VALUES (?, ?, ?, ?, ?, ?)""",
        [
            ('ABC123', 'Toyota Camry', 2022, 'active', 1, 50.00),
            ('XYZ789', 'Honda Civic', 2021, 'active', 1, 45.00),
            ('DEF456', 'Ford Mustang', 2023, 'active', 2, 75.00),
        ],
    )
    db.executemany(
        "INSERT OR IGNORE INTO admin (email, fname, lname, password) VALUES (?, ?, ?, ?)",
        [
            ('admin@example.com', 'Admin', 'User', 'adminpass123'),
            ('super@example.com', 'Super', 'Admin', 'superpass456'),
        ],
    )
    db.commit()

class CarRentalSystem:
    def __init__(self):
        try:
            if os.getenv("DB_ENGINE", "mysql").lower() == "sqlite":
                database_path = Path(os.getenv("SQLITE_DATABASE", "data/car_rental.db"))
                database_path.parent.mkdir(parents=True, exist_ok=True)
                self.db = sqlite3.connect(database_path)
                self.db.row_factory = sqlite3.Row
                initialize_sqlite_database(self.db)
                self.cursor = SQLiteCursor(self.db.cursor())
                return

            self.db = mysql.connector.connect(
                host=os.getenv("MYSQLHOST", os.getenv("DB_HOST", "localhost")),
                port=int(os.getenv("MYSQLPORT", os.getenv("DB_PORT", "3306"))),
                user=os.getenv("MYSQLUSER", os.getenv("DB_USER", "root")),
                password=os.getenv("MYSQLPASSWORD", os.getenv("DB_PASSWORD", "")),
                database=os.getenv("MYSQLDATABASE", os.getenv("DB_NAME", "car_rental")),
            )
            self.cursor = self.db.cursor(dictionary=True)
        except (Error, sqlite3.Error) as e:
            print(f"Error connecting to database: {e}")
            raise

    def create_payment(self, reservation_id: int, amount: float, commit: bool = True) -> bool:
        try:
            query = "INSERT INTO payments (reservation_id, amount) VALUES (%s, %s)"
            self.cursor.execute(query, (reservation_id, amount))
            if commit:
                self.db.commit()
            return True
        except Exception as e:
            print(f"Error creating payment: {e}")
            return False

    def get_reservations_report(self, start_date: datetime, 
                              end_date: datetime) -> List[Dict]:
        try:
            query = """
            SELECT r.*, c.model, c.plate_id, cu.fname, cu.lname
            FROM reservations r
            JOIN cars c ON r.plate_id = c.plate_id
            JOIN customers cu ON r.customer_ssn = cu.SSN
            WHERE r.pickup_date BETWEEN %s AND %s
            """
            self.cursor.execute(query, (start_date, end_date))
            return self.cursor.fetchall()
        except Exception as e:
            print(f"Error getting reservations: {e}")
            return []

    def validate_dates(self, pickup_date: datetime, return_date: datetime) -> bool:
        return pickup_date < return_date and pickup_date.date() >= datetime.now().date()

    def check_car_availability(self, plate_id: str, pickup_date: datetime, 
                             return_date: datetime) -> bool:
        try:
            query = """
            SELECT COUNT(*) as count FROM reservations 
            WHERE plate_id = %s
            AND status IN ('active', 'picked_up')
            AND pickup_date < %s
            AND return_date > %s
            """
            self.cursor.execute(query, (plate_id, return_date, pickup_date))
            result = self.cursor.fetchone()
            return result['count'] == 0
        except Exception as e:
            print(f"Error checking availability: {e}")
            return False

    def get_car_reservations(self, plate_id: str, start_date: datetime, 
                           end_date: datetime) -> List[Dict]:
        try:
            query = """
            SELECT r.*, c.*
            FROM reservations r
            JOIN cars c ON r.plate_id = c.plate_id
            WHERE r.plate_id = %s 
            AND r.pickup_date BETWEEN %s AND %s
            """
            self.cursor.execute(query, (plate_id, start_date, end_date))
            return self.cursor.fetchall()
        except Exception as e:
            print(f"Error getting car reservations: {e}")
            return []

    def get_cars_status_on_date(self, start_date: datetime, end_date: datetime) -> List[Dict]:
        try:
            query = """
            SELECT 
                c.*,
                CASE 
                    WHEN EXISTS (
                        SELECT 1 
                        FROM reservations r 
                        WHERE r.plate_id = c.plate_id 
                        AND r.status NOT IN ('cancelled')
                        AND (
                            (r.pickup_date BETWEEN %s AND %s)  -- reservation starts within period
                            OR (r.return_date BETWEEN %s AND %s)  -- reservation ends within period
                            OR (%s BETWEEN r.pickup_date AND r.return_date)  -- period start within reservation
                            OR (%s BETWEEN r.pickup_date AND r.return_date)  -- period end within reservation
                        )
                    ) THEN 'rented'
                    ELSE 'active'
                END AS current_status
            FROM cars c
            GROUP BY c.plate_id, c.model, c.year, c.status, c.price_per_day, c.office_id
            ORDER BY c.plate_id
            """
            self.cursor.execute(query, (start_date, end_date, start_date, end_date, start_date, end_date))
            return self.cursor.fetchall()
        except Exception as e:
            print(f"Error getting cars status: {e}")
            return []

    def get_customer_reservations(self, customer_ssn: int) -> List[Dict]:
        try:
            query = """
            SELECT r.*, c.model, c.plate_id, cu.*
            FROM reservations r
            JOIN cars c ON r.plate_id = c.plate_id
            JOIN customers cu ON r.customer_ssn = cu.SSN
            WHERE r.customer_ssn = %s
            """
            self.cursor.execute(query, (customer_ssn,))
            return self.cursor.fetchall()
        except Exception as e:
            print(f"Error getting customer reservations: {e}")
            return []

    def get_daily_payments(self, start_date: datetime, end_date: datetime) -> List[Dict]:
        try:
            query = """
            SELECT DATE(payment_date) as date, 
                   SUM(amount) as total_amount,
                   COUNT(*) as number_of_payments
            FROM payments
            WHERE payment_date BETWEEN %s AND %s
            GROUP BY DATE(payment_date)
            ORDER BY date
            """
            self.cursor.execute(query, (start_date, end_date))
            return self.cursor.fetchall()
        except Exception as e:
            print(f"Error getting daily payments: {e}")
            return []

    def __del__(self):
        if hasattr(self, 'cursor') and self.cursor:
            self.cursor.close()
        if hasattr(self, 'db') and self.db:
            self.db.close() 

class Admin(CarRentalSystem):
    def __init__(self):
        super().__init__()

    def admin_login(self, email: str, password: str) -> Tuple[Optional[Dict], str]:
        try:
            # Query by email, then verify the password in Python.
            query = """
            SELECT admin_ssn, fname, lname, email, password
            FROM admin 
            WHERE email = %s
            """
            self.cursor.execute(query, (email,))
            admin = self.cursor.fetchone()

            if admin and self.verify_password(admin['password'], password):
                return {
                    'id': admin['admin_ssn'],  # Changed from 'id' to 'admin_ssn'
                    'email': admin['email'],
                    'name': f"{admin['fname']} {admin['lname']}"  # Combine first and last name
                }, "Login successful"
            return None, "Invalid email or password"
            
        except Exception as e:
            print(f"Admin login error: {e}")
            return None, f"Login failed: {str(e)}"

    @staticmethod
    def verify_password(stored_password, submitted_password: str) -> bool:
        if isinstance(stored_password, str) and stored_password.startswith('$2'):
            return bcrypt.checkpw(submitted_password.encode('utf-8'), stored_password.encode('utf-8'))
        return hmac.compare_digest(str(stored_password), submitted_password)

    def validate_admin_input(self, email: str, password: str) -> Tuple[bool, str]:
        # Email validation
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, email):
            return False, "Invalid email format"
        
        # Password validation (stricter for admin)
        if len(password) < 10:
            return False, "Admin password must be at least 10 characters long"
        if not re.search(r'[A-Z]', password):
            return False, "Password must contain at least one uppercase letter"
        if not re.search(r'[a-z]', password):
            return False, "Password must contain at least one lowercase letter"
        if not re.search(r'[0-9]', password):
            return False, "Password must contain at least one number"
        if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
            return False, "Password must contain at least one special character"
        
        return True, "Validation successful"

    def register_car(self, plate_id: str, model: str, year: int, office_id: int, 
                    price_per_day: float) -> bool:
        try:
            query = """INSERT INTO cars (plate_id, model, year, status, office_id, 
                    price_per_day) VALUES (%s, %s, %s, 'active', %s, %s)"""
            self.cursor.execute(query, (plate_id, model, year, office_id, price_per_day))
            self.db.commit()
            return True
        except Exception as e:
            print(f"Error registering car: {e}")
            return False

    def update_car_status(self, plate_id: str, status: str) -> bool:
        try:
            if status not in ['active', 'rented', 'out_of_service']:
                raise ValueError("Invalid status")
            query = "UPDATE cars SET status = %s WHERE plate_id = %s"
            self.cursor.execute(query, (status, plate_id))
            self.db.commit()
            return True
        except Exception as e:
            print(f"Error updating car status: {e}")
            return False

    def get_car_statistics(self) -> Dict:
        try:
            query = """
            SELECT 
                COUNT(*) as total_cars,
                SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) as available_cars,
                SUM(CASE WHEN status = 'rented' THEN 1 ELSE 0 END) as rented_cars
            FROM cars
            """
            self.cursor.execute(query)
            return self.cursor.fetchone()
        except Exception as e:
            print(f"Error getting statistics: {e}")
            return {}

    def get_car_specific_reservations(self, plate_id: str, start_date: datetime, end_date: datetime) -> List[Dict]:
        try:
            query = """
            SELECT r.*, c.model, c.year, c.price_per_day,  
                   cu.fname, cu.lname, cu.email, cu.phone
            FROM reservations r
            JOIN cars c ON r.plate_id = c.plate_id
            JOIN customers cu ON r.customer_ssn = cu.SSN
            WHERE r.plate_id = %s 
            AND r.pickup_date BETWEEN %s AND %s
            ORDER BY r.pickup_date
            """
            self.cursor.execute(query, (plate_id, start_date, end_date))
            return self.cursor.fetchall()
        except Exception as e:
            print(f"Error getting car reservations: {e}")
            return []

    def get_customer_detailed_reservations(self, customer_ssn: int) -> List[Dict]:
        try:
            query = """
            SELECT 
                r.reservation_id, r.pickup_date, r.return_date, 
                r.status, r.price,
                c.plate_id, c.model, c.year, c.price_per_day,
                cu.fname, cu.lname, cu.email, cu.phone,
                IFNULL(p.amount, 0) as payment_amount,
                p.payment_date
            FROM reservations r
            JOIN cars c ON r.plate_id = c.plate_id
            JOIN customers cu ON r.customer_ssn = cu.SSN
            LEFT JOIN payments p ON r.reservation_id = p.reservation_id
            WHERE r.customer_ssn = %s
            ORDER BY r.pickup_date DESC
            """
            self.cursor.execute(query, (customer_ssn,))
            return self.cursor.fetchall()
        except Exception as e:
            print(f"Error getting customer reservations: {e}")
            return []

    def get_revenue_by_car(self, start_date: datetime, end_date: datetime) -> List[Dict]:
        try:
            query = """
            SELECT 
                c.plate_id, c.model,
                COUNT(r.reservation_id) as total_reservations,
                SUM(p.amount) as total_revenue,
                SUM(DATEDIFF(r.return_date, r.pickup_date)) as total_days_rented
            FROM cars c
            LEFT JOIN reservations r ON c.plate_id = r.plate_id
            LEFT JOIN payments p ON r.reservation_id = p.reservation_id
            WHERE r.pickup_date BETWEEN %s AND %s
            GROUP BY c.plate_id, c.model
            ORDER BY total_revenue DESC
            """
            self.cursor.execute(query, (start_date, end_date))
            return self.cursor.fetchall()
        except Exception as e:
            print(f"Error getting revenue by car: {e}")
            return []

    def get_office_statistics(self, start_date: datetime, end_date: datetime) -> List[Dict]:
        try:
            query = """
            SELECT 
                o.office_id, o.country,
                COUNT(DISTINCT c.plate_id) as total_cars,
                COUNT(r.reservation_id) as total_reservations,
                SUM(p.amount) as total_revenue
            FROM offices o
            LEFT JOIN cars c ON o.office_id = c.office_id
            LEFT JOIN reservations r ON c.plate_id = r.plate_id
            AND r.pickup_date BETWEEN %s AND %s
            LEFT JOIN payments p ON r.reservation_id = p.reservation_id
            GROUP BY o.office_id, o.country
            """
            self.cursor.execute(query, (start_date, end_date))
            return self.cursor.fetchall()
        except Exception as e:
            print(f"Error getting office statistics: {e}")
            return []

    def get_reservations_report(self, start_date: datetime, end_date: datetime, 
                              plate_id: Optional[str] = None, 
                              customer_ssn: Optional[int] = None) -> List[Dict]:
        try:
            query = """
            SELECT r.*, c.model, c.year, c.price_per_day, c.plate_id, 
                   cu.fname, cu.lname, cu.email, cu.phone, cu.SSN
            FROM reservations r
            JOIN cars c ON r.plate_id = c.plate_id
            JOIN customers cu ON r.customer_ssn = cu.SSN
            WHERE r.pickup_date BETWEEN %s AND %s
            """
            params = [start_date, end_date]

            if plate_id:
                query += " AND r.plate_id = %s"
                params.append(plate_id)
            
            if customer_ssn:
                query += " AND r.customer_ssn = %s"
                params.append(customer_ssn)

            query += " ORDER BY r.pickup_date DESC"
            
            self.cursor.execute(query, params)
            return self.cursor.fetchall()
        except Exception as e:
            print(f"Error getting reservations: {e}")
            return []

class Customer(CarRentalSystem):
    def __init__(self):
        super().__init__()
    
    def validate_input(self, email: str, password: str, phone: str) -> Tuple[bool, str]:
        # Phone validation - stricter implementation
        phone = phone.strip()  # Remove any whitespace
        if not phone.isdigit():
            return False, "Phone number must contain only digits"
        if len(phone) != 11:
            return False, f"Phone number must be exactly 11 digits (got {len(phone)})"
            
        # Email validation
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, email):
            return False, "Invalid email format"
        
        # Password validation
        if len(password) < 8:
            return False, "Password must be at least 8 characters long"
        if not re.search(r'[A-Z]', password):
            return False, "Password must contain at least one uppercase letter"
        if not re.search(r'[a-z]', password):
            return False, "Password must contain at least one lowercase letter"
        if not re.search(r'[0-9]', password):
            return False, "Password must contain at least one number"
        
        return True, "Validation successful"

    def register_customer(self, fname: str, lname: str, email: str, 
                         password: str, phone: str) -> Tuple[bool, str]:
        try:
            # Strip whitespace from phone number
            phone = phone.strip()
            
            # Input validation
            is_valid, message = self.validate_input(email, password, phone)
            if not is_valid:
                return False, message
            
            # Check if email already exists
            self.cursor.execute("SELECT email FROM customers WHERE email = %s", (email,))
            if self.cursor.fetchone():
                return False, "Email already registered"
            
            # Hash password
            salt = bcrypt.gensalt()
            hashed_password = bcrypt.hashpw(password.encode('utf-8'), salt)
            
            query = """INSERT INTO customers (fname, lname, email, password, phone) 
                    VALUES (%s, %s, %s, %s, %s)"""
            self.cursor.execute(query, (fname, lname, email, hashed_password, phone))
            self.db.commit()
            return True, "Registration successful"
        except Exception as e:
            print(f"Error registering customer: {e}")
            return False, "Registration failed"
    
    def login(self, email: str, password: str) -> Tuple[Optional[Dict], str]:
        try:
            # First get the user by email only
            query = "SELECT * FROM customers WHERE email = %s"
            self.cursor.execute(query, (email,))
            user = self.cursor.fetchone()
            
            if not user:
                return None, "Invalid email or password"
            
            try:
                # Get the stored hashed password
                stored_password = user['password']
                
                # Ensure the stored password is in bytes
                if isinstance(stored_password, str):
                    stored_password = stored_password.encode('utf-8')
                
                # Compare the entered password with stored hash
                if bcrypt.checkpw(password.encode('utf-8'), stored_password):
                    return user, "Login successful"
                else:
                    return None, "Invalid email or password"
                    
            except Exception as e:
                print(f"Password verification error: {e}")
                return None, "Invalid password format"
                
        except Exception as e:
            print(f"Login error: {e}")
            return None, "Login failed"
    
    def create_reservation(self, customer_ssn: int, plate_id: str, 
                         pickup_date: datetime, return_date: datetime) -> bool:
        try:
            if not self.validate_dates(pickup_date, return_date):
                raise ValueError("Invalid dates")
            
            if not self.check_car_availability(plate_id, pickup_date, return_date):
                raise ValueError("Car not available for selected dates")

            # Calculate price based on number of days and car's daily rate
            query = "SELECT price_per_day FROM cars WHERE plate_id = %s"
            self.cursor.execute(query, (plate_id,))
            car = self.cursor.fetchone()
            if not car:
                raise ValueError("Car not found")
            car_price = car['price_per_day']
            days = (return_date - pickup_date).days
            total_price = car_price * days

            # Create the reservation
            query = """INSERT INTO reservations (customer_ssn, plate_id, reservation_date,
                    pickup_date, return_date, price, status) 
                    VALUES (%s, %s, NOW(), %s, %s, %s, 'active')"""
            self.cursor.execute(query, (customer_ssn, plate_id, pickup_date, 
                                      return_date, total_price))
            
            # Get the reservation_id of the newly created reservation
            reservation_id = self.cursor.lastrowid
            
            # Keep the reservation and payment in the same transaction.
            if not self.create_payment(reservation_id, total_price, commit=False):
                raise ValueError("Could not create payment")
            
            self.db.commit()
            return True
        except Exception as e:
            print(f"Error creating reservation: {e}")
            self.db.rollback()
            return False
    
    def search_available_cars(self, office_id: Optional[int] = None, 
                            model: Optional[str] = None,
                            max_price: Optional[float] = None,
                            min_price: Optional[float] = None,
                            year: Optional[int] = None) -> List[Dict]:
        try:
            query = """
            SELECT * FROM cars c
            WHERE c.status = 'active'
            AND NOT EXISTS (
                SELECT 1 FROM reservations r
                WHERE r.plate_id = c.plate_id
                AND r.status IN ('active', 'picked_up')
                AND r.pickup_date <= %s
                AND r.return_date > %s
            )
            """
            now = datetime.now()
            params = [now, now]
            
            if office_id:
                query += "AND office_id = %s "
                params.append(office_id)
            if model:
                query += "AND model = %s "
                params.append(model)
            if max_price:
                query += "AND price_per_day <= %s "
                params.append(max_price)
            if min_price:
                query += "AND price_per_day >= %s "
                params.append(min_price)
            if year:
                query += "AND year = %s "
                params.append(year)

            self.cursor.execute(query, params)
            return self.cursor.fetchall()
        except Exception as e:
            print(f"Error searching cars: {e}")
            return []

    def pickup_car(self, reservation_id: int) -> bool:
        try:
            # Verify reservation exists and is active
            query = """
            SELECT * FROM reservations 
            WHERE reservation_id = %s AND status = 'active'
            """
            self.cursor.execute(query, (reservation_id,))
            reservation = self.cursor.fetchone()
            
            if not reservation:
                raise ValueError("Invalid or inactive reservation")

            # Update reservation status to 'picked_up'
            query = "UPDATE reservations SET status = 'picked_up' WHERE reservation_id = %s"
            self.cursor.execute(query, (reservation_id,))
            
            self.db.commit()
            return True
        except Exception as e:
            print(f"Error during pickup: {e}")
            self.db.rollback()
            return False

    def return_car(self, reservation_id: int) -> bool:
        try:
            # Get reservation details
            query = """
            SELECT * FROM reservations 
            WHERE reservation_id = %s AND status = 'picked_up'
            """
            self.cursor.execute(query, (reservation_id,))
            reservation = self.cursor.fetchone()
            
            if not reservation:
                raise ValueError("Invalid reservation or car not picked up")

            # Calculate any additional charges (e.g., late returns)
            actual_return = datetime.now()
            scheduled_return = reservation['return_date']
            if isinstance(scheduled_return, str):
                scheduled_return = datetime.fromisoformat(scheduled_return)
            extra_days = max(0, (actual_return - scheduled_return).days)
            extra_charges = 0
            
            if extra_days > 0:
                query = "SELECT price_per_day FROM cars WHERE plate_id = %s"
                self.cursor.execute(query, (reservation['plate_id'],))
                daily_rate = self.cursor.fetchone()['price_per_day']
                extra_charges = extra_days * daily_rate

            # Update reservation status
            query = "UPDATE reservations SET status = 'completed', actual_return_date = %s WHERE reservation_id = %s"
            self.cursor.execute(query, (actual_return, reservation_id))
            
            # Update car status back to active
            query = "UPDATE cars SET status = 'active' WHERE plate_id = %s"
            self.cursor.execute(query, (reservation['plate_id'],))
            
            # Create payment record including any extra charges
            total_payment = reservation['price'] + extra_charges
            self.create_payment(reservation_id, total_payment)
            
            self.db.commit()
            return True
        except Exception as e:
            print(f"Error during return: {e}")
            self.db.rollback()
            return False

    def cancel_reservation(self, reservation_id: int, customer_ssn: int) -> bool:
        try:
            # Verify reservation exists and is active (not picked up or completed)
            query = """
            SELECT * FROM reservations 
            WHERE reservation_id = %s AND customer_ssn = %s AND status = 'active'
            """
            self.cursor.execute(query, (reservation_id, customer_ssn))
            reservation = self.cursor.fetchone()
            
            if not reservation:
                raise ValueError("Invalid reservation or cannot be cancelled (already picked up or completed)")

            # Update reservation status to cancelled
            query = """UPDATE reservations 
                      SET status = 'cancelled',
                          cancellation_date = NOW()
                      WHERE reservation_id = %s"""
            self.cursor.execute(query, (reservation_id,))
            
            self.db.commit()
            return True
        except Exception as e:
            print(f"Error cancelling reservation: {e}")
            self.db.rollback()
            return False
