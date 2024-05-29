from gpiozero import LED, Button, OutputDevice, InputDevice
import schedule
import time
import board
import busio
import adafruit_ads1x15.ads1015 as ADS
from adafruit_ads1x15.analog_in import AnalogIn
import bmp180
import adafruit_dht
from requests import post, get
from datetime import datetime
from secret import bot_token, chat_id

# baseURL = 'http://34.154.241.138:80'
# baseURL = "http://192.168.1.50:80"
baseURL = "https://progetto01-417313.oa.r.appspot.com"

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
            gotParams=True
        except RuntimeError as error:
            # in caso di errore riprovo
            time.sleep(2)
            continue
        except Exception as error:
            # in caso di eccezione rilascio la risorsa e termino
            dht11.exit()
            raise error
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
    return temperature,pressure,altitude,photoResValue,photoResVolt,lighting,rainSensorValue,rainSensorVolt,rainfall

############ RISPOSTA A EVENTO DI WINDTIC
def addWindTic():
    global windTic
    windTic+=1

############ FUNZIONI DI GESTIONE TENDA
def estendiTenda():
    if not fcTendaEstesa.is_active:
        releRitraiTenda.off()
        time.sleep(1)
        releEstendiTenda.on()

def estendiTendaStop():
    print("estendiTendaStop")
    releEstendiTenda.off()

def ritraiTenda():
    if not fcTendaRitratta.is_active:
        releEstendiTenda.off()
        time.sleep(1)
        releRitraiTenda.on()

def ritraiTendaStop():
    print("ritraiTendaStop")
    releRitraiTenda.off()

############ ACQUISIZIONE E GESTIONE DEI DATI DEI SENSORI
def getStatus(wStConst):
    global windTic, itsRaining, itsWinding, sTime, oldsTime
    
    sTime=datetime.now()
    elapsedTime=(sTime-oldsTime).total_seconds()
    oldsTime=sTime
    wind = 10*(windTic * spinAnem)/elapsedTime
    print("----------------------------------------")
    print("Tenda ritratta:\t",fcTendaRitratta.is_active)
    print("Tenda estesa:\t",fcTendaEstesa.is_active)
    print("Tic anemometro:\t",windTic)
    print("Tempo anemometro:\t",elapsedTime)
    print("Velocità anemometro:\t",wind)
    temperatureDHT, humidity = getDHT11(dht11,wStConst)
    temperatureBMP,pressure,altitude,photoResValue,photoResVolt,lighting,rainSensorValue,rainSensorVolt,rainfall = getADS1015_BMP180(i2c,ads,bmp,wStConst)
    print("----------------------------------------")
    print()

    sTimeStr = sTime.strftime("%Y-%m-%d-%H:%M:%S.%f")[:-5]
    # sampleTime = sTime.strftime("%H:%M:%S")
    
    print("sTime: ",sTime)
    print("sTimeStr: ",sTimeStr)
    
    dataVal={"stationID":"stazione",
            "sTimeStr":sTimeStr,
            "sampleTime":sTime,
            "temperature":temperatureBMP,
            "humidity":humidity,
            "pressure":pressure,
            "lighting":lighting,
            "rainfall":rainfall,
             "wind":wind}

    r = post(f'{baseURL}/raspberry',data=dataVal)
    # print(r)
    jsonComandi=r.json()["comandi"]
    # print(jsonComandi)
    listComandi = jsonComandi.split(" ")
    print(listComandi)
    for listElem in listComandi:
        comElem = 0
        try:
            comElem = listElem[3]
        except IndexError:
            pass
        if comElem=="r":
            ritraiTenda()
        if comElem=="e":
            estendiTenda()

    # segnalo al bot Telegram che sta piovendo
    if rainfall>0:
        if not itsRaining:
            chatID = wStConst["chatID"]
            botToken = wStConst["botToken"]
            message = "STA PIOVENDO!"
            url = f"https://api.telegram.org/bot{botToken}/sendMessage?chat_id={chatID}&text={message}"
            get(url).json()
            itsRaining=True
    else:
        itsRaining=False
        
    # segnalo al bot Telegram che ci sono folate di vento forte
    if wind>10:
        if not itsWinding:
            chatID = wStConst["chatID"]
            botToken = wStConst["botToken"]
            message = "FOLATE DI VENTO FORTE!"
            url = f"https://api.telegram.org/bot{botToken}/sendMessage?chat_id={chatID}&text={message}"
            get(url).json()
            itsWinding=True
    
    if wind<0.2:
        itsWinding=False
        
    windTic=0

############# MAIN
# inizializzazione input pin - finecorsa di posizione tenda
fcTendaRitratta = Button(20, pull_up=True)
fcTendaEstesa = Button(21, pull_up=True)

# inizializzazione input pin - anemometro
anemometro = Button(24, pull_up=True)
windTic = 0
radiusAnem = 0.05 # 50 mm
spinAnem = radiusAnem * 2 * 3.1415	# circonferenza
sTime = datetime.now()
oldsTime = sTime

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
itsWinding=False

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

try:
    while True: # ripeti fino a keypressed
        schedule.run_pending()
        time.sleep(1)
except KeyboardInterrupt:
    pass

# svuoto la coda dei processi schedulati
schedule.clear()
# rilascio il DHT11
dht11.exit()

