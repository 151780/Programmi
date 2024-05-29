from google.cloud import firestore, storage
from google.cloud import pubsub_v1
from google.auth import jwt
import time
import json
import schedule
import csv
from requests import post

from vmURL import baseURL

# apertura connessione DB Firestore
dbName = 'db151780'
collUsers = 'Users'
collMeteo = 'MeteoData'
meteoStationDB = firestore.Client.from_service_account_json('credentials.json', database=dbName)


#### INVIO RICHIESTA DI RETRAIN CON PUBSUB
def modelRetrain():
    modelToRetrain = False

    fileName = "retrainRequest"
    bucketName = "151780-progetto01"            # definisco il nome del bucket di salvataggio in cloud
    dumpPath=f"tmp/{fileName}.txt"            # definisco il path di salvataggio locale
    blobName = f"{fileName}.txt"                # definisco il nome del file di salvataggio sul cloud

    csClient = storage.Client.from_service_account_json('./credentials.json')  # accedo al cloud storage

    gcBucket = csClient.bucket(bucketName)      # scelgo il bucket
    gcBlob = gcBucket.blob(blobName)            # assegno il nome del file di destinazione
    gcBlob.download_to_filename(dumpPath)       # scarico il file dal cloud    
    gcBlob.upload_from_string("")               # e lo svuoto

    controlsToRun=""
    with open(dumpPath,mode='r',newline='') as txtFile:         # creo il file locale
        for txtLine in txtFile:
            if txtLine == "retrain":
                modelToRetrain = True
                break

    if modelToRetrain:
        print(" ***** RETRAINING MODEL *****")

        myProj = "progetto01-417313"
        myTopic = "trainRetrainReq"

        servAccount = json.load(open("credentials.json"))
        audience = "https://pubsub.googleapis.com/google.pubsub.v1.Publisher"
        credentials = jwt.Credentials.from_service_account_info(servAccount, audience=audience)
        publisher = pubsub_v1.PublisherClient(credentials=credentials)
        topic_path = publisher.topic_path(myProj, myTopic)
        r = publisher.publish(topic_path, b'Retrain model', type=b"retrain")
        print(r.result())

        r = post(f"{baseURL}/model")
    else:
        print(" ***** RETRAINING NOT NEEDED *****")

        return

### SALVATAGGIO DATI SENSORI SU FILE CSV IN STORAGE PER LOOKER #
def saveDataToCloudStorage():
    print(" ***** SAVING TO STORAGE *****")
    fileName = "MeteoData"
    bucketName = "151780-progetto01"            # definisco il nome del bucket di salvataggio in cloud
    dumpPath=f"tmp/{fileName}.csv"            # definisco il path di salvataggio locale
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


schedule.every(60).seconds.do(modelRetrain)         # verifica periodica se necessita retrain del modello
schedule.every(10).minutes.do(saveDataToCloudStorage)         # aggiornamento periodico cloud storage per looker


try:
    while True: # ripeti fino a keypressed
        schedule.run_pending()
        time.sleep(10)
except KeyboardInterrupt:
    pass
