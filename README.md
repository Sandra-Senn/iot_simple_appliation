# iot_simple_appliation

IoT-Anwendung für das Modul idb: Die Messwerte werden an einen ThingSpeak-Channel gesendet. Das Notebook [idb.ipynb](idb.ipynb) liest sie dort aus und stellt sie grafisch dar.

## Hardware

### Board und Zubehör

| Komponente | Verwendung |
| --- | --- |
| Adafruit Feather nRF52840 Express | Mikrocontroller |
| Adafruit FeatherWing ESP32 AirLift | WLAN-Verbindung zu ThingSpeak |
| Feather to Grove Adapter | Anschluss der Grove-Module an das Feather |
| Grove I2C Hub | Mehrere I2C-Sensoren an einem Anschluss |

### Sensoren

| Komponente | Messgrösse | Schnittstelle |
| --- | --- | --- |
| Grove CO2 Temperature Humidity Sensor SCD30 | CO2 (ppm), Temperatur (°C), Luftfeuchtigkeit (%) | I2C |
| Grove VOC eCO2 Gas Sensor SGP30 | TVOC (ppb), eCO2 (ppm) | I2C |
| Grove Laser PM2.5 Particle Sensor HM3301 | Feinstaub PM1.0 / PM2.5 / PM10 (µg/m³) | I2C |
| Grove Human Presence Sensor AK9753 | Anwesenheit von Personen (Infrarot) | I2C |
| Grove Light Sensor LS06-S (oder LDR) | Helligkeit | Analog |

### Aktoren und Anzeige

| Komponente | Verwendung |
| --- | --- |
| Grove OLED 0.96 Display SSD1315 | Anzeige der Messwerte (I2C) |
| Grove Piezo Buzzer | Akustischer Alarm |
| Grove LED Red | Optischer Alarm / Statusanzeige |

### Eingabe

| Komponente | Verwendung |
| --- | --- |
| Grove Button | Benutzereingabe |

### Sonstiges

- Grove-Kabel (ca. 10 Stück)
- USB-Kabel und Netzteil
