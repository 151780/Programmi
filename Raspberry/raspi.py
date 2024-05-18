from gpiozero import LED, Button, OutputDevice, InputDevice
import schedule
import time
import board
import busio
import adafruit_ads1x15.ads1015 as ADS
from adafruit_ads1x15.analog_in import AnalogIn
import bmp180
import adafruit_dht
import requests
from secret import bot_token, chat_id

############ ACQUISIZIONE DHT11
def getDHT11(dht11,wStConst):
    # ciclo di lettura del sensore - ripeto finchè non ho un dato o per maxTry tentativi
    gotParams = False
    maxTry = 10
    nTry = 0
    while not gotParams and nTry < maxTry:
        try:
            # acquisico i dati dal dispositivo
            temperature = dht11.temperature
            humidity = dht11.humidity
            print("DHT11:\t\tTemperatura {:3.1f} °C - Umidità {:4.1f}%".format(temperature,humidity))
            # print("DHT11:\t\tTemperatura %3.1f °C - Umidità %d "%(temperature,humidity))
            gotParams=True
        except RuntimeError as error:
            # in caso di errore riprovo
            # print(error.args[0])
            time.sleep(2)
            continue
        except Exception as error:
            # in caso di eccezione rilascio la risorsa e termino
            dht11.exit()
            raise error
        # time.sleep(2.0)
        nTry+=1
    return temperature, humidity

############ ACQUISIZIONE ADS1015 + BMP180
def getADS1015_BMP180(i2c,ads,bmp,wStConst):
    photoMin = wStConst["photoMin"]
    photoMax = wStConst["photoMax"]
    rainMin = wStConst["rainMin"]
    rainMax = wStConst["rainMax"]

    # acquisisco i dati del BMP180
    temperature=bmp.temperature
    pressure=bmp.pressure
    altitude=bmp.altitude
    print("BMP180:\t\tTemperatura {:3.1f} °C - Pressione {:6.1f} mbar - Altitudine {:4.0f} m".format(temperature,pressure,altitude))
    # print("BMP180:\t\tTemperatura %3.1f °C - Pressione %5.1f mbar - Altitudine %4d m"%(temperature,pressure,altitude))
    
    # acquisisco i dati del ADS1015
    # canale 0 - fotoresistenza
    chan = AnalogIn(ads,ADS.P0)
    photoResValue=chan.value
    photoResVolt=chan.voltage
    # calcolo il valore relativo di illuminazione
    if photoResValue < photoMin:
        photoResValue = photoMin
    if photoResValue > photoMax:
        photoResValue = photoMax
    lighting=100 * (photoResValue-photoMin)/(photoMax-photoMin)
    print("Canale 0:\tFotoresistenza {:5.0f} - Tensione {:5.3f} V - Illuminazione {:4.1f}%".format(photoResValue,photoResVolt,lighting))

    # canale 1 - sensore pioggia
    chan = AnalogIn(ads,ADS.P1)
    rainSensorValue=chan.value
    rainSensorVolt=chan.voltage
    # calcolo il valore delle precipitazioni
    if rainSensorValue < rainMin:
        rainSensorValue = rainMin
    if rainSensorValue > rainMax:
        rainSensorValue = rainMax
    rainfall=(rainMax-rainSensorValue)/(rainMax-rainMin)
    print("Canale 1:\tSensore pioggia {:5.0f} - Tensione {:5.3f} V - Precipitazioni {:4.2f} mm/h".format(rainSensorValue,rainSensorVolt,rainfall))
    # time.sleep(2)
    return temperature,pressure,altitude,photoResValue,photoResVolt,lighting,rainSensorValue,rainSensorVolt,rainfall

############ RISPOSTA A EVENTO DI WINDTIC
def addWindTic():
    global windTic
    windTic+=1

############ FUNZIONI DI GESTIONE TENDA
def estendiTenda():
    releRitraiTenda.off()
    time.sleep(1)
    releEstendiTenda.on()

def estendiTendaStop():
    print("estendiTendaStop")
    releEstendiTenda.off()

def ritraiTenda():
    releEstendiTenda.on()
    time.sleep(1)
    releRitraiTenda.off()

def ritraiTendaStop():
    print("ritraiTendaStop")
    releRitraiTenda.off()

############ ACQUISIZIONE E GESTIONE DEI DATI DEI SENSORI
def getStatus(wStConst):
    global windTic, itsRaining
    print("----------------------------------------")
    print("Tenda ritratta:\t",fcTendaRitratta.is_active)
    print("Tenda estesa:\t",fcTendaEstesa.is_active)
    print("Tic anemometro:\t",windTic)
    temperatureDHT, humidity = getDHT11(dht11,wStConst)
    temperatureBMP,pressure,altitude,photoResValue,photoResVolt,lighting,rainSensorValue,rainSensorVolt,rainfall = getADS1015_BMP180(i2c,ads,bmp,wStConst)
    print("----------------------------------------")
    print()
    
    # segnalo al bot Telegram che sta piovendo
    if rainfall>0 and not itsRaining:
        chatID = wStConst["chatID"]
        botToken = wStConst["botToken"]
        message = "STA PIOVENDO!"
        url = f"https://api.telegram.org/bot{botToken}/sendMessage?chat_id={chatID}&text={message}"
        requests.get(url).json()
        itsRaining=True
    else:
        itsRaining=False
        
    windTic=0

############# MAIN
# inizializzazione input pin - finecorsa di posizione tenda
fcTendaRitratta = Button(20, pull_up=True)
fcTendaEstesa = Button(21, pull_up=True)

# inizializzazione input pin - anemometro
anemometro = Button(24, pull_up=True)
windTic = 0

# inizializzazione output pin - ritrai tenda
releRitraiTenda = LED(19)
releEstendiTenda = LED(26)

# attribuzione evento reed anemometro attivato
# se attivato aumenta il numero di giri effettuati
anemometro.when_activated = addWindTic

# attribuzione evento finecorsa di tenda ritratta
# se attivato spegne il relè di ritrazione
fcTendaRitratta.when_activated = ritraiTendaStop

# attribuzione evento finecorsa di tenda estesa
# se attivato spegne il relè di estensione
fcTendaEstesa.when_activated = estendiTendaStop

# dizionario con parametri di base della stazione
weatherStationConst = {}
# parametri di connessione per segnalazione al bot Telegram
weatherStationConst["botToken"] = bot_token
weatherStationConst["chatID"] = chat_id
# inizializzazione valori limite della conversione A/D
# per sensore pioggia - valore più alto significa meno pioggia
weatherStationConst["rainMin"] = 7000
weatherStationConst["rainMax"] = 26200
# per sensore luminosità - valore più alto significa più luminosità
weatherStationConst["photoMin"] = 4000
weatherStationConst["photoMax"] = 25400

itsRaining=False

# riservo il DHT11
dht11 = adafruit_dht.DHT11(board.D18)
# riservo il bus I2C
i2c = busio.I2C(board.SCL,board.SDA)
# riservo ADS1015 sul bus I2C
ads = ADS.ADS1015(i2c)
# riservo BMP180 sul bus I2C
bmp = bmp180.BMP180(i2c)
# inizializzo la pressione del luogo
bmp.sea_level_pressure = 1013

# acquisisco la prima volta
getStatus(weatherStationConst)
# schedulazione acquisizione ogni 10 secondi
schedule.every(10).seconds.do(getStatus,weatherStationConst)

releRitraiTenda.toggle()
try:
    while True: # ripeti fino a keypressed
        schedule.run_pending()
        time.sleep(1)
        releRitraiTenda.toggle()
        releEstendiTenda.toggle()
except KeyboardInterrupt:
    pass

# svuoto la coda dei processi schedulati
schedule.clear()
# rilascio il DHT11
dht11.exit()

