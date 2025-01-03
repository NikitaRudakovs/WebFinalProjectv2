from flask import Flask, render_template, request, redirect, url_for, session
from db_config import get_connection
from datetime import datetime, timedelta
import os
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from flask import session, redirect, url_for
import logging
logging.basicConfig(level=logging.DEBUG)

app = Flask(__name__)
app.secret_key = '123123123' 


GOOGLE_CREDENTIALS_FILE = 'static\client_secret_1085694552628-oek555aujd9i1enak89fqiamihii4ocl.apps.googleusercontent.com (2).json'
SCOPES = ['https://www.googleapis.com/auth/calendar.events']

@app.route('/google_auth')
def google_auth():
    flow = Flow.from_client_secrets_file(
        GOOGLE_CREDENTIALS_FILE,
        scopes=SCOPES,
        redirect_uri=url_for('google_auth_callback', _external=True)
    )
    authorization_url, state = flow.authorization_url()
    session['state'] = state
    return redirect(authorization_url)

@app.route('/google_auth_callback')
def google_auth_callback():
    state = session['state']
    flow = Flow.from_client_secrets_file(
        GOOGLE_CREDENTIALS_FILE,
        scopes=SCOPES,
        state=state,
        redirect_uri=url_for('google_auth_callback', _external=True)
    )
    flow.fetch_token(authorization_response=request.url)
    credentials = flow.credentials
    session['credentials'] = credentials_to_dict(credentials)
    return redirect(url_for('main'))

def credentials_to_dict(credentials):
    return {
        'token': credentials.token,
        'refresh_token': credentials.refresh_token,
        'token_uri': credentials.token_uri,
        'client_id': credentials.client_id,
        'client_secret': credentials.client_secret,
        'scopes': credentials.scopes
    }

@app.route('/add_event', methods=['POST'])
def add_event():
    if 'credentials' not in session:
        logging.error("No credentials found in session.")
        return redirect(url_for('google_auth'))

    data = request.json
    logging.debug(f"Received data for event creation: {data}")

    ride_id = data.get('ride_id')
    if not ride_id:
        logging.error("Missing ride_id in request.")
        return {"message": "Missing ride_id"}, 400

    try:
        # Fetch ride details
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT
                r.time_of_start,
                r.starting_address,
                r.end_address,
                r.cost,
                r.calculated_time,
                c.Model AS car_name,
                cl.Email AS client_email
            FROM
                ride r
                JOIN Cars c ON r.car_id = c.ID
                JOIN Client cl ON r.client_id = cl.ID
            WHERE
                r.ID = %s
        """, (ride_id,))
        ride_details = cursor.fetchone()
        conn.close()

        if not ride_details:
            logging.error(f"No ride found for ID: {ride_id}")
            return {"message": "Ride not found"}, 404

        logging.debug(f"Fetched ride details: {ride_details}")

        # Build and insert the event
        credentials = Credentials(**session['credentials'])
        service = build('calendar', 'v3', credentials=credentials)

        time_of_start = ride_details['time_of_start'].isoformat()
        duration_minutes = int(ride_details['calculated_time'])
        end_time = (ride_details['time_of_start'] + timedelta(minutes=duration_minutes)).isoformat()

        event = {
            'summary': f"Ride: {ride_details['car_name']}",
            'location': ride_details['starting_address'],
            'description': (
                f"Client Email: {ride_details['client_email']}\n"
                f"Car: {ride_details['car_name']}\n"
                f"Route: {ride_details['starting_address']} - {ride_details['end_address']}\n"
                f"Cost: €{ride_details['cost']}"
            ),
            'start': {
                'dateTime': time_of_start,
                'timeZone': 'Europe/Riga',
            },
            'end': {
                'dateTime': end_time,
                'timeZone': 'Europe/Riga',
            },
        }

        created_event = service.events().insert(calendarId='primary', body=event).execute()
        logging.debug(f"Event created successfully: {created_event}")
        return {"message": "Event created successfully", "event_id": created_event['id']}, 200
    except Exception as e:
        logging.error(f"Error while creating calendar event: {e}")
        return {"message": str(e)}, 500

@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM Client WHERE Email = %s", (email,))
        user = cursor.fetchone()
        conn.close()

        if user and user['Password'] == password:
            session['user_id'] = user['ID']  # Ensure this is set
            return redirect(url_for('main'))
        else:
            return "Invalid credentials", 401
    return render_template('login.html')

@app.route('/main')
def main():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    # Get user info
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT Email, profile_picture FROM Client WHERE ID = %s", (session['user_id'],))
    user = cursor.fetchone()
    conn.close()
    
    user_email = user['Email']
    user_profile_pic = user.get('profile_picture', 'static/user-placeholder.jpg')  # Default if none

    current_datetime = datetime.now()
    days = [(current_datetime + timedelta(days=i)) for i in range(14)]

    hours = list(range(10,24)) + ['00:00']  
    time_slots = []
    current_day = current_datetime.date()

    for day_dt in days:
        date_str = day_dt.strftime("%Y-%m-%d") 
        day_slots = []
        for h in hours:
            if h == '00:00':
                # Midnight of next day
                slot_datetime = (day_dt + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
                hour_str = "00:00"
            else:
                slot_datetime = day_dt.replace(hour=h, minute=0, second=0, microsecond=0)
                hour_str = f"{h:02d}:00"
            is_past = (slot_datetime < current_datetime)

            day_slots.append({
                'time': hour_str,
                'is_past': is_past,
            })

        time_slots.append({
            'date': date_str,
            'slots': day_slots
        })

    return render_template('main.html',
                           user_email=user_email,
                           user_profile_pic=user_profile_pic,
                           time_slots=time_slots)
    
@app.route('/get_cars', methods=['GET'])
def get_cars():
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT ID, Model, Tariff_Euro_per_km FROM Cars")  # Assuming the table is named 'Cars'
    cars = cursor.fetchall()
    conn.close()
    return {'cars': cars}

@app.route('/get_booked_slots', methods=['GET'])
def get_booked_slots():
    car_id = request.args.get('car_id')  # Car ID is passed as a query parameter
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """
        SELECT time_of_start FROM ride WHERE car_id = %s
        """,
        (car_id,)
    )
    booked_slots = [row['time_of_start'].strftime('%Y-%m-%d %H:%M:%S') for row in cursor.fetchall()]
    conn.close()
    return {'booked_slots': booked_slots}

@app.route('/create_appointment', methods=['POST'])
def create_appointment():
    data = request.json
    logging.debug(f"Received request data: {data}")

    user_email = data.get('user_email')  # Get the email
    car_id = data.get('car_id')
    time_of_start = data.get('time_of_start')
    starting_address = data.get('starting_address')
    end_address = data.get('end_address')
    distance = data.get('distance')
    cost = data.get('cost')
    calculated_time = data.get('calculated_time')
    comments = data.get('comments')

    # Validate required fields
    if not all([user_email, car_id, time_of_start, starting_address, end_address, distance, cost, calculated_time]):
        missing_fields = [field for field in ['user_email', 'car_id', 'time_of_start', 'starting_address', 'end_address', 'distance', 'cost', 'calculated_time'] if not data.get(field)]
        logging.error(f"Missing fields: {missing_fields}")
        return {"message": f"Missing required fields: {', '.join(missing_fields)}"}, 400

    # Look up client_id based on user_email
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT ID FROM Client WHERE Email = %s", (user_email,))
        client = cursor.fetchone()
        if not client:
            logging.error(f"No client found with email: {user_email}")
            return {"message": "Client not found"}, 404
        client_id = client['ID']
    except Exception as e:
        logging.error(f"Database error during client lookup: {e}")
        return {"message": str(e)}, 500

    # Insert into the database
    try:
        cursor.execute(
            """
            INSERT INTO ride (client_id, car_id, time_of_start, starting_address, end_address, distance, cost, calculated_time, comments)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (client_id, car_id, time_of_start, starting_address, end_address, distance, cost, calculated_time, comments)
        )
        conn.commit()
        conn.close()
        return {"message": "Appointment created successfully"}, 200
    except Exception as e:
        logging.error(f"Database error during appointment creation: {e}")
        return {"message": str(e)}, 500

        
@app.route('/get_client_id', methods=['GET'])
def get_client_id():
    if 'user_id' in session:
        return {"client_id": session['user_id']}, 200
    return {"message": "User not logged in"}, 401

if __name__ == '__main__':
    app.run(debug=True)
