# app.py
from flask import Flask, render_template, request, redirect, url_for, flash, session
from functools import wraps
import sqlite3
from datetime import datetime, timedelta
import os

app = Flask(__name__)
app.secret_key = 'your-secret-key-here-change-in-production'
# Добавьте конфигурацию для загрузки файлов
app.config['UPLOAD_FOLDER'] = 'static/images/rooms'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max

DB_NAME = "hotel_management.db"

def init_uploads():
    upload_folder = os.path.join('static', 'images', 'rooms')
    if not os.path.exists(upload_folder):
        os.makedirs(upload_folder)
        print(f"Создана папка: {upload_folder}")

# Вызовите при запуске
init_uploads()


# app.py - обновленный context_processor

@app.context_processor
def utility_processor():
    def get_room_image(room_number):
        """Возвращает путь к изображению по номеру комнаты"""
        room_number_str = str(room_number)

        # Проверяем существование файла с разными расширениями
        extensions = ['.jpg', '.jpeg', '.png', '.webp', '.JPG', '.JPEG', '.PNG', '.WEBP']

        for ext in extensions:
            filename = f"{room_number_str}{ext}"
            full_path = os.path.join('static', 'images', 'rooms', filename)
            if os.path.exists(full_path):
                return url_for('static', filename=f'images/rooms/{filename}')

        # Если не нашли изображение, возвращаем заглушку
        return url_for('static', filename='images/rooms/default.jpg')

    def get_room_image_extra(room_number, index):
        """Возвращает путь к дополнительному изображению по номеру комнаты и индексу"""
        room_number_str = str(room_number)

        # Возможные форматы имен для дополнительных фото
        possible_formats = [
            f"{room_number_str}-{index}",  # 101-1
            f"{room_number_str}_{index}",  # 101_1
            f"{room_number_str} {index}",  # 101 1
            f"{room_number_str}a{index}",  # 101a1
            f"{room_number_str}_{index:02d}",  # 101_01
        ]

        extensions = ['.jpg', '.jpeg', '.png', '.webp', '.JPG', '.JPEG', '.PNG', '.WEBP']

        for format_name in possible_formats:
            for ext in extensions:
                filename = f"{format_name}{ext}"
                full_path = os.path.join('static', 'images', 'rooms', filename)
                if os.path.exists(full_path):
                    return url_for('static', filename=f'images/rooms/{filename}')

        # Если дополнительного фото нет, возвращаем основное
        return get_room_image(room_number)

    return {
        'now': datetime.now(),
        'today': datetime.now().date(),
        'timedelta': timedelta,
        'get_room_image': get_room_image,
        'get_room_image_extra': get_room_image_extra
    }

# Декоратор для проверки авторизации
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'client_id' not in session:
            flash('Пожалуйста, войдите в систему', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)

    return decorated_function


# Функция для подключения к БД
def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


# Главная страница
@app.route('/')
def index():
    try:
        conn = get_db()
        cursor = conn.cursor()

        # Получаем все категории номеров для фильтра
        cursor.execute("SELECT DISTINCT Категория FROM Номера ORDER BY Категория")
        categories = [row['Категория'] for row in cursor.fetchall()]

        # Получаем все номера
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
            # Исключаем номера, которые уже забронированы на эти даты
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

        # Получаем все категории для фильтра
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

            # Валидация
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

            # Проверяем, существует ли клиент с таким телефоном
            cursor.execute("SELECT ID_Клиента FROM Клиенты WHERE Телефон = ?", (phone,))
            if cursor.fetchone():
                flash('Клиент с таким телефоном уже зарегистрирован', 'danger')
                conn.close()
                return render_template('register.html')

            # Генерируем ID клиента
            cursor.execute("SELECT COUNT(*) FROM Клиенты")
            count = cursor.fetchone()[0] + 1
            client_id = f"CL{count:03d}"

            # Добавляем клиента
            cursor.execute("""
                INSERT INTO Клиенты (ID_Клиента, Фамилия, Имя, Отчество, Телефон, Дата_рождения, Адрес)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (client_id, last_name, first_name, middle_name, phone, birth_date or None, address or None))

            # Создаем запись в таблице пользователей (для авторизации)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS Пользователи (
                    ID INTEGER PRIMARY KEY AUTOINCREMENT,
                    ID_Клиента TEXT UNIQUE,
                    Логин TEXT UNIQUE,
                    Пароль TEXT NOT NULL,
                    FOREIGN KEY (ID_Клиента) REFERENCES Клиенты(ID_Клиента)
                )
            """)

            cursor.execute("""
                INSERT INTO Пользователи (ID_Клиента, Логин, Пароль)
                VALUES (?, ?, ?)
            """, (client_id, phone, password))

            conn.commit()
            conn.close()

            flash('Регистрация успешна! Теперь вы можете войти в систему.', 'success')
            return redirect(url_for('login'))

        except Exception as e:
            flash(f'Ошибка при регистрации: {str(e)}', 'danger')
            return render_template('register.html')

    return render_template('register.html')


# Вход в систему
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        try:
            login_phone = request.form['login']
            password = request.form['password']

            conn = get_db()
            cursor = conn.cursor()

            # Проверяем существование таблицы пользователей
            cursor.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='Пользователи'
            """)

            if not cursor.fetchone():
                cursor.execute("""
                    CREATE TABLE Пользователи (
                        ID INTEGER PRIMARY KEY AUTOINCREMENT,
                        ID_Клиента TEXT UNIQUE,
                        Логин TEXT UNIQUE,
                        Пароль TEXT NOT NULL,
                        FOREIGN KEY (ID_Клиента) REFERENCES Клиенты(ID_Клиента)
                    )
                """)
                conn.commit()

            # Ищем пользователя
            cursor.execute("""
                SELECT u.ID_Клиента, c.Фамилия, c.Имя, c.Отчество, u.Пароль
                FROM Пользователи u
                JOIN Клиенты c ON u.ID_Клиента = c.ID_Клиента
                WHERE u.Логин = ?
            """, (login_phone,))

            user = cursor.fetchone()
            conn.close()

            if user and user['Пароль'] == password:
                session['client_id'] = user['ID_Клиента']
                session['client_name'] = f"{user['Фамилия']} {user['Имя']} {user['Отчество'] or ''}".strip()

                flash(f'Добро пожаловать, {user["Имя"]}!', 'success')

                # Перенаправляем на страницу, с которой пришли
                next_page = request.args.get('next')
                if next_page:
                    return redirect(next_page)
                return redirect(url_for('index'))
            else:
                flash('Неверный логин или пароль', 'danger')

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
# app.py - исправленная функция profile()
@app.route('/profile')
@login_required
def profile():
    try:
        conn = get_db()
        cursor = conn.cursor()

        # Получаем данные клиента
        cursor.execute("""
            SELECT * FROM Клиенты WHERE ID_Клиента = ?
        """, (session['client_id'],))

        client = cursor.fetchone()

        if not client:
            flash('Клиент не найден', 'danger')
            return redirect(url_for('index'))

        # Получаем бронирования клиента
        cursor.execute("""
            SELECT b.*, n.Номер_Комнаты, n.Категория, n.Цена_за_сутки,
                   CAST(JULIANDAY(b.Дата_выезда) - JULIANDAY(b.Дата_заезда) AS INTEGER) as days_count
            FROM Бронирования b
            JOIN Номера n ON b.ID_Номера = n.ID_Номера
            WHERE b.ID_Клиента = ?
            ORDER BY b.Дата_заезда DESC
        """, (session['client_id'],))

        bookings = cursor.fetchall()

        # Вычисляем общую сумму для каждого бронирования
        bookings_with_total = []
        for booking in bookings:
            booking_dict = dict(booking)
            days = booking_dict.get('days_count', 0)
            if days <= 0:
                days = 1
            booking_dict['total_price'] = days * booking_dict.get('Цена_за_сутки', 0)
            # Преобразуем даты в строки для корректного отображения
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

        # Получаем информацию о номере
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

            # Валидация
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

            if guests < 1:
                flash('Количество гостей должно быть не менее 1', 'danger')
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

            # Генерируем ID бронирования
            cursor.execute("SELECT COUNT(*) FROM Бронирования")
            booking_count = cursor.fetchone()[0] + 1
            booking_id = f"BR{booking_count:03d}"

            # Рассчитываем предоплату (30% от стоимости)
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

            # Обновляем статус номера
            cursor.execute("""
                UPDATE Номера 
                SET Статус = 'Будет занят' 
                WHERE ID_Номера = ? AND Статус = 'Свободен'
            """, (room_id,))

            conn.commit()
            conn.close()

            flash('Бронирование успешно создано!', 'success')
            return redirect(url_for('booking_confirmation', booking_id=booking_id))

        conn.close()

        # Получаем параметры из URL
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

        # Проверяем, принадлежит ли бронирование клиенту
        cursor.execute("""
            SELECT Дата_заезда, ID_Номера FROM Бронирования 
            WHERE ID_Бронирования = ? AND ID_Клиента = ?
        """, (booking_id, session['client_id']))

        booking = cursor.fetchone()

        if not booking:
            flash('Бронирование не найдено', 'danger')
            conn.close()
            return redirect(url_for('profile'))

        # Проверяем, можно ли отменить (за 24 часа до заезда)
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

        # Обновляем статус номера
        cursor.execute("""
            UPDATE Номера 
            SET Статус = 'Свободен' 
            WHERE ID_Номера = ?
        """, (booking['ID_Номера'],))

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


if __name__ == '__main__':
    # Проверяем наличие базы данных
    if not os.path.exists(DB_NAME):
        print("База данных не найдена. Запустите db.py для создания базы данных.")
        print("Выполните команду: python db.py")
    else:
        app.run(debug=True, host='0.0.0.0', port=5000)