import pandas as pd
import calendar
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error
from joblib import dump, load
from google.cloud import firestore, storage
def retrain(event, context):
    #db = firestore.Client.from_service_account_json('../credentials.json', database='sensors')
    db = firestore.Client(database='sensors')
    coll = 'data'
    s = 's1'
    doc_ref = db.collection(coll).document(s)
    diz = doc_ref.get().to_dict()['values']
    dates = list(diz.keys())
    values = list(diz.values())
    df = pd.DataFrame({'datetime':dates,'PM10':values})

    #df = pd.read_csv('CleanData_PM10.csv')
    print(df)
    df['datetime'] = pd.to_datetime(df['datetime'], format='%Y-%m-%d %H:%M:%S')
    df['weekday'] = df['datetime'].apply(lambda t: calendar.day_name[t.weekday()])
    df['weekend01'] = df['weekday'].apply(lambda w: 1 if (w == 'Saturday' or w == 'Sunday') else 0)
    df['PM10-1'] = df['PM10'].shift(1)
    df['PM10-2'] = df['PM10'].shift(2)
    df['PM10-3'] = df['PM10'].shift(3)
    df = df.iloc[3:, :]
    train = df
    model = LinearRegression()
    model.fit(train.loc[:,['PM10-1','PM10-2','PM10-3','weekend01']], train['PM10'])
    print('MAE = ', mean_absolute_error(df['PM10'], model.predict(df[['PM10-1','PM10-2','PM10-3','weekend01']])))
    dump(model, '/tmp/model.joblib')

    #client = storage.Client.from_service_account_json('../credentials.json')
    client = storage.Client()
    bucket = client.bucket('pcloud2024-models')
    source_file_name = '/tmp/model.joblib'
    destination_blob_name = 'model.joblib'
    blob = bucket.blob(destination_blob_name)
    blob.upload_from_filename(source_file_name)


'''
if __name__ == '__main__':
    retrain(None,None)
'''