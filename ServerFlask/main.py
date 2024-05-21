from flask import Flask,request,redirect,url_for,render_template,jsonify
from flask_login import LoginManager, current_user, login_user, logout_user, login_required, UserMixin
from secret import secret_key
from google.cloud import firestore, storage
from joblib import load, dump
import os

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
login.login_view = '/login.html'

# verifico se sono in locale o in cloud
if os.path.isfile("./credentials.json"):
    local = True
else:
    local = False
# apertura connessione DB Firestore
dbName = 'db151780'
collUsers = 'Users'
collMeteo = 'MeteoData'
if local:
    meteoStationDB = firestore.Client.from_service_account_json('credentials.json', database=dbName)
else:
    meteoStationDB = firestore.Client(database=dbName)
usersDB = {}

# inizializzazione parametri per forecast
backwardGap = 10        # indica da quanti passi indietro devo partire per il forecast
backwardSamples = 1     # indica quanti campioni devo inserire per forecast
forecastPeriods = 30    # indica per quanti periodi devo prevedere il forecast

#### ACQUISIZIONE MODELLO DA CLOUD ####
def getModel():
    # recupero il modello dal cloud
    clfName = "rfClass"
    bucketName = "151780-progetto01"        # definisco il nome del bucket di salvatoaggio in cloud
    dumpPath=f"./tmp/{clfName}.joblib"      # definisco il path di salvataggio locale del modello
    blobName = f"{clfName}.joblib"          # definisco il nome del file di salvataggio sul cloud

    if local:
        csClient = storage.Client.from_service_account_json('./credentials.json')  # accedo al cloud storage
    else:
        csClient = storage.Client()
    gcBucket = csClient.bucket(bucketName)      # scelgo il bucket
    gcBlob = gcBucket.blob(blobName)            # assegno il nome del file di destinazione
    gcBlob.download_to_filename(dumpPath)       # scarico il file dal cloud    

    rf = load(dumpPath)                         # salvo in locale il modello
    return rf

### Home page
@app.route('/',methods=['GET'])
def main():
    return redirect("/static/index.html")

### Menu generale
@app.route('/menu', methods=['GET'])
@login_required
def menu():
    return redirect("/static/menu.html")

### Acquisisci dati dal DB per grafici
def getGraphData(atmoEv):
    collRef = meteoStationDB.collection(collMeteo)      # definisco la collection da leggere e ne leggo gli ultimi elementi necessari per grafico
    qForecast = collRef.order_by("sampleTime", direction=firestore.Query.DESCENDING).limit(forecastPeriods+backwardSamples)
    meteoList = list(qForecast.stream())                # creo la lista dei documenti da graficare sul forecast
    meteoList.reverse()                                 # inverto la lista perchè ero in descending
    dOra=[]                                          # inizializzo le liste dei dati
    aEvent=[]

    for sampleMeteo in meteoList:                       # per ogni documento nella collezione
        sampleDict = sampleMeteo.to_dict()              # appendo il valore alla lista corrispondente
        dOra.append(sampleDict["sampleTime"])
        aEvent.append(sampleDict[atmoEv])
   
    return dOra, aEvent

### Grafico pioggia
@app.route('/rain', methods=['GET'])
@login_required
def rainGraph():
    print("Grafico pioggia")
    dataOra, atmoEvent = getGraphData("rain")
    ds={}
    return render_template('/static/rain.html',data=ds)

### Forecasting pioggia
@app.route('/forecast', methods=['GET'])
@login_required
def forecastGraph():
    print("Grafico forecast pioggia")
    collRef = meteoStationDB.collection(collMeteo)      # definisco la collection da leggere e ne leggo gli ultimi elementi necessari per grafico
    qForecast = collRef.order_by("sampleTime", direction=firestore.Query.DESCENDING).limit(forecastPeriods+backwardSamples)
    meteoList = list(qForecast.stream())                # creo la lista dei documenti da graficare sul forecast
    meteoList.reverse()                                 # inverto la lista perchè ero in descending
    ascisse=[]                                          # inizializzo le liste dei dati
    pioggiaPrevista=[]
    pioggiaReale=[]

    for sampleMeteo in meteoList:                       # per ogni documento nella collezione
        sampleDict = sampleMeteo.to_dict()              # appendo il valore alla lista corrispondente
        ascisse.append(sampleDict["sampleTime"])
        pioggiaReale.append(sampleDict["rain"]>0)
        pioggiaPrevista.append(sampleDict[f"rain{backwardGap}"])
    ascisse.pop(0)                                      # faccio in modo che la previsione sia allineata al giorno corretto
    pioggiaReale.pop(0)
    pioggiaPrevista.pop(-1)

    ds={}
    return render_template('/static/forecast.html',data=ds)

### Comando tende
@app.route('/controls', methods=['GET'])
@login_required
def controls():
    print("Controlli")
    return redirect('/static/controls.html')

### Ricezione dati da Raspberry
@app.route('/raspberry', methods=['POST'])
def raspberryData():
    stationID = request.values["stationID"]
    sTime = request.values["sampleTime"]
    temperatureValue = float(request.values["temperature"])
    humidityValue = float(request.values["humidity"])
    pressureValue = float(request.values["pressure"])
    lightingValue = float(request.values["lighting"])
    rainfallValue = float(request.values["rainfall"])
   
    collRef = meteoStationDB.collection(collMeteo)          # definisco la collection da leggere e ne leggo gli ultimi elementi necessari per grafico
    qForecast = collRef.order_by("sampleTime", direction=firestore.Query.DESCENDING).limit(backwardSamples)
    meteoList = list(qForecast.stream())                    # creo la lista dei documenti che servono per fare il forecast
    featureColList=["humidity","pressure","temperature"]
    if len(meteoList)>=backwardSamples:                     # se ho sufficienti dati per fare il forecast
        forecastData = [[]]                                 # costruisco l'esempio
        for sampleDoc in meteoList:                         # per ogni esempio acquisito
            sampleData = sampleDoc.to_dict()
            for feat in featureColList:                     # per ogni feature
                forecastData[0].append(sampleData[feat])    # appendo alla lista dati

        rainForecast=rfModel.predict(forecastData)[0]       # predico la pioggia
    else:
        rainForecast=0

    print(stationID,sTime)
    print("T = ",temperatureValue)
    print("H = ",humidityValue)
    print("P = ",pressureValue)
    print("L = ",lightingValue)
    print("R = ",rainfallValue)
    saveDataToDB(stationID,sTime,temperatureValue,humidityValue,pressureValue,lightingValue,rainfallValue,rainForecast)
    return "ok", 200

### Salvataggio dati sensori su Firestore
def saveDataToDB(stID,sTime,sTemp,sHum,sPress,sLight,sRain,fRain):
    print("salvataggio dati")
    docID = stID + sTime
    print("docID: ",docID)
    docVal={}
    docVal["stationID"] = stID                                      # aggiungo ID stazione
    docVal["sampleTime"] = sTime                                    # aggiungo dataora rilevazione
    docVal["temperature"] = sTemp                                   # aggiungo temperatura
    docVal["humidity"] = sHum                                       # aggiungo umidità
    docVal["pressure"] = sPress                                     # aggiungo pressione
    docVal["lighting"] = sLight                                     # aggiungo illuminazione
    docVal["rain"] = sRain                                          # aggiungo pioggia
    docVal[f"rain{backwardGap}"] = fRain                            # aggiungo forecast pioggia
    print("docVal: ",docVal)

    docRef = meteoStationDB.collection(collMeteo).document(docID)   # imposto il documento
    docRef.set(docVal)                                              # e lo scrivo
   
    return 'Data saved',200

### Verifica utente ###
@login.user_loader                      # carico il nome dell'utente loggato
def load_user(username):                # ritorno nome utente se in db altrimenti None
    if username in usersDB:
        return User(username)
    return None

### Acquisizione dati utenti da Firestore
def getUsersDB():
    usersList = meteoStationDB.collection(collUsers).stream()
    usersDB = {user.to_dict()["username"]: {"password": user.to_dict()["password"],
                                            "email": user.to_dict()["email"]} for user in usersList}
    print(usersDB)
    return usersDB
    
### Aggiornamento utenti su Firestore on signup e aggiornamento DB locale
def updateUsersDB(username,password,email):
    docVal={}
    docVal["username"] = username                   # aggiungo username
    docVal["password"] = password                   # aggiungo password
    docVal["email"] = email                         # aggiungo email
    print("docVal: ",docVal)

    docRef = meteoStationDB.collection(collUsers).document()        # imposto il documento
    docRef.set(docVal)                                              # e lo scrivo
 
    usersDB[username] = {"password": password,"email": email}
    print(usersDB)
    return usersDB
    
### Signup nuovo utente ###
@app.route('/sign_up', methods=['POST'])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for('/static/menu.html'))
    username = request.values['username']
    email = request.values['email']
    password1 = request.values['password1']
    password2 = request.values['password2']

    if username in usersDB:
        return redirect('/static/sign_up.html')
    if password1 != password2:
        return redirect('/static/sign_up.html')
    if email in [valDict["email"] for valDict in usersDB.values()]:
        return redirect('/static/sign_up.html')
    
    updateUsersDB(username,password1,email)
    return redirect('/static/login.html')

### Login utente ###
@app.route('/login', methods=['POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('/static/menu.html'))
    username = request.values['username']
    password = request.values['password']

    if username in usersDB and password == usersDB[username]["password"]:
        login_user(User(username))
        return redirect('/static/menu.html')
    return redirect('/static/login.html')

### Logout utente ###
@app.route('/logout')
def logout():
    logout_user()
    return redirect('/static/index.html')



if __name__ == '__main__':
    usersDB=getUsersDB()
    rfModel = getModel()            # variabile contenente il modello di forecasting
    app.run(host='0.0.0.0', port=80, debug=False)

