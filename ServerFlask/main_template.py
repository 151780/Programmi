from flask import Flask, request, redirect, url_for, render_template, jsonify, flash
from flask_login import LoginManager, current_user, login_user, logout_user, login_required, UserMixin
from secret import secret_key
from google.cloud import firestore, storage
from google.cloud import pubsub_v1
from google.auth import jwt
from joblib import load, dump
from sklearn.metrics import accuracy_score
import json
import schedule
import csv


# i nomi delle finestre sono:
# index
# login
# menu
# controls
# rain
# wind
# humidity
# pressure
# temperature
# light
# forecast

########################## INIZIALIZZAZIONI ##########################
# definizione classe User
class User(UserMixin):
    def __init__(self, username):
        super().__init__()
        self.id = username
        self.username = username

# avvio istanza flask
app = Flask(__name__)
app.config['SECRET_KEY'] = secret_key
login = LoginManager(app)
login.login_view = 'show_login_form'  # Punti alla rotta della funzione che renderizza il template login.html

# apertura connessione DB Firestore
dbName = 'db151780'
collUsers = 'Users'
collMeteo = 'MeteoData'
meteoStationDB = firestore.Client.from_service_account_json('credentials.json', database=dbName)

usersDB = {}

# definizione parametri per forecast
# backwardGap = 10        # indica da quanti passi indietro devo partire per il forecast
backwardSamples = 1     # indica quanti campioni devo inserire per forecast
showPeriods = 50        # indica per quanti periodi devo mostrare i grafici
accuracyThreshold = 0.8 # indica la soglia sotto la quale devo fare retrain
modelToRetrain = False  # variabile globale per segnalazione di retrain necessario

########################## FUNZIONI DI SERVIZIO ##########################
#### INVIO RICHIESTA DI RETRAIN CON PUBSUB
def modelRetrain():
    global modelToRetrain

    if modelToRetrain:
        myProj = "progetto01-417313"
        myTopic = "trainRetrainReq"

        servAccount = json.load(open("credentials.json"))
        audience = "https://pubsub.googleapis.com/google.pubsub.v1.Publisher"
        credentials = jwt.Credentials.from_service_account_info(servAccount, audience=audience)
        publisher = pubsub_v1.PublisherClient(credentials=credentials)
        topic_path = publisher.topic_path(myProj, myTopic)
        r = publisher.publish(topic_path, b'Retrain model', type=b"retrain")
        print(r.result())
        modelToRetrain = False

        return

#### ACQUISIZIONE MODELLO DA CLOUD ####
def getModel():
    # recupero il modello dal cloud
    clfName = "rfClass"
    bucketName = "151780-progetto01"        # definisco il nome del bucket di salvataggio in cloud
    dumpPath=f"./tmp/{clfName}.joblib"      # definisco il path di salvataggio locale del modello
    blobName = f"{clfName}.joblib"          # definisco il nome del file di salvataggio sul cloud

    csClient = storage.Client.from_service_account_json('./credentials.json')  # accedo al cloud storage

    gcBucket = csClient.bucket(bucketName)      # scelgo il bucket
    gcBlob = gcBucket.blob(blobName)            # assegno il nome del file di destinazione
    gcBlob.download_to_filename(dumpPath)       # scarico il file dal cloud    

    rf = load(dumpPath)                         # salvo in locale il modello
    return rf

### ACQUSIZIONE DATI DAL DB PER GRAFICI
def getDataFromDB(atmoEv,sPer):
    collRef = meteoStationDB.collection(collMeteo)      # definisco la collection da leggere e ne leggo gli ultimi elementi necessari per grafico
    qForecast = collRef.order_by("sampleTime", direction=firestore.Query.DESCENDING).limit(sPer)
    meteoList = list(qForecast.stream())                # creo la lista dei documenti da graficare sul forecast
    meteoList.reverse()                                 # inverto la lista perchè ero in descending
    featData=[]                                         # inizializzo le liste dei dati

    for sampleMeteo in meteoList:                       # per ogni documento nella collezione
        sampleDict = sampleMeteo.to_dict()              # appendo il valore alla lista corrispondente
        featData.append((sampleDict["sampleTime"],sampleDict[atmoEv]))
   
    return featData

### SALVATAGGIO DATI SENSORI SU FIRESTORE E SU FILE CSV IN STORAGE PER LOOKER
def saveDataToDB(stID,sTime,sTemp,sHum,sPress,sLight,sRain,fRain):
    sTimeStr = sTime.strftime("%Y-%m-%d-%H:%M:%S:%f")[:-5]
    print("salvataggio dati")
    docID = stID + sTimeStr
    print("docID: ",docID)
    docVal={}
    docVal["stationID"] = stID                                      # aggiungo ID stazione
    docVal["sampleTime"] = sTime                                    # aggiungo dataora rilevazione
    docVal["temperature"] = sTemp                                   # aggiungo temperatura
    docVal["humidity"] = sHum                                       # aggiungo umidità
    docVal["pressure"] = sPress                                     # aggiungo pressione
    docVal["lighting"] = sLight                                     # aggiungo illuminazione
    docVal["rain"] = sRain                                          # aggiungo pioggia
    docVal["rain10"] = fRain                            # aggiungo forecast pioggia
    print("docVal: ",docVal)

    docRef = meteoStationDB.collection(collMeteo).document(docID)   # imposto il documento
    docRef.set(docVal)                                              # e lo scrivo



    return 'Data saved',200

### SALVATAGGIO DATI SENSORI SU FILE CSV IN STORAGE PER LOOKER
def saveDataToCloudStorage():
    fileName = "MeteoData"
    bucketName = "151780-progetto01"            # definisco il nome del bucket di salvataggio in cloud
    dumpPath=f"./tmp/{fileName}.csv"            # definisco il path di salvataggio locale
    blobName = f"{fileName}.csv"                # definisco il nome del file di salvataggio sul cloud

    meteoList = meteoStationDB.collection(collMeteo).stream()   # acquisisco i dati dal DB Firestore
    firstLine = True
    with open(dumpPath,mode='w',newline='') as csvFile:         # creo il file locale
        writer = csv.writer(csvFile)
        for meteoSample in meteoList:
            meteoSampleDict=meteoSample.to_dict()
            if firstLine:
                meteoNames = list(meteoSampleDict.keys())       # creo intestazione solo al primo record
                writer.writerow(meteoNames)
                firstLine = False
            meteoValues = list(meteoSampleDict.values())
            writer.writerow(meteoValues)

    csClient = storage.Client.from_service_account_json('./credentials.json')  # accedo al cloud storage

    gcBucket = csClient.bucket(bucketName)      # scelgo il bucket
    gcBlob = gcBucket.blob(blobName)            # assegno il nome del file di destinazione
    gcBlob.upload_from_filename(dumpPath)       # carico il file sul cloud

### SALVATAGGIO RICHIESTE CONTROLLI TENDE
def saveControls(ctrlToRun):
    fileName = "awningControls"
    bucketName = "151780-progetto01"            # definisco il nome del bucket di salvataggio in cloud
    dumpPath=f"./tmp/{fileName}.txt"            # definisco il path di salvataggio locale
    blobName = f"{fileName}.txt"                # definisco il nome del file di salvataggio sul cloud

    with open(dumpPath,mode='a',newline='') as txtFile:         # creo il file locale
        writer = csv.writer(txtFile)
        writer.writerow(ctrlToRun)

    csClient = storage.Client.from_service_account_json('./credentials.json')  # accedo al cloud storage

    gcBucket = csClient.bucket(bucketName)      # scelgo il bucket
    gcBlob = gcBucket.blob(blobName)            # assegno il nome del file di destinazione
    gcBlob.upload_from_filename(dumpPath)       # carico il file sul cloud

########################## ENDPOINTS ##########################
### LOGIN ###
@app.route("/login", methods=["POST", "GET"])
def show_login_form():
    return render_template("login.html")

@app.route("/login_request", methods=["POST"])
def login_request():
    global usersDB

    if request.method == "POST":
        data = request.get_json()
        username = data.get("username")
        password = data.get("password")

        # Recupera le informazioni sull'utente dal database Firestore
        userRef = meteoStationDB.collection(collUsers).document(username)
        user = userRef.get()

        if user.exists:
            userData = user.to_dict()
            dbUsername = userData.get("username")
            dbPassword = userData.get("password")

            if dbUsername == username and dbPassword == password:
                login_user(User(username))
                usersDB[username] = User(username)
                return redirect(url_for("index"))
            else:
                flash("Invalid username or password", "error")
        else:
            flash("Invalid username or password", "error")
    
    return render_template("login.html")

### LOGOUT ###
@app.route("/logout", methods=["POST", "GET"])
@login_required
def logout():
    username = current_user.username
    logout_user()
    usersDB.pop(username, None)
    return redirect(url_for("show_login_form"))

### HOME ###
@app.route("/")
@login_required
def index():
    return render_template("index.html")

### GESTIONE ERRORI ###
@login.unauthorized_handler
def unauthorized_callback():
    return redirect(url_for('show_login_form'))

@login.user_loader
def load_user(user_id):
    return usersDB.get(user_id)

### MENU ###
@app.route("/menu", methods=["POST", "GET"])
@login_required
def menu():
    return render_template("menu.html")

### CONTROLLO TENDE ###
@app.route("/controls", methods=["POST", "GET"])
@login_required
def controls():
    return render_template("controls.html")

@app.route("/sendCtrl", methods=["POST"])
@login_required
def sendCtrl():
    data = request.get_json()
    dataToSend = []

    try:
        sTime = datetime.now()
        stID = data["stID"]
        dataToSend.append(stID)
        dataToSend.append(sTime)
        dataToSend.append(data["wOnOff"])
        dataToSend.append(data["wReason"])
        saveControls(dataToSend)
        return "control sent", 200
    except:
        return "wrong data", 403

### PIOGGIA ###
@app.route("/rain", methods=["POST", "GET"])
@login_required
def rain():
    try:
        atmoEvent = "rain"
        featData = getDataFromDB(atmoEvent,showPeriods)
        return render_template("rain.html", data = featData)
    except:
        return render_template("rain.html", data = [])

### VENTO ###
@app.route("/wind", methods=["POST", "GET"])
@login_required
def wind():
    try:
        atmoEvent = "wind"
        featData = getDataFromDB(atmoEvent,showPeriods)
        return render_template("wind.html", data = featData)
    except:
        return render_template("wind.html", data = [])

### UMIDITA ###
@app.route("/humidity", methods=["POST", "GET"])
@login_required
def humidity():
    try:
        atmoEvent = "humidity"
        featData = getDataFromDB(atmoEvent,showPeriods)
        return render_template("humidity.html", data = featData)
    except:
        return render_template("humidity.html", data = [])

### PRESSIONE ###
@app.route("/pressure", methods=["POST", "GET"])
@login_required
def pressure():
    try:
        atmoEvent = "pressure"
        featData = getDataFromDB(atmoEvent,showPeriods)
        return render_template("pressure.html", data = featData)
    except:
        return render_template("pressure.html", data = [])

### TEMPERATURA ###
@app.route("/temperature", methods=["POST", "GET"])
@login_required
def temperature():
    try:
        atmoEvent = "temperature"
        featData = getDataFromDB(atmoEvent,showPeriods)
        return render_template("temperature.html", data = featData)
    except:
        return render_template("temperature.html", data = [])

### LUCE ###
@app.route("/light", methods=["POST", "GET"])
@login_required
def light():
    try:
        atmoEvent = "lighting"
        featData = getDataFromDB(atmoEvent,showPeriods)
        return render_template("light.html", data = featData)
    except:
        return render_template("light.html", data = [])

### FORECAST ###
@app.route("/forecast", methods=["POST", "GET"])
@login_required
def forecast():
    try:
        atmoEvent = "forecast"
        featData = getDataFromDB(atmoEvent,showPeriods)
        return render_template("forecast.html", data = featData)
    except:
        return render_template("forecast.html", data = [])


### INVIO DATI ###
@app.route("/data", methods=["POST"])
@login_required
def postData():
    global modelToRetrain

    data = request.get_json()

    try:
        stationID = data["stID"]
        sampleTime = datetime.now()
        sampleTemperature = data["stTemp"]
        sampleHumidity = data["stHum"]
        samplePressure = data["stPress"]
        sampleLighting = data["stLight"]
        sampleRain = data["stRain"]
        print("campione rilevato")
        print(stationID)
        print(sampleTemperature)
        print(sampleHumidity)
        print(samplePressure)
        print(sampleLighting)
        print(sampleRain)

        saveDataToDB(stationID,sampleTime,sampleTemperature,sampleHumidity,samplePressure,sampleLighting,sampleRain,0)

        rf = getModel()
        forecastSamples=[]
        for r in range(0,backwardSamples):                         # recupero dati per sample indietro nel tempo e preparo il vettore di input
            atmoEventData = getDataFromDB("rain",backwardSamples)
            forecastSamples.append(atmoEventData[r][1])

        print("campioni per forecast: ",forecastSamples)
        rainForecast=rf.predict([forecastSamples])
        print("forecast: ",rainForecast[0])
        saveDataToDB(stationID,sampleTime,sampleTemperature,sampleHumidity,samplePressure,sampleLighting,sampleRain,rainForecast[0])

        featData = getDataFromDB("rain",showPeriods)
        y_test = []
        y_pred = []

        for r in featData:
            y_test.append(r[1])

        featData = getDataFromDB("rain10",showPeriods)

        for r in featData:
            y_pred.append(r[1])

        acc = accuracy_score(y_test, y_pred)
        print("acc: ",acc)

        if acc<accuracyThreshold:
            modelToRetrain=True

        return "Data registered", 200
    except:
        return "Wrong data", 403

### JOBS ###
schedule.every().day.at("00:00").do(saveDataToCloudStorage)

########################## MAIN ##########################
if __name__ == "__main__":
    app.run(debug=True)
