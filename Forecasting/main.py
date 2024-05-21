import pandas as pd
from sklearn.metrics import mean_absolute_error
from joblib import dump, load
from google.cloud import firestore, storage
import os

from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import MinMaxScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics import confusion_matrix, classification_report



def trainRetrain(event, context):
    backwardGap = 10        # indica da quanti passi indietro devo partire per il forecast
    backwardSamples = 1     # indica quanti campioni devo inserire per forecast
                            # es:   se backwardGap = 10 e backwardSamples = 5
                            #       considero per il forecast a t le rilevazioni da t-10 a t-6

    if os.path.isfile("./credentials.json"):
        local = True
    else:
        local = False
    
    # apertura connessione DB Firestore
    dbName = 'db151780'
    collMeteo = 'MeteoData'
    if local:
        meteoStationDB = firestore.Client.from_service_account_json('credentials.json', database=dbName)
    else:
        meteoStationDB = firestore.Client(database=dbName)

    collRef = meteoStationDB.collection(collMeteo)  # acquisisco tutta la collezione dei dati meteo
    docsMeteoData = collRef.stream()
    meteoDataList = []                              # e la metto in un dataframe
    for docMD in docsMeteoData:
        meteoDataList.append(docMD.to_dict())
    meteoDatadf = pd.DataFrame(meteoDataList)

    featureColList=["humidity","pressure","temperature"]    # definisco le feature su cui basare il forecast

    for i in range(1,backwardSamples+1):                    # costruisco le feature del passato
        for col in featureColList:
            meteoDatadf[f"{col}_{i}"]=meteoDatadf[col].shift(i)

    meteoDatadf["rainBool"]=(meteoDatadf["rain"]>0)         # aggiungo la colonna booleana che indica se piove o meno

    columnToRemove=["humidity","pressure","temperature","sampleTime","lighting","rain",f"rain{backwardGap}","stationID"]     # definisco le colonne che non servono per il forecast
    meteoDatadf = meteoDatadf.drop(columns=columnToRemove)          # e le rimuovo
    meteoDatadf = meteoDatadf.iloc[backwardGap:]                    # rimuovo le prime righe che non hanno colonne valide per forecast

    print(meteoDatadf)
    # input()


    # Creo classificatore
    rs=None     # random state per test

    X = meteoDatadf.drop(columns=["rainBool"])      # creo il df delle feature
    y = meteoDatadf["rainBool"]                     # creo i termini noti

    # divido il dataframe in train test validation
    X_trainval, X_test, y_trainval, y_test = train_test_split(X, y, test_size=0.3, random_state=rs)
    X_train, X_val, y_train, y_val = train_test_split(X_trainval, y_trainval, test_size=0.3, random_state=rs)
    # normalizzo con MinMax
    scaler=MinMaxScaler()
    X_train=scaler.fit_transform(X_train)
    X_test=scaler.transform(X_test)
    X_trainval=scaler.transform(X_trainval)
    X_val=scaler.transform(X_val)

    rf = RandomForestClassifier()       # classifico con random forest
    rf.fit(X_trainval, y_trainval)      # creo il modello

    y_pred=rf.predict(X_test)           # effettuo predizione
    print(y_pred)

    # stampo statistiche del classificatore
    print("--> CLASSIFICATORE RANDOM FOREST ")        
    print()
    print(confusion_matrix(y_test, y_pred))
    print()
    print(classification_report(y_test, y_pred, zero_division=0))
    print()

    # salvo il modello in cloud
    clfName = "rfClass"
    bucketName = "151780-progetto01"        # definisco il nome del bucket di salvatoaggio in cloud
    dumpPath=f"./tmp/{clfName}.joblib"       # definisco il path di salvataggio locale del modello
    blobName = f"{clfName}.joblib"          # definisco il nome del file di salvataggio sul cloud

    dump(rf, dumpPath)                      # salvo in locale il modello

    if local:
        csClient = storage.Client.from_service_account_json('./credentials.json')  # accedo al cloud storage
    else:
        csClient = storage.Client()
    gcBucket = csClient.bucket(bucketName)      # scelgo il bucket
    gcBlob = gcBucket.blob(blobName)            # assegno il nome del file di destinazione
    gcBlob.upload_from_filename(dumpPath)       # carico il file sul cloud

if __name__ == '__main__':
    trainRetrain(None,None)


