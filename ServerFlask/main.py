from flask import Flask,request,redirect,url_for,render_template,jsonify,flash
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
login.login_view = '/static/login.html'

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
    dumpPath=f"/tmp/{clfName}.joblib"      # definisco il path di salvataggio locale del modello
    blobName = f"{clfName}.joblib"          # definisco il nome del file di salvataggio sul cloud

    csClient = storage.Client.from_service_account_json('./credentials.json')  # accedo al cloud storage

    gcBucket = csClient.bucket(bucketName)      # scelgo il bucket
    gcBlob = gcBucket.blob(blobName)            # assegno il nome del file di destinazione
    gcBlob.download_to_filename(dumpPath)       # scarico il file dal cloud    

    rf = load(dumpPath)                         # salvo in locale il modello
    return rf

rfModel = getModel()                                # variabile contenente il modello di forecasting

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

### SALVATAGGIO DATI SENSORI SU FILE CSV IN STORAGE PER LOOKER
def saveDataToCloudStorage():
    fileName = "MeteoData"
    bucketName = "151780-progetto01"            # definisco il nome del bucket di salvataggio in cloud
    dumpPath=f"/tmp/{fileName}.csv"            # definisco il path di salvataggio locale
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
    dumpPath=f"/tmp/{fileName}.txt"            # definisco il path di salvataggio locale
    blobName = f"{fileName}.txt"                # definisco il nome del file di salvataggio sul cloud

    with open(dumpPath,mode='a',newline='') as txtFile:         # creo il file locale
        writer = csv.writer(txtFile)
        writer.writerow(ctrlToRun)

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
            controlsToRun = controlsToRun + " " + ctrl

    return controlsToRun

### ACQUISIZIONE DATI UTENTI DA FIRESTORE
def getUsersDB():
    usersList = meteoStationDB.collection(collUsers).stream()
    usersDB = {user.to_dict()["username"]: {"password": user.to_dict()["password"],
                                            "email": user.to_dict()["email"]} for user in usersList}
    return usersDB
    
### AGGIORNAMENTO DATI UTENTI SU FIRESTORE ON SIGNUP
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
    usersDB=getUsersDB()                            # riacquisco il DB completo (più istanze contemporaneamente possibili)
    return usersDB

########################## FUNZIONI SERVER FLASK GENERALI ##########################
### HOME PAGE
@app.route('/',methods=['GET'])
def main():
    return redirect("/static/index.html")

### MENU GENERALE
@app.route('/menu', methods=['GET'])
@login_required
def menu():
    return redirect("/static/menu.html")

### GRAFICO PIOGGIA
@app.route('/rain', methods=['GET'])
@login_required
def rainGraph():
    featData = getDataFromDB("rain",showPeriods)  # acquisisco i dati da DB
    ds=[]                                         # li passo alla pagina html per mostrare il grafico
    i=1
    for fData in featData:                        # creo il dataset da inviare alla pagina per il grafico
        fTime = str(fData[0].strftime("%H:%M:%S"))
        ds.append([fTime,fData[1]])
        i+=1
    return json.dumps(ds),200

### GRAFICO HUMIDITY
@app.route('/humidity', methods=['GET'])
@login_required
def humidityGraph():
    featData = getDataFromDB("humidity",showPeriods)  # acquisisco i dati da DB
    ds=[]                                         # li passo alla pagina html per mostrare il grafico
    i=1
    for fData in featData:
        fTime = str(fData[0].strftime("%H:%M:%S"))
        ds.append([fTime,fData[1]])
        i+=1
    return json.dumps(ds),200

### GRAFICO TEMPERATURE
@app.route('/temperature', methods=['GET'])
@login_required
def temperatureGraph():
    featData = getDataFromDB("temperature",showPeriods)  # acquisisco i dati da DB
    ds=[]                                         # li passo alla pagina html per mostrare il grafico
    i=1
    for fData in featData:
        fTime = str(fData[0].strftime("%H:%M:%S"))
        ds.append([fTime,fData[1]])
        i+=1
    return json.dumps(ds),200

### GRAFICO WIND
@app.route('/wind', methods=['GET'])
@login_required
def windGraph():
    featData = getDataFromDB("wind",showPeriods)  # acquisisco i dati da DB
    ds=[]                                         # li passo alla pagina html per mostrare il grafico
    i=1
    for fData in featData:
        fTime = str(fData[0].strftime("%H:%M:%S"))
        ds.append([fTime,fData[1]])
        i+=1
    return json.dumps(ds),200

### GRAFICO PRESSURE
@app.route('/pressure', methods=['GET'])
@login_required
def pressureGraph():
    featData = getDataFromDB("pressure",showPeriods)  # acquisisco i dati da DB
    ds=[]                                         # li passo alla pagina html per mostrare il grafico
    i=1
    for fData in featData:
        fTime = str(fData[0].strftime("%H:%M:%S"))
        ds.append([fTime,fData[1]])
        i+=1
    return json.dumps(ds),200

### GRAFICO LIGHTING
@app.route('/lighting', methods=['GET'])
@login_required
def lightingGraph():
    featData = getDataFromDB("lighting",showPeriods)  # acquisisco i dati da DB
    ds=[]                                         # li passo alla pagina html per mostrare il grafico
    i=1
    for fData in featData:
        fTime = str(fData[0].strftime("%H:%M:%S"))
        ds.append([fTime,fData[1]])
        i+=1
    return json.dumps(ds),200

### GRAFICO FORECASTING PIOGGIA
@app.route('/forecast', methods=['GET'])
@login_required
def forecastGraph():
    global modelToRetrain

    print("Grafico forecast pioggia")
    collRef = meteoStationDB.collection(collMeteo)      # definisco la collection da leggere e ne leggo gli ultimi elementi necessari per grafico
    qForecast = collRef.order_by("sampleTime", direction=firestore.Query.DESCENDING).limit(showPeriods+backwardSamples)
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

    if accuracy_score(pioggiaReale, pioggiaPrevista, normalize=True) < accuracyThreshold: # se accuracy si riduce sottosoglia
        modelToRetrain = True

    ds=[]                                         # li passo alla pagina html per mostrare il grafico
    for i in range(len(ascisse)):
        fTime = str(ascisse[i].strftime("%H:%M:%S"))
        ds.append([fTime,pioggiaReale[i]+2,pioggiaPrevista[i]])
    print(ds)
    return json.dumps(ds),200

### GESTIONE COMANDO TENDE
@app.route('/controls', methods=['GET'])
@login_required
def controls():
    print("Controlli")
    return redirect('/static/controls.html')

### ACQUISIZIONE COMANDO TENDE
@app.route('/awning/<ctrlToRun>', methods=['GET'])
@login_required
def awningControl(ctrlToRun):
    saveControls(ctrlToRun)
    return redirect('/static/controls.html')

### RICHIESTA DATI DA TELEGRAM - OK
@app.route('/chatbot', methods=['POST'])
def getChatbotData():
    atmoEventRequested = request.values["atmoEventRequested"]   # identifico il parametro da mostrare
    
    dataList = getDataFromDB(atmoEventRequested,1)        # acquisisco il valore dal DB
    resp = {"valore":dataList[0][1]}
    return resp

### ACQUISIZIONE DATI DA RASPBERRY
@app.route('/raspberry', methods=['POST'])
def getRaspberryData():
    global rfModel
    stationID = request.values["stationID"]
    sTime = request.values["sampleTime"]
    sTimeStr = request.values["sTimeStr"]
    temperatureValue = float(request.values["temperature"])
    humidityValue = float(request.values["humidity"])
    pressureValue = float(request.values["pressure"])
    lightingValue = float(request.values["lighting"])
    rainfallValue = float(request.values["rainfall"])
    windValue = float(request.values["wind"])

    print(stationID,sTime)
    print(sTimeStr)
    print("T = ",temperatureValue)
    print("H = ",humidityValue)
    print("P = ",pressureValue)
    print("L = ",lightingValue)
    print("R = ",rainfallValue)
    print("W = ",windValue)
       
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


    saveDataToDB(stationID,sTime,sTimeStr,temperatureValue,humidityValue,pressureValue,lightingValue,rainfallValue,rainForecast,windValue) # salvo i dati sul DB
    controlsToRun = getControls()   # acquisisco i controlli da effettuare sulle tende da inoltrare al Raspberry
    return controlsToRun, 200

########################## FUNZIONI SERVER FLASK LOGIN
### VERIFICA UTENTE
@login.user_loader                      # carico il nome dell'utente loggato
def load_user(username):                # ritorno nome utente se in db altrimenti None
    usersDB=getUsersDB()                # acquisisco i dati degli utenti registrati
    if username in usersDB:
        return User(username)
    return None
    
### SIGNUP NUOVO UTENTE
@app.route('/sign_up', methods=['POST'])
def signup():
    if current_user.is_authenticated:                           # se utente già autenticato lo porto al menu generale
        return redirect(url_for('/static/menu.html'))
    username = request.values['username']                       # altrimenti acquisisco i dati da pagina html
    email = request.values['email']
    password1 = request.values['password1']
    password2 = request.values['password2']

    usersDB = getUsersDB()                                      # acquisisco i dati degli utenti registrati
    if username in usersDB:                                     # se utente o mail già in DB o se password diverse ripropongo
        return redirect('/static/sign_up.html')
    if password1 != password2:
        return redirect('/static/sign_up.html')
    if email in [valDict["email"] for valDict in usersDB.values()]:
        return redirect('/static/sign_up.html')
    
    usersDB = updateUsersDB(username,password1,email)           # altrimenti aggiorno DB
    return redirect('/static/login.html')

### LOGIN UTENTE
@app.route('/login', methods=['POST'])
def login():
    if current_user.is_authenticated:                   # se utente già autenticato lo porto al menu generale
        return redirect(url_for('/static/menu.html'))
    username = request.values['username']               # altrimenti acquisisco i dati da pagina html
    password = request.values['password']

    usersDB = getUsersDB()                              # acquisisco i dati degli utenti registrati
                                                        # (lo devo fare ogni volta perchè se ho più istanze potrei avere aggiornamenti da altre istanze del DB)
    if username in usersDB and password == usersDB[username]["password"]:   # se registrato e password ok
        login_user(User(username))                                          # lo porto al menu generale
        return redirect('/static/menu.html')
    
    return redirect('/static/login.html')               # altrimenti lo riporto a login con errore

### LOGOUT UTENTE
@app.route('/logout', methods=["POST"])
def logout():
    logout_user()
    return redirect('/static/index.html')


if __name__ == '__main__':

    schedule.every(10).minutes.do(modelRetrain)         # verifica periodica se necessita retrain del modello
    schedule.every(5).minutes.do(saveDataToCloudStorage)         # aggiornamento periodico cloud storage per looker
    app.run(host='0.0.0.0', port=80, debug=False)

