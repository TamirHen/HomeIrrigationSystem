from flask import Flask
from flask import request
from flask import jsonify
from flask_api import FlaskAPI
import RPi.GPIO as GPIO
import time
from datetime import datetime, date
import json
from datetime import datetime
import threading
import numpy as np
import schedule
from gpiozero import MCP3008


# out18 - water_on
# out24 - water_close

GPIO.setmode(GPIO.BCM)

app = FlaskAPI(__name__)
app.config['JSON_SORT_KEYS'] = False

state = False
week = {
    "sunday" : False,
    "monday" : False,
    "tuesday" : False,
    "wednesday" : False,
    "thursday" : False,
    "friday" : False,
    "saturday" : False,
    "firstRoundStart": None,
    "firstRoundEnd": None,
    "secondRoundStart": None,
    "secondRoundEnd": None,
    "thirdRoundStart": None,
    "thirdRoundEnd": None,
}
week_day_int = [False, False, False, False, False, False, False]
is_irrigate_by_moisture = False

@app.route('/irrigate_by_seconds/<int:seconds>', methods=["POST"])
def irrigate_by_seconds(seconds):
    new_thread = threading.Thread(target=irrigate_by_seconds_thread, args=(seconds,))
    new_thread.start()
    return { }


@app.route('/irrigate_by_minutes/<int:minutes>', methods=["POST"])
def irrigate_by_minutes(minutes):
    seconds = minutes * 60
    new_thread = threading.Thread(target=irrigate_by_seconds_thread, args=(seconds,))
    new_thread.start()
    return { }

@app.route('/start_irrigate', methods=["POST"])
def start_irrigate():
    water_on()
    return { }

@app.route('/stop_irrigate', methods=["POST"])
def stop_irrigate():
    water_off()
    return { }


@app.route('/get_week', methods=["GET"])
def get_week():
    return jsonify(week)



def irrigate_by_seconds_thread(seconds):
    water_on()
    time.sleep(seconds)
    water_off()


@app.route('/get_state', methods=["GET"])
def get_state():
    global state
    return jsonify(state)



@app.route('/update_week', methods=["POST"])
def create_weekly_irrigation():
    global week
    global week_day_int
    water_off() # firstable close water for safety reasons
    schedule.clear("Round-1")
    schedule.clear("Round-2")
    schedule.clear("Round-3")
    week = request.get_json()

    week_day_int[6]=week["sunday"] # setup days in integers for schedule_irrigation
    week_day_int[0]=week["monday"]
    week_day_int[1]=week["tuesday"]
    week_day_int[2]=week["wednesday"]
    week_day_int[3]=week["thursday"]
    week_day_int[4]=week["friday"]
    week_day_int[5]=week["saturday"]

    check_irrigation_every_day()
    return jsonify(week)


def check_irrigation_every_day():
    now = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
    if(week["firstRoundStart"] != None and week["firstRoundEnd"] != None):
        print("start new thread to irrigate every --true-- day at round 1 time")
        new_thread1 = threading.Thread(target=check_round_every_day_thread, args=(1,))
        new_thread1.setName("Round-1 " + now)
        new_thread1.start()
    if(week["secondRoundStart"] != None and week["secondRoundEnd"] != None):
        print("start new thread to irrigate every --true-- day at round 2 time")
        new_thread2 = threading.Thread(target=check_round_every_day_thread, args=(2,))
        new_thread2.setName("Round-2 " + now)
        new_thread2.start()
    if(week["thirdRoundStart"] != None and week["thirdRoundEnd"] != None):
        print("start new thread to irrigate every --true-- day at round 3 time")
        new_thread3 = threading.Thread(target=check_round_every_day_thread, args=(3,))
        new_thread3.setName("Round-3 " + now)
        new_thread3.start()


def check_round_every_day_thread(iround):
    if(iround==1):
        schedule.every().day.at(week["firstRoundStart"]).do(schedule_irrigation, iround).tag("Round-1")
        while 1:
            schedule.run_pending()
            time.sleep(1)
    if(iround==2):
        schedule.every().day.at(week["secondRoundStart"]).do(schedule_irrigation, iround).tag("Round-2")
        while 1:
            schedule.run_pending()
            time.sleep(1)
    if(iround==3):
        schedule.every().day.at(week["thirdRoundStart"]).do(schedule_irrigation, iround).tag("Round-3")
        while 1:
            schedule.run_pending()
            time.sleep(1)


def schedule_irrigation(iround):
    if(week_day_int[datetime.today().weekday()] == True):  #check if needs to irrigate today.
        if(iround==1):
            round_time_start = week["firstRoundStart"]
            round_time_end = week["firstRoundEnd"]
        elif(iround==2):
            round_time_start = week["secondRoundStart"]
            round_time_end = week["secondRoundEnd"]
        else:
            round_time_start = week["thirdRoundStart"]
            round_time_end = week["thirdRoundEnd"]

        start_time = datetime.strptime(round_time_start, '%H:%M:%S').time()
        end_time = datetime.strptime(round_time_end, '%H:%M:%S').time()
        result = convert_to_seconds_in_integer(start_time, end_time)

        water_on()
        time.sleep(result)
        water_off()

def convert_to_seconds_in_integer(start_time, end_time):
    time_to_irrigate = datetime.combine(date.today(), end_time) - datetime.combine(date.today(), start_time)
    (h, m, s) = str(time_to_irrigate).split(':')
    return int(h) * 3600 + int(m) * 60 + int(s)


@app.route('/print_running_threads', methods=["GET"])
def print_running_threads():
    print()
    print(threading.enumerate())
    print()
    return { }


#the pi connected to the mcp3008 through SPI port
#the data-in of the mcp3008 is on channel 5
@app.route('/irrigate_by_moisture', methods=["POST"])
def irrigate_by_moisture():
    irrigate_level_bars = request.get_json()
    if irrigate_level_bars["is_irrigate_by_moisture"] == True:
        new_thread = threading.Thread(target=irrigate_by_moisture_new_thread, args=(irrigate_level_bars,))
        new_thread.start()
    else:
        stop_irrigate_by_moisture()

    return {}



def irrigate_by_moisture_new_thread(irrigate_level_bars):
    global is_irrigate_by_moisture
    global state
    is_irrigate_by_moisture = True
    while is_irrigate_by_moisture==True: # after calling irrigate_by_moisture this mode is on all the time unless someone canceled it
        if MCP3008.readadc(5) < int(irrigate_level_bars["low_level"]): # if moisture level too low start irrigate
            while MCP3008.readadc(5) < int(irrigate_level_bars["high_level"]):
                if state == False:
                    start_irrigate()
                time.sleep(30)

        # else just make sure the watering is off and wait 8 hours for next check
        stop_irrigate()
        time.sleep(60*60*8)


@app.route('/stop_irrigate_by_moisture', methods=["POST"])
def stop_irrigate_by_moisture():
    global is_irrigate_by_moisture
    is_irrigate_by_moisture = False


def water_on():
    global state
    GPIO.setup(18, GPIO.OUT)
    state = True
    time.sleep(2)
    GPIO.cleanup(18)

def water_off():
    global state
    GPIO.setup(24, GPIO.OUT)
    state = False
    time.sleep(2)
    GPIO.cleanup(24)


if __name__ == "__main__":
    app.run()