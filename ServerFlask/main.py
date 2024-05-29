from flask import Flask,request,redirect,url_for,render_template,session,flash
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
login.login_view = 'login'

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
#### ACQUISIZIONE MODELLO DA CLOUD ####
def getModel():
    # recupero il modello dal cloud
    clfName = "rfClass"
    bucketName = "151780-progetto01"        # definisco il nome del bucket di salvataggio in cloud
    dumpPath=f"/tmp/{clfName}.joblib"       # definisco il path di salvataggio locale del modello
    blobName = f"{clfName}.joblib"          # definisco il nome del file di salvataggio sul cloud

    csClient = storage.Client.from_service_account_json('./credentials.json')  # accedo al cloud storage

    gcBucket = csClient.bucket(bucketName)      # scelgo il bucket
    gcBlob = gcBucket.blob(blobName)            # assegno il nome del file di destinazione
    gcBlob.download_to_filename(dumpPath)       # scarico il file dal cloud    

    rf = load(dumpPath)                         # salvo in locale il modello
    print("Modello riacquisito")
    return rf

rfModel = getModel()                         # variabile contenente il modello di forecasting

### ACQUSIZIONE DATI DAL DB PER GRAFICI
def getDataFromDB(atmoEv,sPer,stID):
    print("StationID = ", stID)
    collRef = meteoStationDB.collection(collMeteo)      # definisco la collection da leggere e ne leggo gli ultimi elementi necessari per grafico
    qForecast = collRef.where("stationID", "==", stID).order_by("sampleTime", direction=firestore.Query.DESCENDING)
    qForecast=qForecast.limit(5)
    # .limit(sPer)
    # collRef = meteoStationDB.collection(collMeteo).where("stationID", "==", stID)     # definisco la collection da leggere e ne leggo gli ultimi elementi necessari per grafico
    # qForecast = collRef.order_by("sampleTime", direction=firestore.Query.DESCENDING).limit(sPer)
    meteoList = list(qForecast.stream())                # creo la lista dei documenti da graficare sul forecast
    print(meteoList)
    meteoList.reverse()                                 # inverto la lista perchè ero in descending
    featData=[]                                         # inizializzo le liste dei dati

    for sampleMeteo in meteoList:                       # per ogni documento nella collezione
        sampleDict = sampleMeteo.to_dict()              # appendo il valore alla lista corrispondente
        featData.append((sampleDict["sampleTime"][:-7],sampleDict[atmoEv]))
   
    return featData

### SALVATAGGIO DATI FEATURES SU FIRESTORE
def saveDataToDB(stID,sTime,sTimeStr,sTemp,sHum,sPress,sLight,sRain,fRain,sWind):
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
    docVal["wind"] = sWind                                          # aggiungo pioggia
    docVal["rain10"] = fRain                            # aggiungo forecast pioggia
    print("docVal: ",docVal)

    docRef = meteoStationDB.collection(collMeteo).document(docID)   # imposto il documento
    docRef.set(docVal)                                              # e lo scrivo

    return 'Data saved',200

### PREPARAZIONE DATI GRAFICI
def setGraphData(featData):
    ds=[]                                           # li passo alla pagina html per mostrare il grafico
    for fData in featData:                          # creo il dataset da inviare alla pagina per il grafico
        ds.append([fData[0][11:],fData[1]])
    return ds

### SALVATAGGIO RICHIESTE CONTROLLI TENDE
def saveControls(ctrlToRun):
    ctrlToRun+="\n"
    fileName = "awningControls"
    bucketName = "151780-progetto01"           # definisco il nome del bucket di salvataggio in cloud
    dumpPath=f"/tmp/{fileName}.txt"            # definisco il path di salvataggio locale
    blobName = f"{fileName}.txt"               # definisco il nome del file di salvataggio sul cloud

    with open(dumpPath,mode='a',newline='') as txtFile:         # creo il file locale
        txtFile.write(ctrlToRun)

    csClient = storage.Client.from_service_account_json('./credentials.json')  # accedo al cloud storage

    gcBucket = csClient.bucket(bucketName)      # scelgo il bucket
    gcBlob = gcBucket.blob(blobName)            # assegno il nome del file di destinazione
    gcBlob.upload_from_filename(dumpPath)       # carico il file sul cloud
    return

### SALVATAGGIO RICHIESTA RETRAIN
def setModelToRetrain():
    fileName = "retrainRequest"
    bucketName = "151780-progetto01"                # definisco il nome del bucket di salvataggio in cloud
    dumpPath=f"/tmp/{fileName}.txt"                 # definisco il path di salvataggio locale
    blobName = f"{fileName}.txt"                    # definisco il nome del file di salvataggio sul cloud

    with open(dumpPath,mode='w',newline='') as txtFile:     # creo il file locale
        txtFile.write("retrain\n")

    csClient = storage.Client.from_service_account_json('./credentials.json')  # accedo al cloud storage

    gcBucket = csClient.bucket(bucketName)      # scelgo il bucket
    gcBlob = gcBucket.blob(blobName)            # assegno il nome del file di destinazione
    gcBlob.upload_from_filename(dumpPath)       # carico il file sul cloud
    return

### ACQUISIZIONE RICHIESTE CONTROLLI TENDE
def getControls():
    fileName = "awningControls"
    bucketName = "151780-progetto01"            # definisco il nome del bucket di salvataggio in cloud
    dumpPath=f"/tmp/{fileName}.txt"            # definisco il path di salvataggio locale
    blobName = f"{fileName}.txt"                # definisco il nome del file di salvataggio sul cloud

    csClient = storage.Client.from_service_account_json('./credentials.json')  # accedo al cloud storage

    gcBucket = csClient.bucket(bucketName)      # scelgo il bucket
    gcBlob = gcBucket.blob(blobName)            # assegno il nome del file di destinazione
    gcBlob.download_to_filename(dumpPath)       # scarico il file dal cloud    
    gcBlob.upload_from_string("")               # e lo svuoto

    controlsToRun=""
    with open(dumpPath,mode='r',newline='') as txtFile:         # creo il file locale
        for ctrl in txtFile:
            controlsToRun = controlsToRun + " " + ctrl          # genero una stringa con spazi tra i comandi

    return controlsToRun

### ACQUISIZIONE DATI UTENTI DA FIRESTORE
def getUsersDB():
    usersList = meteoStationDB.collection(collUsers).stream()
    usersDB = {user.to_dict()["username"]: {"password": user.to_dict()["password"],
                                            "email": user.to_dict()["email"]} for user in usersList}
    return usersDB
    
### AGGIORNAMENTO DATI UTENTI SU FIRESTORE ON SIGNUP
def updateUsersDB(username,password,email,usersDB):
    docVal={}
    docVal["username"] = username                   # aggiungo username
    docVal["password"] = password                   # aggiungo password
    docVal["email"] = email                         # aggiungo email
    print("docVal: ",docVal)

    docRef = meteoStationDB.collection(collUsers).document()        # imposto il documento
    docRef.set(docVal)                                              # e lo scrivo
 
    usersDB[username] = {"password": password,"email": email}
    usersDB=getUsersDB()                            # riacquisco il DB completo (più istanze contemporaneamente possibili)
    return usersDB

########################## FUNZIONI SERVER FLASK GENERALI ##########################
### HOME PAGE
@app.route('/', methods=['GET', 'POST'])
def main():
    return render_template('index.html')

### MENU GENERALE
@app.route('/menu', methods=['GET'])
@login_required
def menu():
    return redirect("/static/menu.html")

### ACQUISIZIONE STAZIONE DA VISUALIZZARE
@app.route('/saveStation', methods=['POST'])
def saveStation():
    stationID = request.form['stationID']
    session['stationID'] = f"{stationID}-"
    print(f'Selected value: {stationID}')
    return '', 200

### GRAFICO PIOGGIA
@app.route('/rain', methods=['GET'])
@login_required
def rainGraph():
    stationID = session.get("stationID", 'ras')   # Recupera il valore dalla sessione
    featData = getDataFromDB("rain",showPeriods,stationID)  # acquisisco i dati da DB
    ds=setGraphData(featData)                     # li passo alla pagina html per mostrare il grafico
    return json.dumps(ds),200

### GRAFICO HUMIDITY
@app.route('/humidity', methods=['GET'])
@login_required
def humidityGraph():
    stationID = session.get("stationID", 'ras')   # Recupera il valore dalla sessione
    featData = getDataFromDB("humidity",showPeriods,stationID)  # acquisisco i dati da DB
    ds=setGraphData(featData)                     # li passo alla pagina html per mostrare il grafico
    return json.dumps(ds),200

### GRAFICO TEMPERATURE
@app.route('/temperature', methods=['GET'])
@login_required
def temperatureGraph():
    stationID = session.get("stationID", 'ras')   # Recupera il valore dalla sessione
    featData = getDataFromDB("temperature",showPeriods,stationID)  # acquisisco i dati da DB
    ds=setGraphData(featData)                     # li passo alla pagina html per mostrare il grafico
    return json.dumps(ds),200

### GRAFICO WIND
@app.route('/wind', methods=['GET'])
@login_required
def windGraph():
    stationID = session.get("stationID", 'ras')   # Recupera il valore dalla sessione
    featData = getDataFromDB("wind",showPeriods,stationID)  # acquisisco i dati da DB
    ds=setGraphData(featData)                     # li passo alla pagina html per mostrare il grafico
    return json.dumps(ds),200

### GRAFICO PRESSURE
@app.route('/pressure', methods=['GET'])
@login_required
def pressureGraph():
    stationID = session.get("stationID", 'ras')   # Recupera il valore dalla sessione
    featData = getDataFromDB("pressure",showPeriods,stationID)  # acquisisco i dati da DB
    ds=setGraphData(featData)                     # li passo alla pagina html per mostrare il grafico
    return json.dumps(ds),200

### GRAFICO LIGHTING
@app.route('/lighting', methods=['GET'])
@login_required
def lightingGraph():
    stationID = session.get("stationID", 'ras')   # Recupera il valore dalla sessione
    featData = getDataFromDB("lighting",showPeriods,stationID)  # acquisisco i dati da DB
    ds=setGraphData(featData)                     # li passo alla pagina html per mostrare il grafico
    return json.dumps(ds),200

### GRAFICO FORECASTING PIOGGIA
@app.route('/forecast', methods=['GET'])
@login_required
def forecastGraph():
    global rfModel
    stationID = session.get("stationID", 'ras')   # Recupera il valore dalla sessione

    print("Grafico forecast pioggia")
    collRef = meteoStationDB.collection(collMeteo)      # definisco la collection da leggere e ne leggo gli ultimi elementi necessari per grafico
    qForecast = collRef.where("station", "==", stationID).order_by("sampleTime", direction=firestore.Query.DESCENDING).limit(showPeriods+backwardSamples)
    meteoList = list(qForecast.stream())                # creo la lista dei documenti da graficare sul forecast
    meteoList.reverse()                                 # inverto la lista perchè ero in descending
    ascisse=[]                                          # inizializzo le liste dei dati
    pioggiaPrevista=[]
    pioggiaReale=[]

    for sampleMeteo in meteoList:                       # per ogni documento nella collezione
        sampleDict = sampleMeteo.to_dict()              # appendo il valore alla lista corrispondente
        ascisse.append(sampleDict["sampleTime"])
        pioggiaReale.append(int(sampleDict["rain"]>0))
        pioggiaPrevista.append(int(sampleDict[f"rain10"]))
    ascisse.pop(0)                                      # faccio in modo che la previsione sia allineata al giorno corretto
    pioggiaReale.pop(0)
    pioggiaPrevista.pop(-1)

    accScore=accuracy_score(pioggiaReale, pioggiaPrevista, normalize=True)
    print("Accuracy: ", accScore)
    if accScore < accuracyThreshold: # se accuracy si riduce sottosoglia
        setModelToRetrain()

    ds=[]                                         # li passo alla pagina html per mostrare il grafico
    for i in range(len(ascisse)):
        fTime = str(ascisse[i])[11:-7]
        ds.append([fTime,pioggiaReale[i],pioggiaPrevista[i]])
    return json.dumps(ds),200

### ACQUISIZIONE COMANDO TENDE
@app.route('/awning/<ctrlToRun>', methods=['GET'])
@login_required
def awningControl(ctrlToRun):
    saveControls(ctrlToRun)
    return redirect('/static/controls.html')

### RIACQUISIZIONE MODELLO
@app.route('/model', methods=['POST'])
def modelReload():
    global rfModel
    rfModel=getModel()
    return "model reloaded", 200

### RICHIESTA DATI DA TELEGRAM - OK
@app.route('/chatbot', methods=['POST'])
def getChatbotData():
    atmoEventRequested = request.values["atmoEventRequested"]   # identifico il parametro da mostrare
    graphToSend = request.values["graph"]                       # verifico se è richiesto un grafico
    numSamples = int(request.values["numSamples"])
    stationID = request.values["stationID"]
    
    if graphToSend:
        dataList = getDataFromDB(atmoEventRequested,numSamples,stationID)        # acquisisco i valori dal DB per il grafico
        resp = {"valore":dataList}
    else:
        dataList = getDataFromDB(atmoEventRequested,numSamples,stationID)        # acquisisco il valore dal DB per interrogazione feature
        resp = {"valore":dataList[0][1]}
    return resp

# ### GESTIONE COMANDO TENDE DA TELEGRAM
@app.route('/controls', methods=['POST'])
def controls():
    awningCommand = request.values["awningCommand"]     # acquisco i parametri di chiamata
    awningItem = int(request.values["awningItem"])
    if awningCommand == "up":                           # in base a comando e numero tenda costruisco il comando da inviare al Raspberry
        ctrlToRun = f"t{awningItem}-r"
    if awningCommand == "down":
        ctrlToRun = f"t{awningItem}-e"
    saveControls(ctrlToRun)                             # lo appendo sul file di comunicazione
    resp = "Controllo ricevuto"
    return resp

### ACQUISIZIONE DATI DA RASPBERRY
@app.route('/raspberry', methods=['POST'])
def getRaspberryData():
    global rfModel
    stationID = request.values["stationID"]             # acquisisco i parametri ricevuti
    sTime = request.values["sampleTime"]
    sTimeStr = request.values["sTimeStr"]
    temperatureValue = float(request.values["temperature"])
    humidityValue = float(request.values["humidity"])
    pressureValue = float(request.values["pressure"])
    lightingValue = float(request.values["lighting"])
    rainfallValue = float(request.values["rainfall"])
    windValue = float(request.values["wind"])

       
    collRef = meteoStationDB.collection(collMeteo)          # definisco la collection da leggere e ne leggo gli ultimi elementi necessari per grafico
    qForecast = collRef.order_by("sampleTime", direction=firestore.Query.DESCENDING).limit(backwardSamples)
    meteoList = list(qForecast.stream())                    # creo la lista dei documenti che servono per fare il forecast
    featureColList=["humidity","pressure","temperature","wind"]
    if len(meteoList)>=backwardSamples:                     # se ho sufficienti dati per fare il forecast
        forecastData = [[]]                                 # costruisco l'esempio
        for sampleDoc in meteoList:                         # per ogni esempio acquisito
            sampleData = sampleDoc.to_dict()
            for feat in featureColList:                     # per ogni feature
                forecastData[0].append(sampleData[feat])    # appendo alla lista dati

        rainForecast=int(rfModel.predict(forecastData)[0])       # predico la pioggia
    else:
        rainForecast=0

    # print(stationID,sTime)
    # print(sTimeStr)
    # print("T = ",temperatureValue)
    # print("H = ",humidityValue)
    # print("P = ",pressureValue)
    # print("L = ",lightingValue)
    # print("R = ",rainfallValue)
    # print("W = ",windValue)
    # print("F = ", rainForecast)

    saveDataToDB(stationID,sTime,sTimeStr,temperatureValue,humidityValue,pressureValue,lightingValue,rainfallValue,rainForecast,windValue) # salvo i dati sul DB
    controlsToRun = getControls()   # acquisisco i controlli da effettuare sulle tende da inoltrare al Raspberry
    resp = {"comandi":controlsToRun}# e li invio al Raspberry in risposta
    return resp

########################## FUNZIONI SERVER FLASK LOGIN
### VERIFICA UTENTE
@login.user_loader                      # carico il nome dell'utente loggato
def load_user(username):                # ritorno nome utente se in db altrimenti None
    usersDB=getUsersDB()                # acquisisco i dati degli utenti registrati
    if username in usersDB:
        return User(username)
    return None
    
### SIGNUP NUOVO UTENTE
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        if current_user.is_authenticated:                           # se utente già autenticato lo porto al menu generale
            return redirect(url_for('menu'))
        username = request.values['username']                       # altrimenti acquisisco i dati da pagina html
        email = request.values['email']
        password1 = request.values['password1']
        password2 = request.values['password2']

        usersDB = getUsersDB()                                      # acquisisco i dati degli utenti registrati
        if username == "" or password1 == "" or email == "":        # dse non ho compilato tutti i campi
            flash('Fill in all fields', 'error')
            return render_template('signup.html')
        if email in [valDict["email"] for valDict in usersDB.values()]: # se mail già usata segnalo e richiedo
            flash('e-mail already exists', 'error')
            return render_template('signup.html')
        if username in usersDB:                                     # se l'utente esiste già
            flash('Username already exists', 'error')
            return render_template('signup.html')
        if password1 != password2:                                  # se le 2 password non sono uguali
            flash("Passwords don't match", 'error')
            return render_template('signup.html')
        
        usersDB = updateUsersDB(username,password1,email,usersDB)           # altrimenti aggiorno DB
        flash("User correctly registered. You can now login", 'notify')
        return render_template("login.html")
    return render_template('signup.html')

### LOGIN UTENTE
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if current_user.is_authenticated:
            return redirect(url_for('menu'))
        
        username = request.values['username']
        password = request.values['password']

        usersDB = getUsersDB()
        if username in usersDB and password == usersDB[username]["password"]:
            login_user(User(username))
            return redirect(url_for('menu'))
        
        flash('Invalid username or password', 'error')
        return redirect(url_for('login'))

    return render_template('login.html')

### LOGOUT UTENTE
@app.route('/logout', methods=["POST"])
def logout():
    logout_user()
    return redirect(url_for('main'))


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=80, debug=False)

