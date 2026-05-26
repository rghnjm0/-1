# app.py
from flask import Flask, render_template, request, redirect, url_for, flash, session
from functools import wraps
import sqlite3
from datetime import datetime, timedelta
import os

app = Flask(__name__)
app.secret_key = 'your-secret-key-here-change-in-production'
app.config['UPLOAD_FOLDER'] = 'static/images/rooms'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

DB_NAME = "hotel_management.db"


def init_uploads():
    upload_folder = os.path.join('static', 'images', 'rooms')
    if not os.path.exists(upload_folder):
        os.makedirs(upload_folder)
        print(f"Создана папка: {upload_folder}")


init_uploads()


@app.context_processor
def utility_processor():
    def get_room_image(room_number):
        room_number_str = str(room_number)
        extensions = ['.jpg', '.jpeg', '.png', '.webp', '.JPG', '.JPEG', '.PNG', '.WEBP']
        for ext in extensions:
            filename = f"{room_number_str}{ext}"
            full_path = os.path.join('static', 'images', 'rooms', filename)
            if os.path.exists(full_path):
                return url_for('static', filename=f'images/rooms/{filename}')
        return url_for('static', filename='images/rooms/default.jpg')

    def get_room_image_extra(room_number, index):
        room_number_str = str(room_number)
        possible_formats = [
            f"{room_number_str}-{index}",
            f"{room_number_str}_{index}",
            f"{room_number_str} {index}",
            f"{room_number_str}a{index}",
            f"{room_number_str}_{index:02d}",
        ]
        extensions = ['.jpg', '.jpeg', '.png', '.webp', '.JPG', '.JPEG', '.PNG', '.WEBP']
        for format_name in possible_formats:
            for ext in extensions:
                filename = f"{format_name}{ext}"
                full_path = os.path.join('static', 'images', 'rooms', filename)
                if os.path.exists(full_path):
                    return url_for('static', filename=f'images/rooms/{filename}')
        return get_room_image(room_number)

    return {
        'now': datetime.now(),
        'today': datetime.now().date(),
        'timedelta': timedelta,
        'get_room_image': get_room_image,
        'get_room_image_extra': get_room_image_extra
    }


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'client_id' not in session and session.get('user_role') != 'admin':
            flash('Пожалуйста, войдите в систему', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)

    return decorated_function


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('user_role') != 'admin':
            flash('Доступ запрещен. Требуются права администратора.', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)

    return decorated_function


def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def sync_room_statuses():
    """Синхронизирует статусы номеров с актуальными бронированиями"""
    try:
        conn = get_db()
        cursor = conn.cursor()

        today = datetime.now().date()
        today_str = today.strftime('%Y-%m-%d')

        # Сначала сбрасываем все номера в "Свободен"
        cursor.execute("UPDATE Номера SET Статус = 'Свободен'")

        # Находим номера с активными бронированиями (заселенные сейчас)
        cursor.execute("""
            SELECT DISTINCT ID_Номера 
            FROM Бронирования 
            WHERE Статус = 'Заселен'
            AND Дата_заезда <= ?
            AND Дата_выезда > ?
        """, (today_str, today_str))
        occupied_rooms = cursor.fetchall()
        for room in occupied_rooms:
            cursor.execute("UPDATE Номера SET Статус = 'Занят' WHERE ID_Номера = ?", (room['ID_Номера'],))

        # Находим номера с будущими бронями (будут заняты)
        cursor.execute("""
            SELECT DISTINCT ID_Номера 
            FROM Бронирования 
            WHERE Статус IN ('Подтверждено')
            AND Дата_заезда > ?
        """, (today_str,))
        future_rooms = cursor.fetchall()
        for room in future_rooms:
            cursor.execute("""
                UPDATE Номера 
                SET Статус = 'Будет занят' 
                WHERE ID_Номера = ? AND Статус = 'Свободен'
            """, (room['ID_Номера'],))

        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Ошибка синхронизации: {e}")
        return False


# Главная страница
@app.route('/')
def index():
    try:
        sync_room_statuses()
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT Категория FROM Номера ORDER BY Категория")
        categories = [row['Категория'] for row in cursor.fetchall()]
        cursor.execute("""
            SELECT * FROM Номера 
            ORDER BY 
                CASE Статус 
                    WHEN 'Свободен' THEN 1
                    WHEN 'Будет занят' THEN 2
                    WHEN 'Занят' THEN 3
                END,
                Номер_Комнаты
        """)
        rooms = cursor.fetchall()
        conn.close()
        return render_template('index.html', rooms=rooms, categories=categories)
    except Exception as e:
        flash(f'Ошибка при загрузке данных: {str(e)}', 'danger')
        return render_template('index.html', rooms=[], categories=[])


# Поиск номеров
@app.route('/search')
def search_rooms():
    try:
        sync_room_statuses()
        check_in = request.args.get('check_in', '')
        check_out = request.args.get('check_out', '')
        guests = request.args.get('guests', 1, type=int)
        category = request.args.get('category', '')

        conn = get_db()
        cursor = conn.cursor()

        query = """
            SELECT * FROM Номера 
            WHERE Вместимость >= ? 
            AND Статус = 'Свободен'
        """
        params = [guests]

        if category:
            query += " AND Категория = ?"
            params.append(category)

        if check_in and check_out:
            query += """
                AND ID_Номера NOT IN (
                    SELECT ID_Номера FROM Бронирования 
                    WHERE Статус IN ('Подтверждено', 'Заселен')
                    AND NOT (Дата_выезда <= ? OR Дата_заезда >= ?)
                )
            """
            params.extend([check_in, check_out])

        query += " ORDER BY Цена_за_сутки"

        cursor.execute(query, params)
        rooms = cursor.fetchall()

        cursor.execute("SELECT DISTINCT Категория FROM Номера ORDER BY Категория")
        categories = [row['Категория'] for row in cursor.fetchall()]

        conn.close()

        return render_template('rooms.html', rooms=rooms, categories=categories,
                               check_in=check_in, check_out=check_out,
                               guests=guests, selected_category=category)
    except Exception as e:
        flash(f'Ошибка при поиске: {str(e)}', 'danger')
        return redirect(url_for('index'))


# Детальная страница номера
@app.route('/room/<string:room_id>')
def room_detail(room_id):
    try:
        sync_room_statuses()
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM Номера WHERE ID_Номера = ?", (room_id,))
        room = cursor.fetchone()
        if not room:
            flash('Номер не найден', 'danger')
            conn.close()
            return redirect(url_for('index'))
        conn.close()
        return render_template('room_detail.html', room=room)
    except Exception as e:
        flash(f'Ошибка при загрузке номера: {str(e)}', 'danger')
        return redirect(url_for('index'))


# Регистрация клиента
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        try:
            last_name = request.form['last_name']
            first_name = request.form['first_name']
            middle_name = request.form.get('middle_name', '')
            phone = request.form['phone']
            birth_date = request.form.get('birth_date', '')
            address = request.form.get('address', '')
            password = request.form['password']
            confirm_password = request.form['confirm_password']

            if not all([last_name, first_name, phone, password]):
                flash('Заполните все обязательные поля', 'danger')
                return render_template('register.html')

            if password != confirm_password:
                flash('Пароли не совпадают', 'danger')
                return render_template('register.html')

            if len(password) < 6:
                flash('Пароль должен содержать минимум 6 символов', 'danger')
                return render_template('register.html')

            conn = get_db()
            cursor = conn.cursor()

            cursor.execute("SELECT ID_Клиента FROM Клиенты WHERE Телефон = ?", (phone,))
            if cursor.fetchone():
                flash('Клиент с таким телефоном уже зарегистрирован', 'danger')
                conn.close()
                return render_template('register.html')

            cursor.execute("SELECT COUNT(*) FROM Клиенты")
            count = cursor.fetchone()[0] + 1
            client_id = f"CL{count:03d}"

            cursor.execute("""
                INSERT INTO Клиенты (ID_Клиента, Фамилия, Имя, Отчество, Телефон, Дата_рождения, Адрес)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (client_id, last_name, first_name, middle_name, phone, birth_date or None, address or None))

            cursor.execute("""
                INSERT INTO Пользователи (ID_Клиента, Логин, Пароль, Роль)
                VALUES (?, ?, ?, ?)
            """, (client_id, phone, password, 'client'))

            conn.commit()
            conn.close()

            flash('Регистрация успешна! Теперь вы можете войти в систему.', 'success')
            return redirect(url_for('login'))

        except Exception as e:
            flash(f'Ошибка при регистрации: {str(e)}', 'danger')
            return render_template('register.html')

    return render_template('register.html')


# Вход в систему (единый для всех)
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        try:
            phone = request.form['login']
            password = request.form['password']

            conn = get_db()
            cursor = conn.cursor()

            cursor.execute("""
                SELECT u.ID_Клиента, u.Роль, u.Пароль,
                       c.Фамилия, c.Имя, c.Отчество
                FROM Пользователи u
                LEFT JOIN Клиенты c ON u.ID_Клиента = c.ID_Клиента
                WHERE u.Логин = ?
            """, (phone,))

            user = cursor.fetchone()
            conn.close()

            if user and user['Пароль'] == password:
                session.clear()
                session['user_id'] = user['ID_Клиента']
                session['user_role'] = user['Роль']
                session['user_name'] = f"{user['Фамилия'] or ''} {user['Имя'] or ''}".strip()

                if user['Роль'] == 'admin':
                    session['admin_id'] = user['ID_Клиента']
                    session['admin_name'] = session['user_name'] or 'Администратор'
                    flash(f'Добро пожаловать в админ-панель, {user["Имя"] or "Администратор"}!', 'success')
                    return redirect(url_for('admin_dashboard'))
                else:
                    session['client_id'] = user['ID_Клиента']
                    session['client_name'] = session['user_name']
                    flash(f'Добро пожаловать, {user["Имя"]}!', 'success')

                    next_page = request.args.get('next')
                    if next_page:
                        return redirect(next_page)
                    return redirect(url_for('index'))
            else:
                flash('Неверный телефон или пароль', 'danger')

        except Exception as e:
            flash(f'Ошибка при входе: {str(e)}', 'danger')

    return render_template('login.html')


# Выход из системы
@app.route('/logout')
def logout():
    session.clear()
    flash('Вы вышли из системы', 'info')
    return redirect(url_for('index'))


# Личный кабинет
@app.route('/profile')
@login_required
def profile():
    try:
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM Клиенты WHERE ID_Клиента = ?", (session['client_id'],))
        client = cursor.fetchone()

        if not client:
            flash('Клиент не найден', 'danger')
            return redirect(url_for('index'))

        cursor.execute("""
            SELECT b.*, n.Номер_Комнаты, n.Категория, n.Цена_за_сутки,
                   CAST(JULIANDAY(b.Дата_выезда) - JULIANDAY(b.Дата_заезда) AS INTEGER) as days_count
            FROM Бронирования b
            JOIN Номера n ON b.ID_Номера = n.ID_Номера
            WHERE b.ID_Клиента = ?
            ORDER BY b.Дата_заезда DESC
        """, (session['client_id'],))

        bookings = cursor.fetchall()
        bookings_with_total = []
        for booking in bookings:
            booking_dict = dict(booking)
            days = booking_dict.get('days_count', 0)
            if days <= 0:
                days = 1
            booking_dict['total_price'] = days * booking_dict.get('Цена_за_сутки', 0)
            if booking_dict.get('Дата_заезда'):
                booking_dict['Дата_заезда'] = str(booking_dict['Дата_заезда'])
            if booking_dict.get('Дата_выезда'):
                booking_dict['Дата_выезда'] = str(booking_dict['Дата_выезда'])
            bookings_with_total.append(booking_dict)

        conn.close()
        return render_template('profile.html', client=client, bookings=bookings_with_total)

    except Exception as e:
        flash(f'Ошибка при загрузке профиля: {str(e)}', 'danger')
        return redirect(url_for('index'))


# Создание бронирования
@app.route('/booking/<string:room_id>', methods=['GET', 'POST'])
@login_required
def create_booking(room_id):
    try:
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM Номера WHERE ID_Номера = ?", (room_id,))
        room = cursor.fetchone()

        if not room:
            flash('Номер не найден', 'danger')
            conn.close()
            return redirect(url_for('index'))

        if request.method == 'POST':
            check_in = request.form['check_in']
            check_out = request.form['check_out']
            guests = int(request.form['guests'])

            check_in_date = datetime.strptime(check_in, '%Y-%m-%d').date()
            check_out_date = datetime.strptime(check_out, '%Y-%m-%d').date()
            today = datetime.now().date()

            if check_in_date < today:
                flash('Дата заезда не может быть в прошлом', 'danger')
                return render_template('booking.html', room=room,
                                       check_in=check_in, check_out=check_out, guests=guests)

            if check_out_date <= check_in_date:
                flash('Дата выезда должна быть позже даты заезда', 'danger')
                return render_template('booking.html', room=room,
                                       check_in=check_in, check_out=check_out, guests=guests)

            if guests > room['Вместимость']:
                flash(f'Максимальная вместимость номера: {room["Вместимость"]} гостей', 'danger')
                return render_template('booking.html', room=room,
                                       check_in=check_in, check_out=check_out, guests=guests)

            # Проверяем доступность номера
            cursor.execute("""
                SELECT ID_Бронирования FROM Бронирования 
                WHERE ID_Номера = ? 
                AND Статус IN ('Подтверждено', 'Заселен')
                AND NOT (Дата_выезда <= ? OR Дата_заезда >= ?)
            """, (room_id, check_in, check_out))

            if cursor.fetchone():
                flash('Номер недоступен на выбранные даты', 'danger')
                return render_template('booking.html', room=room,
                                       check_in=check_in, check_out=check_out, guests=guests)

            cursor.execute("SELECT COUNT(*) FROM Бронирования")
            booking_count = cursor.fetchone()[0] + 1
            booking_id = f"BR{booking_count:03d}"

            days = (check_out_date - check_in_date).days
            total_price = days * room['Цена_за_сутки']
            prepayment = total_price * 0.3

            # Создаем бронирование
            cursor.execute("""
                INSERT INTO Бронирования (
                    ID_Бронирования, ID_Клиента, ID_Номера, 
                    Дата_бронирования, Дата_заезда, Дата_выезда, 
                    Количество_гостей, Статус, Предоплата
                ) VALUES (?, ?, ?, date('now'), ?, ?, ?, 'Подтверждено', ?)
            """, (booking_id, session['client_id'], room_id,
                  check_in, check_out, guests, prepayment))

            # Обновляем статус номера
            if check_in_date == today or check_in_date == today + timedelta(days=1):
                cursor.execute("UPDATE Номера SET Статус = 'Занят' WHERE ID_Номера = ?", (room_id,))
            else:
                cursor.execute("UPDATE Номера SET Статус = 'Будет занят' WHERE ID_Номера = ?", (room_id,))

            # Создаем счет
            cursor.execute("SELECT COUNT(*) FROM Счета")
            invoice_count = cursor.fetchone()[0] + 1
            invoice_id = f"INV{invoice_count:03d}"

            cursor.execute("""
                INSERT INTO Счета (
                    ID_Счета, ID_Бронирования, Дата_выставления, 
                    Сумма_проживание, Оплачено
                ) VALUES (?, ?, date('now'), ?, 0)
            """, (invoice_id, booking_id, total_price))

            conn.commit()
            conn.close()

            flash('Бронирование успешно создано!', 'success')
            return redirect(url_for('booking_confirmation', booking_id=booking_id))

        conn.close()

        check_in = request.args.get('check_in', datetime.now().strftime('%Y-%m-%d'))
        check_out = request.args.get('check_out', (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d'))
        guests = request.args.get('guests', 1, type=int)

        return render_template('booking.html', room=room,
                               check_in=check_in, check_out=check_out, guests=guests)

    except Exception as e:
        flash(f'Ошибка при создании бронирования: {str(e)}', 'danger')
        return redirect(url_for('room_detail', room_id=room_id))


# Подтверждение бронирования
@app.route('/booking/confirmation/<string:booking_id>')
@login_required
def booking_confirmation(booking_id):
    try:
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT b.*, n.Номер_Комнаты, n.Категория, n.Цена_за_сутки,
                   CAST(JULIANDAY(b.Дата_выезда) - JULIANDAY(b.Дата_заезда) AS INTEGER) as days_count,
                   c.Фамилия, c.Имя, c.Отчество
            FROM Бронирования b
            JOIN Номера n ON b.ID_Номера = n.ID_Номера
            JOIN Клиенты c ON b.ID_Клиента = c.ID_Клиента
            WHERE b.ID_Бронирования = ? AND b.ID_Клиента = ?
        """, (booking_id, session['client_id']))

        booking = cursor.fetchone()
        conn.close()

        if not booking:
            flash('Бронирование не найдено', 'danger')
            return redirect(url_for('profile'))

        booking_dict = dict(booking)
        days = booking_dict.get('days_count', 0)
        if days <= 0:
            days = 1
        booking_dict['total_price'] = days * booking_dict.get('Цена_за_сутки', 0)

        return render_template('confirmation.html', booking=booking_dict)

    except Exception as e:
        flash(f'Ошибка при загрузке подтверждения: {str(e)}', 'danger')
        return redirect(url_for('profile'))


# Отмена бронирования
@app.route('/booking/cancel/<string:booking_id>')
@login_required
def cancel_booking(booking_id):
    try:
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT Дата_заезда, ID_Номера FROM Бронирования 
            WHERE ID_Бронирования = ? AND ID_Клиента = ?
        """, (booking_id, session['client_id']))

        booking = cursor.fetchone()

        if not booking:
            flash('Бронирование не найдено', 'danger')
            conn.close()
            return redirect(url_for('profile'))

        check_in = datetime.strptime(booking['Дата_заезда'], '%Y-%m-%d').date()
        today = datetime.now().date()

        if check_in <= today:
            flash('Невозможно отменить бронирование в день заезда или позже', 'danger')
            conn.close()
            return redirect(url_for('profile'))

        # Обновляем статус бронирования
        cursor.execute("""
            UPDATE Бронирования 
            SET Статус = 'Отменено' 
            WHERE ID_Бронирования = ?
        """, (booking_id,))

        # Проверяем, есть ли другие активные брони на этот номер
        cursor.execute("""
            SELECT COUNT(*) FROM Бронирования 
            WHERE ID_Номера = ? AND Статус IN ('Подтверждено', 'Заселен')
        """, (booking['ID_Номера'],))

        if cursor.fetchone()[0] == 0:
            cursor.execute("UPDATE Номера SET Статус = 'Свободен' WHERE ID_Номера = ?", (booking['ID_Номера'],))
        else:
            # Если есть другие брони, нужно пересчитать статус
            sync_room_statuses()

        conn.commit()
        conn.close()

        flash('Бронирование успешно отменено', 'success')
        return redirect(url_for('profile'))

    except Exception as e:
        flash(f'Ошибка при отмене бронирования: {str(e)}', 'danger')
        return redirect(url_for('profile'))


# Контакты
@app.route('/contact')
def contact():
    return render_template('contact.html')


# ============= АДМИН-ПАНЕЛЬ =============

# Главная админ-панели
@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    sync_room_statuses()
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM Клиенты")
    total_clients = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM Номера")
    total_rooms = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM Номера WHERE Статус = 'Свободен'")
    free_rooms = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM Бронирования WHERE Статус IN ('Подтверждено', 'Заселен')")
    active_bookings = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*) FROM Бронирования 
        WHERE Статус = 'Подтверждено' AND Дата_заезда >= date('now')
    """)
    upcoming_bookings = cursor.fetchone()[0]

    # Статистика по категориям номеров
    cursor.execute("""
        SELECT Категория, 
               COUNT(*) as total,
               SUM(CASE WHEN Статус = 'Свободен' THEN 1 ELSE 0 END) as free
        FROM Номера
        GROUP BY Категория
    """)
    room_status_stats = cursor.fetchall()

    # Ближайшие заезды
    cursor.execute("""
        SELECT b.Дата_заезда, c.Фамилия, c.Имя, n.Номер_Комнаты
        FROM Бронирования b
        JOIN Клиенты c ON b.ID_Клиента = c.ID_Клиента
        JOIN Номера n ON b.ID_Номера = n.ID_Номера
        WHERE b.Статус = 'Подтверждено' 
        AND b.Дата_заезда BETWEEN date('now') AND date('now', '+2 days')
        ORDER BY b.Дата_заезда
        LIMIT 5
    """)
    upcoming_checkins = cursor.fetchall()

    # Статистика бронирований по категориям
    cursor.execute("""
        SELECT n.Категория, COUNT(*) as count
        FROM Бронирования b
        JOIN Номера n ON b.ID_Номера = n.ID_Номера
        WHERE b.Статус != 'Отменено'
        GROUP BY n.Категория
        ORDER BY count DESC
    """)
    booking_stats = cursor.fetchall()

    # Финансовая статистика
    cursor.execute("""
        SELECT 
            SUM(Предоплата) as total_prepaid,
            SUM(CASE WHEN Статус = 'Подтверждено' THEN Предоплата * 7/3 ELSE 0 END) as total_remaining,
            SUM(CASE WHEN Статус != 'Отменено' THEN Предоплата * 10/3 ELSE 0 END) as total_amount
        FROM Бронирования
        WHERE Статус != 'Отменено'
    """)
    financial = cursor.fetchone()
    if financial and financial['total_prepaid'] is None:
        financial = {'total_prepaid': 0, 'total_remaining': 0, 'total_amount': 0}

    # Популярные номера
    cursor.execute("""
        SELECT n.Номер_Комнаты, n.Категория, COUNT(b.ID_Бронирования) as booking_count
        FROM Номера n
        LEFT JOIN Бронирования b ON n.ID_Номера = b.ID_Номера AND b.Статус != 'Отменено'
        GROUP BY n.ID_Номера
        ORDER BY booking_count DESC
        LIMIT 5
    """)
    popular_rooms = cursor.fetchall()

    # Свежие бронирования
    cursor.execute("""
        SELECT b.*, n.Номер_Комнаты, c.Фамилия, c.Имя
        FROM Бронирования b
        JOIN Номера n ON b.ID_Номера = n.ID_Номера
        JOIN Клиенты c ON b.ID_Клиента = c.ID_Клиента
        ORDER BY b.Дата_бронирования DESC
        LIMIT 8
    """)
    recent_bookings = cursor.fetchall()

    conn.close()

    occupied_rooms = total_rooms - free_rooms

    return render_template('admin/dashboard.html',
                           total_clients=total_clients,
                           total_rooms=total_rooms,
                           free_rooms=free_rooms,
                           occupied_rooms=occupied_rooms,
                           active_bookings=active_bookings,
                           upcoming_bookings=upcoming_bookings,
                           room_status_stats=room_status_stats,
                           upcoming_checkins=upcoming_checkins,
                           booking_stats=booking_stats,
                           financial=financial,
                           popular_rooms=popular_rooms,
                           recent_bookings=recent_bookings)


# Выход из админ-панели
@app.route('/admin/logout')
def admin_logout():
    session.clear()
    flash('Вы вышли из админ-панели', 'info')
    return redirect(url_for('login'))


# Управление номерами
@app.route('/admin/rooms')
@admin_required
def admin_rooms():
    sync_room_statuses()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM Номера ORDER BY Номер_Комнаты")
    rooms = cursor.fetchall()
    conn.close()
    return render_template('admin/rooms.html', rooms=rooms)


@app.route('/admin/room/add', methods=['GET', 'POST'])
@admin_required
def admin_room_add():
    if request.method == 'POST':
        try:
            room_number = request.form['room_number']
            category = request.form['category']
            capacity = int(request.form['capacity'])
            price = float(request.form['price'])
            floor = int(request.form['floor'])
            status = request.form['status']

            conn = get_db()
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) FROM Номера")
            count = cursor.fetchone()[0] + 1
            room_id = f"RM{count:03d}"

            cursor.execute("""
                INSERT INTO Номера (ID_Номера, Номер_Комнаты, Категория, Вместимость, Цена_за_сутки, Статус, Этаж)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (room_id, room_number, category, capacity, price, status, floor))

            conn.commit()
            conn.close()
            flash('Номер успешно добавлен', 'success')
            return redirect(url_for('admin_rooms'))
        except Exception as e:
            flash(f'Ошибка: {str(e)}', 'danger')

    return render_template('admin/room_form.html')


@app.route('/admin/room/edit/<string:room_id>', methods=['GET', 'POST'])
@admin_required
def admin_room_edit(room_id):
    conn = get_db()
    cursor = conn.cursor()

    if request.method == 'POST':
        try:
            room_number = request.form['room_number']
            category = request.form['category']
            capacity = int(request.form['capacity'])
            price = float(request.form['price'])
            floor = int(request.form['floor'])
            status = request.form['status']

            cursor.execute("""
                UPDATE Номера 
                SET Номер_Комнаты=?, Категория=?, Вместимость=?, Цена_за_сутки=?, Статус=?, Этаж=?
                WHERE ID_Номера=?
            """, (room_number, category, capacity, price, status, floor, room_id))

            conn.commit()
            flash('Номер успешно обновлен', 'success')
            return redirect(url_for('admin_rooms'))
        except Exception as e:
            flash(f'Ошибка: {str(e)}', 'danger')

    cursor.execute("SELECT * FROM Номера WHERE ID_Номера = ?", (room_id,))
    room = cursor.fetchone()
    conn.close()

    return render_template('admin/room_form.html', room=room)


@app.route('/admin/room/delete/<string:room_id>')
@admin_required
def admin_room_delete(room_id):
    try:
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT COUNT(*) FROM Бронирования 
            WHERE ID_Номера = ? AND Статус IN ('Подтверждено', 'Заселен')
        """, (room_id,))

        if cursor.fetchone()[0] > 0:
            flash('Нельзя удалить номер с активными бронированиями', 'danger')
        else:
            cursor.execute("DELETE FROM Номера WHERE ID_Номера = ?", (room_id,))
            conn.commit()
            flash('Номер удален', 'success')

        conn.close()
    except Exception as e:
        flash(f'Ошибка: {str(e)}', 'danger')

    return redirect(url_for('admin_rooms'))


# Управление бронированиями
@app.route('/admin/bookings')
@admin_required
def admin_bookings():
    sync_room_statuses()
    status = request.args.get('status', '')

    conn = get_db()
    cursor = conn.cursor()

    query = """
        SELECT b.*, n.Номер_Комнаты, n.Категория, c.Фамилия, c.Имя, c.Телефон
        FROM Бронирования b
        JOIN Номера n ON b.ID_Номера = n.ID_Номера
        JOIN Клиенты c ON b.ID_Клиента = c.ID_Клиента
    """
    params = []

    if status:
        query += " WHERE b.Статус = ?"
        params.append(status)

    query += " ORDER BY b.Дата_заезда DESC"

    cursor.execute(query, params)
    bookings = cursor.fetchall()

    conn.close()
    return render_template('admin/bookings.html', bookings=bookings, selected_status=status)


@app.route('/admin/booking/update/<string:booking_id>', methods=['POST'])
@admin_required
def admin_booking_update(booking_id):
    status = request.form['status']

    try:
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("SELECT ID_Номера, Дата_заезда, Дата_выезда FROM Бронирования WHERE ID_Бронирования = ?",
                       (booking_id,))
        booking = cursor.fetchone()

        cursor.execute("UPDATE Бронирования SET Статус = ? WHERE ID_Бронирования = ?", (status, booking_id))

        today = datetime.now().date()
        check_in_date = datetime.strptime(booking['Дата_заезда'], '%Y-%m-%d').date()

        if status in ['Отменено', 'Завершено']:
            # Проверяем, есть ли другие активные брони
            cursor.execute("""
                SELECT COUNT(*) FROM Бронирования 
                WHERE ID_Номера = ? AND Статус IN ('Подтверждено', 'Заселен')
            """, (booking['ID_Номера'],))
            if cursor.fetchone()[0] == 0:
                cursor.execute("UPDATE Номера SET Статус = 'Свободен' WHERE ID_Номера = ?", (booking['ID_Номера'],))
        elif status == 'Заселен':
            cursor.execute("UPDATE Номера SET Статус = 'Занят' WHERE ID_Номера = ?", (booking['ID_Номера'],))
        elif status == 'Подтверждено':
            if check_in_date == today or check_in_date == today + timedelta(days=1):
                cursor.execute("UPDATE Номера SET Статус = 'Занят' WHERE ID_Номера = ?", (booking['ID_Номера'],))
            else:
                cursor.execute("UPDATE Номера SET Статус = 'Будет занят' WHERE ID_Номера = ?", (booking['ID_Номера'],))

        conn.commit()
        conn.close()
        flash('Статус бронирования обновлен', 'success')
    except Exception as e:
        flash(f'Ошибка: {str(e)}', 'danger')

    return redirect(url_for('admin_bookings'))


# Управление клиентами
@app.route('/admin/clients')
@admin_required
def admin_clients():
    search = request.args.get('search', '')

    conn = get_db()
    cursor = conn.cursor()

    if search:
        cursor.execute("""
            SELECT * FROM Клиенты 
            WHERE Фамилия LIKE ? OR Имя LIKE ? OR Телефон LIKE ?
            ORDER BY Фамилия
        """, (f'%{search}%', f'%{search}%', f'%{search}%'))
    else:
        cursor.execute("SELECT * FROM Клиенты ORDER BY Фамилия")

    clients = cursor.fetchall()
    conn.close()

    return render_template('admin/clients.html', clients=clients, search=search)


@app.route('/admin/client/<string:client_id>')
@admin_required
def admin_client_detail(client_id):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM Клиенты WHERE ID_Клиента = ?", (client_id,))
    client = cursor.fetchone()

    cursor.execute("""
        SELECT b.*, n.Номер_Комнаты, n.Категория
        FROM Бронирования b
        JOIN Номера n ON b.ID_Номера = n.ID_Номера
        WHERE b.ID_Клиента = ?
        ORDER BY b.Дата_заезда DESC
    """, (client_id,))
    bookings = cursor.fetchall()

    conn.close()

    return render_template('admin/client_detail.html', client=client, bookings=bookings)


# Отчеты
@app.route('/admin/reports')
@admin_required
def admin_reports():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT Категория, COUNT(*) as count, AVG(Цена_за_сутки) as avg_price
        FROM Номера
        GROUP BY Категория
    """)
    room_stats = cursor.fetchall()

    cursor.execute("""
        SELECT strftime('%Y-%m', Дата_заезда) as month, COUNT(*) as count
        FROM Бронирования
        WHERE Статус != 'Отменено'
        GROUP BY month
        ORDER BY month DESC
        LIMIT 6
    """)
    monthly_stats = cursor.fetchall()

    cursor.execute("""
        SELECT SUM(Предоплата) as total_prepaid, COUNT(*) as total_bookings
        FROM Бронирования
        WHERE Статус != 'Отменено'
    """)
    financial = cursor.fetchone()
    if financial and financial['total_prepaid'] is None:
        financial = {'total_prepaid': 0, 'total_bookings': 0}

    conn.close()

    return render_template('admin/reports.html',
                           room_stats=room_stats,
                           monthly_stats=monthly_stats,
                           financial=financial)


if __name__ == '__main__':
    if not os.path.exists(DB_NAME):
        print("База данных не найдена. Запустите db.py для создания базы данных.")
        print("Выполните команду: python db.py")
    else:
        # Синхронизация статусов при запуске
        sync_room_statuses()
        app.run(debug=True, host='0.0.0.0', port=5000)