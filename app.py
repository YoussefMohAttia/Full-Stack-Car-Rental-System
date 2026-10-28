from flask import Flask, abort, render_template, request, redirect, url_for, flash, session
from datetime import datetime
from functools import wraps
import hmac
import os
import secrets
from backend import Admin, Customer

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'development-only-secret-key')
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax')


def csrf_token():
    if '_csrf_token' not in session:
        session['_csrf_token'] = secrets.token_urlsafe(32)
    return session['_csrf_token']


@app.context_processor
def inject_csrf_token():
    return {'csrf_token': csrf_token(), 'current_year': datetime.now().year}


def validate_csrf():
    submitted_token = request.form.get('csrf_token', '')
    if not hmac.compare_digest(session.get('_csrf_token', ''), submitted_token):
        abort(400)


def admin_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if not session.get('admin'):
            return redirect(url_for('admin_login'))
        return view(*args, **kwargs)
    return wrapped_view


def customer_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if not session.get('customer_ssn'):
            return redirect(url_for('customer_login'))
        return view(*args, **kwargs)
    return wrapped_view


@app.template_filter('date_display')
def date_display(value):
    if hasattr(value, 'strftime'):
        return value.strftime('%Y-%m-%d')
    return str(value)[:10]

@app.route('/')
def index():
    return render_template('index.html')

# Admin routes
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        try:
            validate_csrf()
            email = request.form['email']
            password = request.form['password']
            
            admin = Admin()
            user, message = admin.admin_login(email, password)
            
            if user:
                session.pop('customer_ssn', None)
                session['admin'] = True
                session['admin_ssn'] = user['id']  
                session['admin_name'] = user['name']
                flash('Login successful', 'success')
                return redirect(url_for('admin_dashboard'))
            else:
                flash(message, 'danger')  
        except Exception:
            flash('An error occurred during login. Please try again.', 'danger')
    
    return render_template('admin/login.html')

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin', None)
    session.pop('admin_ssn', None)
    session.pop('admin_name', None)
    return redirect(url_for('index'))

@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    admin = Admin()
    stats = admin.get_car_statistics()
    return render_template('admin/dashboard.html', stats=stats)

@app.route('/admin/cars/add', methods=['GET', 'POST'])
@admin_required
def add_car():
    if request.method == 'POST':
        try:
            validate_csrf()
            year = int(request.form['year'])
            current_year = datetime.now().year
            
            if year < 1900 or year > current_year:
                flash(f'Please enter a valid year between 1900 and {current_year}', 'danger')
                return render_template('admin/add_car.html')
                
            admin = Admin()
            result = admin.register_car(
                plate_id=request.form['plate_id'],
                model=request.form['model'],
                year=year,
                office_id=int(request.form['office_id']),
                price_per_day=float(request.form['price_per_day'])
            )
            if result:
                flash('Car added successfully', 'success')
            else:
                flash('Could not add car. Check that the plate ID is unique and the office exists.', 'danger')
            return redirect(url_for('admin_dashboard'))
        except ValueError:
            flash('Invalid year format', 'danger')
            return render_template('admin/add_car.html')
    return render_template('admin/add_car.html')

@app.route('/admin/reports')
@admin_required
def view_reports():
    # Get date range and filters from request arguments or use defaults
    default_start_date = datetime.now().replace(day=1).strftime('%Y-%m-%d')
    default_end_date = datetime.now().strftime('%Y-%m-%d')
    
    start_date = request.args.get('start_date', default_start_date)
    end_date = request.args.get('end_date', default_end_date)
    plate_id = request.args.get('plate_id', '')
    customer_ssn = request.args.get('customer_ssn', type=int)  # Convert to int if present

    # Convert string dates to datetime objects
    try:
        start_date = datetime.strptime(start_date, '%Y-%m-%d')
        end_date = datetime.strptime(end_date, '%Y-%m-%d')
        if start_date > end_date:
            raise ValueError
    except ValueError:
        flash('Choose a valid date range.', 'danger')
        return redirect(url_for('view_reports'))

    admin = Admin()
    
    # Get reports data with both plate_id and customer_ssn filters
    reservations = admin.get_reservations_report(
        start_date=start_date,
        end_date=end_date,
        plate_id=plate_id if plate_id else None,
        customer_ssn=customer_ssn if customer_ssn else None
    )
    # Pass both start_date and end_date for car status
    car_status = admin.get_cars_status_on_date(start_date, end_date)  # Now passing both dates
    payments = admin.get_daily_payments(start_date, end_date)
    revenue_by_car = admin.get_revenue_by_car(start_date, end_date)
    office_stats = admin.get_office_statistics(start_date, end_date)

    return render_template(
        'admin/reports.html',
        reservations=reservations,
        car_status=car_status,
        payments=payments,
        revenue_by_car=revenue_by_car,
        office_statistics=office_stats,
        default_start_date=default_start_date,
        default_end_date=default_end_date,
        selected_plate_id=plate_id,
        selected_customer_ssn=customer_ssn
    )

# Customer routes
@app.route('/customer/register', methods=['GET', 'POST'])
def customer_register():
    if request.method == 'POST':
        validate_csrf()
        customer = Customer()
        success, message = customer.register_customer(
            fname=request.form['fname'],
            lname=request.form['lname'],
            email=request.form['email'],
            password=request.form['password'],
            phone=request.form['phone']
        )
        if success:
            flash(message, 'success')
            return redirect(url_for('customer_login'))
        flash(message, 'error')
    return render_template('customer/register.html')

@app.route('/customer/login', methods=['GET', 'POST'])
def customer_login():
    if request.method == 'POST':
        try:
            validate_csrf()
            email = request.form['email']
            password = request.form['password']
            
            customer = Customer()
            user, message = customer.login(email, password)
            
            if user:
                session.pop('admin', None)
                session.pop('admin_ssn', None)
                session.pop('admin_name', None)
                session['customer_ssn'] = user['SSN']
                flash('Login successful', 'success')
                return redirect(url_for('customer_dashboard'))
            else:
                flash(message, 'error')
        except Exception:
            flash('An error occurred during login. Please try again.', 'error')
    
    return render_template('customer/login.html')

@app.route('/customer/logout')
def customer_logout():
    session.pop('customer_ssn', None)
    return redirect(url_for('index'))

@app.route('/customer/search')
def search_cars():
    customer = Customer()
    cars = customer.search_available_cars(
        max_price=request.args.get('max_price', type=float),
        model=request.args.get('model'),
        year=request.args.get('year', type=int)
    )
    return render_template('customer/search.html', cars=cars)

@app.route('/customer/reserve/<plate_id>', methods=['GET', 'POST'])
@customer_required
def reserve_car(plate_id):
    if request.method == 'POST':
        try:
            validate_csrf()
            customer = Customer()
            result = customer.create_reservation(
                customer_ssn=session['customer_ssn'],
                plate_id=plate_id,
                pickup_date=datetime.strptime(request.form['pickup_date'], '%Y-%m-%d'),
                return_date=datetime.strptime(request.form['return_date'], '%Y-%m-%d')
            )
        except (KeyError, ValueError):
            flash('Choose valid pickup and return dates.', 'danger')
            return redirect(url_for('reserve_car', plate_id=plate_id))
        if result:
            flash('Reservation successful', 'success')
            return redirect(url_for('customer_dashboard'))
        else:
            flash('Reservation failed. The car may be unavailable for those dates.', 'danger')
    
    today = datetime.now().strftime('%Y-%m-%d')
    return render_template('customer/reserve.html', plate_id=plate_id, today=today)

@app.route('/customer/reservation/cancel/<int:reservation_id>', methods=['POST'])
@customer_required
def cancel_reservation(reservation_id):
    validate_csrf()
    customer = Customer()
    if customer.cancel_reservation(reservation_id, session['customer_ssn']):
        flash('Reservation cancelled successfully', 'success')
    else:
        flash('Reservation could not be cancelled.', 'danger')
    return redirect(url_for('customer_dashboard'))

@app.route('/customer/dashboard')
@customer_required
def customer_dashboard():
    customer = Customer()
    reservations = customer.get_customer_reservations(session['customer_ssn'])
    return render_template('customer/dashboard.html', reservations=reservations)

if __name__ == '__main__':
    app.run(debug=True)
