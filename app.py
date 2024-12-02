from flask import Flask, render_template, request, redirect, url_for, jsonify
import mysql.connector
import board
import busio
import adafruit_ads1x15.ads1115 as ADS
from adafruit_ads1x15.analog_in import AnalogIn
import RPi.GPIO as GPIO
import threading
import time

app = Flask(__name__)

# Initialize the I2C interface
i2c = busio.I2C(board.SCL, board.SDA)

# Create an ADS1115 object
ads = ADS.ADS1115(i2c)
ads.gain = 1

# Define the analog input channel
channel0 = AnalogIn(ads, ADS.P0)

# MariaDB connection details
db_config = {
    "host": "localhost",
    "user": "pi",
    "password": "pi",
    "database": "pigrow"
}

# GPIO setup for the relay (Pin 26 as an example)
RELAY_PIN = 26
GPIO.setmode(GPIO.BCM)
GPIO.setup(RELAY_PIN, GPIO.OUT)
GPIO.output(RELAY_PIN, GPIO.HIGH)

# Threshold value for when to turn the pump on
threshold_voltage = 1.5

# Manual override flag
manual_override = False

# Current mode (auto or manual)
current_mode = "auto"

def read_sensor_data():
    global manual_override, current_mode
    while True:
        try:
            raw_value = channel0.value
            voltage_value = channel0.voltage

            # Save data into MariaDB immediately for real-time access
            conn = mysql.connector.connect(**db_config)
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO soil (raw_data, voltage) VALUES (%s, %s)",
                (raw_value, voltage_value)
            )
            conn.commit()
            cursor.close()
            conn.close()

            print(f"Raw Data: {raw_value}, Voltage: {voltage_value}")

            if not manual_override:
                # Check if the voltage is above the threshold to control the relay
                if voltage_value > threshold_voltage:
                    GPIO.output(RELAY_PIN, GPIO.LOW)  # Turn the pump on
                    print("Pump ON - Soil moisture low")
                else:
                    GPIO.output(RELAY_PIN, GPIO.HIGH)  # Ensure the pump is off
                    print("Pump OFF - Soil moisture sufficient")

            time.sleep(1)  # Additional delay before the next loop iteration

        except OSError as os_err:
            print(f"OS Error: {os_err}")
        except mysql.connector.Error as db_err:
            print(f"Database Error: {db_err}")
        except Exception as e:
            print(f"Error: {e}")

# Start the sensor reading in a separate thread
sensor_thread = threading.Thread(target=read_sensor_data)
sensor_thread.daemon = True
sensor_thread.start()

@app.route('/')
def index():
    try:
        # Connect to the database and fetch the latest data
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT raw_data, voltage FROM soil ORDER BY id DESC LIMIT 1")
        latest_data = cursor.fetchone()

        cursor.close()
        conn.close()

        return render_template('index.html', latest_data=latest_data, threshold_voltage=threshold_voltage, current_mode=current_mode)
    except mysql.connector.Error as db_err:
        return f"Database Error: {db_err}"
    except Exception as e:
        return f"Error: {e}"

@app.route('/control', methods=['POST'])
def control():
    global manual_override, current_mode
    action = request.form.get('action')
    if action == 'on':
        manual_override = True
        current_mode = "manual"
        GPIO.output(RELAY_PIN, GPIO.LOW)
    elif action == 'off':
        manual_override = True
        current_mode = "manual"
        GPIO.output(RELAY_PIN, GPIO.HIGH)
    elif action == 'auto':
        manual_override = False
        current_mode = "auto"
    return redirect(url_for('index'))

@app.route('/set_threshold', methods=['POST'])
def set_threshold():
    global threshold_voltage
    threshold_voltage = float(request.form.get('threshold'))
    return redirect(url_for('index'))

@app.route('/data')
def data():
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT raw_data, voltage FROM soil ORDER BY id DESC LIMIT 1")
        data = cursor.fetchall()
        cursor.close()
        conn.close()

        return {"data": data}
    except mysql.connector.Error as db_err:
        return {"error": f"Database Error: {db_err}"}, 500
    except Exception as e:
        return {"error": f"Error: {e}"}, 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
