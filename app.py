from flask import Flask, render_template, request, redirect, url_for, jsonify
import mysql.connector
import board
import busio
import adafruit_ads1x15.ads1115 as ADS
from adafruit_ads1x15.analog_in import AnalogIn
import RPi.GPIO as GPIO
import threading
import time
import os
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

app = Flask(__name__)

# Database config
db_config = {
    "host": "localhost",
    "user": "pi",
    "password": "pi",
    "database": "pigrow"
}

class Sensor:
    def __init__(self, sensor_id, analog_input, pump_pin, name):
        self.sensor_id = sensor_id
        self.analog_input = analog_input
        self.pump_pin = pump_pin
        self.name = name
        self.threshold_voltage = 1.5
        self.manual_override = False
        self.current_mode = "auto"
        GPIO.setup(pump_pin, GPIO.OUT)
        GPIO.output(pump_pin, GPIO.HIGH)
        self.start_reading()

    def start_reading(self):
        threading.Thread(target=self.read_sensor_data, daemon=True).start()

    def read_sensor_data(self):
        while True:
            try:
                raw_data = self.analog_input.value
                voltage = self.analog_input.voltage
                self.save_to_db(raw_data, voltage)
                self.control_pump(voltage)
                time.sleep(1)
            except Exception as e:
                logging.error(f"Sensor {self.sensor_id} ({self.name}) error: {e}")

    def save_to_db(self, raw_data, voltage):
        with mysql.connector.connect(**db_config) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO soil (sensor_id, raw_data, voltage) VALUES (%s, %s, %s)",
                (self.sensor_id, raw_data, voltage)
            )
            conn.commit()

    def control_pump(self, voltage):
        if not self.manual_override and self.current_mode == "auto":
            if voltage < self.threshold_voltage:
                GPIO.output(self.pump_pin, GPIO.LOW)
                logging.info(f"Sensor {self.sensor_id} ({self.name}) - Pump ON")
            else:
                GPIO.output(self.pump_pin, GPIO.HIGH)
                logging.info(f"Sensor {self.sensor_id} ({self.name}) - Pump OFF")

# Initialize I2C and ADS1115
i2c = busio.I2C(board.SCL, board.SDA)
ads = ADS.ADS1115(i2c)

# Define sensors and pumps
sensor_names = ["Sensor 1", "Sensor 2", "Sensor 3", "Sensor 4"]
sensors = [
    Sensor(0, AnalogIn(ads, ADS.P0), 26, sensor_names[0]),
    Sensor(1, AnalogIn(ads, ADS.P1), 19, sensor_names[1]),
    Sensor(2, AnalogIn(ads, ADS.P2), 13, sensor_names[2]),
    Sensor(3, AnalogIn(ads, ADS.P3), 6, sensor_names[3])
]

@app.route('/')
def index():
    with mysql.connector.connect(**db_config) as conn:
        cursor = conn.cursor(dictionary=True)
        latest_data = []
        for sensor in sensors:
            cursor.execute(
                "SELECT raw_data, voltage FROM soil WHERE sensor_id = %s ORDER BY id DESC LIMIT 1",
                (sensor.sensor_id,)
            )
            latest_data.append(cursor.fetchone() or {"raw_data": "N/A", "voltage": "N/A"})
    return render_template(
        'page.html',
        latest_data=latest_data,
        threshold_voltages=[sensor.threshold_voltage for sensor in sensors],
        current_modes=[sensor.current_mode for sensor in sensors],
        manual_overrides=[sensor.manual_override for sensor in sensors],
        sensor_names=sensor_names
    )

@app.route('/control', methods=['POST'])
def control():
    sensor_id = int(request.form['sensor_id'])
    action = request.form['action']
    sensor = sensors[sensor_id]
    if action == 'on':
        sensor.manual_override = True
        sensor.current_mode = "manual"
        GPIO.output(sensor.pump_pin, GPIO.LOW)
    elif action == 'off':
        sensor.manual_override = True
        sensor.current_mode = "manual"
        GPIO.output(sensor.pump_pin, GPIO.HIGH)
    elif action == 'auto':
        sensor.manual_override = False
        sensor.current_mode = "auto"
    return redirect(url_for('index'))

@app.route('/set_threshold', methods=['POST'])
def set_threshold():
    sensor_id = int(request.form['sensor_id'])
    sensors[sensor_id].threshold_voltage = float(request.form['threshold'])
    return redirect(url_for('index'))

@app.route('/data')
def data():
    with mysql.connector.connect(**db_config) as conn:
        cursor = conn.cursor(dictionary=True)
        data = []
        for sensor in sensors:
            cursor.execute(
                "SELECT raw_data, voltage FROM soil WHERE sensor_id = %s ORDER BY id DESC LIMIT 1",
                (sensor.sensor_id,)
            )
            data.append(cursor.fetchone() or {"raw_data": "N/A", "voltage": "N/A"})
    return jsonify(data)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
