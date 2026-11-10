# Buero-Klima-Waechter (CircuitPython)
#
# Board:    Adafruit Feather nRF52840 + FeatherWing ESP32 AirLift
#           + Grove Shield FeatherWing (8 Grove-Ports, 3.3 V)
#
# Anschluesse (Grove-Port -> Feather-Pin):
#   Grove A0     Light Sensor v1.2            -> A0
#   Grove D2     LED Socket Kit               -> D5
#   Grove D4     PIR Motion Sensor (adjust.)  -> D9
#   Grove A2     Button                       -> A2
#   Grove A4     Dust Sensor PPD42            -> A4   (braucht 5 V, siehe Anleitung)
#   Grove I2C 1  SCD30 (CO2/Temp/Feuchte)     -> SCL/SDA
#   Grove I2C 2  OLED 128x64                  -> SCL/SDA
#
# ThingSpeak-Felder:
#   1 Temperatur [C]   2 Feuchte [%]   3 Licht [%]   4 CO2 [ppm]
#   5 Staub [Partikel pro 0.01 cf]     6 Person (0/1)
#   7 Alarm (0 = keiner, 1 = Lueften, 2 = Licht, 3 = beides)
#
# Ablauf:
#   - Werte werden laufend gemessen und auf dem Display angezeigt
#   - CO2 oder Staub zu hoch -> LED blinkt schnell, Display: Fenster oeffnen
#   - Licht zu tief          -> LED blinkt langsam, Display: Licht einschalten
#   - Alarme nur, wenn der PIR in den letzten Minuten eine Person erkannt hat
#   - Taste druecken -> Alarme aus, 10 Minuten Pause
#     (gemessen und gesendet wird weiterhin)

import time
import board
import busio
import digitalio
import analogio
import displayio
import terminalio
import keypad
import pulseio
import adafruit_scd30
import adafruit_displayio_ssd1306
from adafruit_display_text import label
from adafruit_esp32spi import adafruit_esp32spi
import adafruit_connection_manager
import adafruit_requests

try:
    from i2cdisplaybus import I2CDisplayBus  # CircuitPython 9 und neuer
except ImportError:
    from displayio import I2CDisplay as I2CDisplayBus  # CircuitPython 8

# ---------------- Konfiguration ----------------
WIFI_SSID = "Sandra"
WIFI_PASSWORD = "98765432"

TS_WRITE_API_KEY = "UT2SQ71BBC4ICWYL"
TS_HTTPS_SERVER = "api.thingspeak.com"

SEND_INTERVAL = 20      # Sekunden zwischen zwei ThingSpeak-Uploads (Free-Lizenz: min. 15)
MEASURE_INTERVAL = 2    # Sekunden zwischen zwei Messungen

CO2_LIMIT = 1000        # ppm, ab hier Lueftungsalarm
DUST_LIMIT = 3000       # Partikel pro 0.01 cf, ab hier Lueftungsalarm (kalibrieren!)
LIGHT_THRESHOLD = 10    # %, darunter Lichtalarm

PAUSE_TIME = 10 * 60    # Sekunden Pause nach Tastendruck
PRESENCE_HOLD = 5 * 60  # Sekunden, die "Person da" nach der letzten Bewegung gilt

DUST_WINDOW = 30        # Sekunden pro Staubmessung (PPD42 braucht mind. 30 s)
DUST_WARMUP = 60        # Sekunden Aufwaermzeit des PPD42
# -----------------------------------------------


# ---------------- Aktoren, Taste, einfache Sensoren ----------------
led = digitalio.DigitalInOut(board.D5)       # Grove D2
led.direction = digitalio.Direction.OUTPUT

# keypad entprellt die Taste und merkt sich Druecke, auch waehrend gesendet wird
button = keypad.Keys((board.A2,), value_when_pressed=True, pull=False)  # Grove A2

pir = digitalio.DigitalInOut(board.D9)       # Grove D4
pir.direction = digitalio.Direction.INPUT

light_sensor = analogio.AnalogIn(board.A0)   # Grove A0

# PPD42: misst, wie lange der Ausgang LOW ist. PulseIn zeichnet die Pulse im Hintergrund auf.
dust_pulses = pulseio.PulseIn(board.A4, maxlen=200, idle_state=True)  # Grove A4


# ---------------- I2C: Display und SCD30 ----------------
displayio.release_displays()
# Tiefe Frequenz, weil der SCD30 "Clock Stretching" braucht
i2c = None
try:
    i2c = busio.I2C(board.SCL, board.SDA, frequency=50000)
except RuntimeError as e:
    print("I2C-Fehler:", e)
    print("-> SCD30 und Display an die I2C-Ports stecken. Weiter ohne I2C-Geraete.")

text_area = None
try:
    display_bus = I2CDisplayBus(i2c, device_address=0x3C)
    display = adafruit_displayio_ssd1306.SSD1306(display_bus, width=128, height=64)
    # Schrift 6x12 Pixel -> 5 Zeilen mit je 21 Zeichen
    text_area = label.Label(terminalio.FONT, text="Starte ...", color=0xFFFFFF,
                            line_spacing=1.0, anchor_point=(0, 0), anchored_position=(0, 0))
    group = displayio.Group()
    group.append(text_area)
    display.root_group = group
except Exception as e:
    print("Display nicht gefunden:", e)


def i2c_scan():
    """Zeigt, welche I2C-Adressen antworten (SCD30 = 0x61, Display = 0x3C)."""
    if i2c is None:
        return
    while not i2c.try_lock():
        pass
    try:
        print("I2C-Geraete gefunden:", [hex(a) for a in i2c.scan()])
    finally:
        i2c.unlock()


i2c_scan()


def show(lines):
    text = "\n".join(lines)
    if text_area is not None and text_area.text != text:
        text_area.text = text


scd30 = None
try:
    scd30 = adafruit_scd30.SCD30(i2c)
    # scd30.temperature_offset = 1.5  # falls die Temperatur zu hoch ist (Eigenerwaermung)
except Exception as e:
    print("SCD30 nicht gefunden:", e)


# ---------------- WLAN und ThingSpeak ----------------
cs = digitalio.DigitalInOut(board.D13)
rdy = digitalio.DigitalInOut(board.D11)
rst = digitalio.DigitalInOut(board.D12)
spi = busio.SPI(board.SCK, board.MOSI, board.MISO)
radio = adafruit_esp32spi.ESP_SPIcontrol(spi, cs, rdy, rst)


def connect_wifi(max_tries=None):
    tries = 0
    while not radio.is_connected:
        if max_tries is not None and tries >= max_tries:
            return False
        tries += 1
        print("Verbinde mit WLAN ...")
        try:
            radio.connect_AP(WIFI_SSID, WIFI_PASSWORD)
            print("WLAN verbunden, IP", radio.pretty_ip(radio.ip_address))
        except (RuntimeError, OSError) as e:
            print("WLAN-Fehler:", e)
            time.sleep(1)
    return True


show(["Verbinde mit WLAN", WIFI_SSID, "..."])
connect_wifi()

pool = adafruit_connection_manager.get_radio_socketpool(radio)
context = adafruit_connection_manager.get_radio_ssl_context(radio)
requests = adafruit_requests.Session(pool, context)
post_url = "https://" + TS_HTTPS_SERVER + "/update"


def send_to_thingspeak(fields):
    """Sendet die Werte und liefert einen kurzen Status fuers Display."""
    if not connect_wifi(max_tries=1):
        return "kein WLAN"
    payload = "api_key=" + TS_WRITE_API_KEY
    for number, value in fields.items():
        if value is not None:
            payload += "&field{}={}".format(number, value)
    try:
        response = requests.post(post_url, data=payload)
        entry = response.text.strip()
        response.close()
        print("ThingSpeak:", response.status_code, "Eintrag", entry)
        if entry == "0":
            return "abgelehnt"  # meist: zu schnell gesendet
        return "OK"
    except Exception as e:
        print("Sendefehler:", e)
        radio.reset()
        return "Fehler"


# ---------------- Hilfsfunktionen ----------------
def fmt(value, pattern="{}"):
    return "--" if value is None else pattern.format(value)


dust_low_us = 0   # Summe der LOW-Zeiten im aktuellen Messfenster
dust_index = 0    # gerade = LOW-Puls, ungerade = HIGH-Puls


def collect_dust_pulses():
    global dust_low_us, dust_index
    while len(dust_pulses) > 0:
        duration = dust_pulses.popleft()
        if dust_index % 2 == 0:
            dust_low_us += duration
        dust_index += 1


def restart_dust_window():
    global dust_low_us, dust_index
    dust_pulses.pause()
    dust_pulses.clear()
    dust_low_us = 0
    dust_index = 0
    dust_pulses.resume()


def dust_concentration(low_us, window_s):
    """Umrechnung nach Datenblatt/Seeed-Wiki in Partikel pro 0.01 cf (283 ml)."""
    ratio = low_us / (window_s * 1000000) * 100  # LOW-Anteil in %
    return round(1.1 * ratio ** 3 - 3.8 * ratio ** 2 + 520 * ratio + 0.62)


# ---------------- Hauptschleife ----------------
m = {"temp": None, "hum": None, "light": None, "co2": None, "dust": None}

start = time.monotonic()
last_measure = -MEASURE_INTERVAL
last_send = -SEND_INTERVAL
last_presence = -PRESENCE_HOLD - 1
dust_window_start = start
pause_until = 0
ts_status = "--"
restart_dust_window()

while True:
    now = time.monotonic()

    # --- Taste: Alarme quittieren, 10 Minuten Pause
    event = button.events.get()
    if event and event.pressed:
        pause_until = now + PAUSE_TIME
        print("Taste gedrueckt -> 10 Minuten keine Alarme")

    # --- Personenerkennung (PIR ist HIGH, solange er Bewegung sieht)
    if pir.value:
        last_presence = now
    present = now - last_presence < PRESENCE_HOLD

    # --- Staubsensor: Pulse einsammeln, alle DUST_WINDOW Sekunden auswerten
    collect_dust_pulses()
    if now - dust_window_start >= DUST_WINDOW:
        if now - start >= DUST_WARMUP:
            m["dust"] = dust_concentration(dust_low_us, now - dust_window_start)
        dust_window_start = now
        restart_dust_window()

    # --- Uebrige Messungen
    if now - last_measure >= MEASURE_INTERVAL:
        last_measure = now

        if scd30 is not None:
            try:
                if scd30.data_available:
                    m["co2"] = round(scd30.CO2)
                    m["temp"] = round(scd30.temperature, 1)
                    m["hum"] = round(scd30.relative_humidity)
            except Exception as e:
                print("SCD30-Fehler:", e)

        m["light"] = round(light_sensor.value * 100 / 65535, 1)

        print("T:", m["temp"], "H:", m["hum"], "L:", m["light"],
              "CO2:", m["co2"], "Staub:", m["dust"], "Person:", present)

    # --- Alarme bestimmen
    paused = now < pause_until
    air_bad = ((m["co2"] is not None and m["co2"] > CO2_LIMIT) or
               (m["dust"] is not None and m["dust"] > DUST_LIMIT))
    dark = m["light"] is not None and m["light"] < LIGHT_THRESHOLD

    air_alarm = air_bad and present and not paused
    light_alarm = dark and present and not paused

    # --- LED: schnell blinken = lueften, langsam blinken = Licht
    if air_alarm:
        led.value = (now % 0.5) < 0.25
    elif light_alarm:
        led.value = (now % 2) < 1
    else:
        led.value = False

    # --- Display (Schrift ohne Umlaute, darum OE / UE)
    air_text = ["OEFFNEN SIE DAS", "FENSTER FUER", "5 MINUTEN", "", "Taste = erledigt"]
    light_text = ["SCHALTEN SIE", "DAS LICHT EIN", "", "", "Taste = erledigt"]

    if air_alarm and light_alarm:
        # beide Meldungen im Wechsel alle 3 Sekunden
        show(air_text if int(now / 3) % 2 == 0 else light_text)
    elif air_alarm:
        show(air_text)
    elif light_alarm:
        show(light_text)
    else:
        if paused:
            rest = int(pause_until - now)
            status = "Pause {}:{:02d}".format(rest // 60, rest % 60)
        else:
            status = "TS: " + ts_status
        show([
            "T:{}C  H:{}%".format(fmt(m["temp"]), fmt(m["hum"])),
            "CO2:  {} ppm".format(fmt(m["co2"])),
            "Staub:{}".format(fmt(m["dust"])),
            "Licht:{}%  Pers:{}".format(fmt(m["light"], "{:.0f}"), "ja" if present else "nein"),
            status,
        ])

    # --- ThingSpeak
    if now - last_send >= SEND_INTERVAL:
        last_send = now
        alarm_code = (1 if air_alarm else 0) + (2 if light_alarm else 0)
        ts_status = send_to_thingspeak({
            1: m["temp"], 2: m["hum"], 3: m["light"], 4: m["co2"],
            5: m["dust"], 6: 1 if present else 0, 7: alarm_code,
        })

    time.sleep(0.05)
