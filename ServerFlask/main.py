from flask import Flask,request,redirect,url_for,render_template,jsonify
from flask_login import LoginManager, current_user, login_user, logout_user, login_required, UserMixin
from secret import secret_key
from google.cloud import firestore
from joblib import load

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

# apertura connessione DB Firestore
dbName = 'db151780'
collUsers = 'Users'
collMeteo = 'MeteoData'
meteoStationDB = firestore.Client.from_service_account_json('credentials.json', database=dbName)
# db = firestore.Client(database=dbName)
usersDB = {}


### Home page
@app.route('/',methods=['GET'])
def main():
    return redirect("/static/index.html")

### Menu generale
@app.route('/menu', methods=['GET'])
@login_required
def menu():
    return redirect("/static/menu.html")

### Grafico pioggia
@app.route('/rain', methods=['GET'])
@login_required
def rainGraph():
    print("Grafico pioggia")
    ds={}
    return render_template('/static/rain.html',data=ds)

### Forecasting pioggia
@app.route('/forecast', methods=['GET'])
@login_required
def forecastGraph():
    print("Grafico forecast pioggia")
    # model = load('model.joblib')
    # for i in range(10):
    #     yp = model.predict([[r[-1][1],r[-2][1],r[-3][1],0]])
    #     r.append([len(r),yp[0]])
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
    print("SONO QUI")
    data = request.values["data"]
    val = float(request.values["val"])
    print(data,val)
    return "ok", 200
# @app.route('/raspberry', methods=['POST'])
# def raspberryData():
#     stationID = request.values["stationID"]
#     sampleTime = request.values["sampleTime"]
#     sampleRain = request.values["sampleRain"]
#     saveDataToDB(stationID,sampleTime,sampleRain)
#     return "ok", 200

### Richiesta dati operazioni da Raspberry
@app.route('/raspberry', methods=['GET'])
def raspberryInform():
    dataFromDB = getDataFromDB()
    return jsonify(dataFromDB)

### Salvataggio dati sensori su Firestore
def saveDataToDB(stID,sTime,sRain):
    print("salvataggio dati")
    print("stID: ",stID)
    print("sTime: ",sTime)
    print("sRain: ",sRain)
    sensColl = meteoStationDB.collection(collMeteo)                 # apertura collezione
    # sTimeStr = sTime.strftime("%Y/%m/%d-%H:%M:%S")                  # preparo ID documento da scrivere come ID stazione concatenato con dataora
    docID = stID + sTime
    docVal={}
    docVal["stationID"] = stID                                      # aggiungo ID stazione
    docVal["sampleTime"] = sTime                                    # aggiungo dataora rilevazione
    docVal["rain"] = sRain                                          # aggiungo pioggia

    docRef = sensColl.document(docID)                               # imposto il documento
    docRef.set(docVal)                                              # e lo scrivo
   
    return 'Data saved',200

### Acquisizione dati da Firestore
def getDataFromDB():
    print("lettura dati")
    return 'ok',200

### Verifica utente ###
@login.user_loader                      # carico il nome dell'utente loggato
def load_user(username):                # ritorno nome utente se in db altrimenti None
    if username in usersDB:
        return User(username)
    return None

### Acquisizione dati utenti da Firestore
def getUsersDB():
    usersList = meteoStationDB.collection(collUsers).stream()
    usersDB = {user.to_dict()["username"]: user.to_dict()["password"] for user in usersList}
    print(usersDB)
    return usersDB
    
### Login utente ###
@app.route('/login', methods=['POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('/menu.html'))
    username = request.values['username']
    password = request.values['password']

    if username in usersDB and password == usersDB[username]:
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
    app.run(host='0.0.0.0', port=80, debug=False)

