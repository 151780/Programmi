import logging
import os
import sys
import json
import matplotlib.pyplot as plt
from requests import post

from telegram import ForceReply, Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from secret import bot_token 

parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, parent_dir)
from vmURL import baseURL

# baseURL = 'http://34.154.156.218:80'
# baseURL = 'http://192.168.1.50:80'


# Definisco il dizionario di aiuto e similari
helpDict={"rain": "Ricevi l'informazione di quanta pioggia in mm/h stia cadendo al momento della richiesta\n",
            "wind": "Ricevi l'informazione della velocità del vento in m/s al momento della richiesta\n",
            "humidity": "Ricevi l'informazione dell'umidità percentuale al momento della richiesta\n",
            "pressure": "Ricevi l'informazione della pressione atmosferica in hPa al momento della richiesta\n",
            "temperature": "Ricevi l'informazione della temperatura esterna in °C al momento della richiesta\n",
            "lighting": "Ricevi l'informazione del fattore di illuminazione percentuale al momento della richiesta\n",
            "forecast": "Ricevi la previsione di pioggia a breve termine basata sui parametri attuali\n",
            "all": "Ricevi l'informazione completa della situazione atmosferica|n",
            "global": "Digita\n/start per avviare il bot\n/help per aiuto\n/help <feature> per aiuto sulla specifica feature\n/graph <feature> <numero osservazioni> per andamento della specifica feature (escluso forecast e all) nelle ultime <numero osservazioni> (30 se non definito)\n/awning <command> <numero_tenda>per controllare la posizione della tenda <numero_tenda>; <command> = up - down;\n\noppure uno dei seguenti per avere i dati relativi alla feature\n   Rain\n   Wind\n   Humidity\n   Pressure\n   Temperature\n   Light\n   Forecast\n   All",
            }
umDict={"rain": "mm/h",
            "wind": "m/s",
            "humidity": "%",
            "pressure": "hPa",
            "temperature": "°C",
            "lighting": "%",
            }


# Acquisisco le info dell'utente
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)    # imposto livello alto di log
logger = logging.getLogger(__name__)

# Invio messaggio di benvenuto al comando di start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    await update.message.reply_html(
        rf"Benvenuto {user.mention_html()}!",
        reply_markup=ForceReply(selective=True),
    )

# Invio informazioni di help generiche o in base al comando
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user                        # acquisisco il nome del richiedente
    msg=f"Sono qui per aiutarti, {user.first_name}\n"   # inizializzo il messaggio di risposta
    messageText=update.message.text.lower()             # metto tutto in minuscolo il messaggio
    linea=tuple(messageText.split())                    # divido il messaggio
    try:                                                # verifico se alla richiesta di aiuto è associato un parametro
        globale = linea[1] not in helpDict
    except IndexError:
        globale = True

    if globale:                                         # se non c'è parametro o parametro non esistente
        msg+=helpDict["global"]                         # mostro aiuto completo
    else:                                               # altrimenti
        msg+=helpDict[linea[1]]                         # mostro aiuto di comando
    await update.message.reply_text(msg)                # invio la risposta

# Gestione comando tende
async def awning_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user                            # acquisisco il nome del richiedente
    messageText=update.message.text.lower()                 # metto tutto in minuscolo il messaggio
    linea=tuple(messageText.split())                        # divido il messaggio
    try:                                                    # verifico se alla richiesta di aiuto è associato un parametro corretto
        globale = linea[1] not in ["up","down"]
    except IndexError:
        globale = True

    if globale:                                             # se non c'è parametro o parametro non esistente
        msg=f"La tua richiesta non è corretta, {user.first_name}\n"
        msg+="Ecco un po' di aiuto\n\n"+helpDict["global"]
    else:  
        awningCommand=linea[1]                              # acquisisco il comando da effettuare 
        try:                                                # verifico se alla richiesta è associato il parametro tenda
            awningItem = int(linea[2])
        except IndexError:
            awningItem = 1

        resp = post(f'{baseURL}/controls',data={"awningCommand":awningCommand,"awningItem":awningItem}) # richiedo al server di registrare la richiesta
        statusCode = resp.status_code

        if statusCode == 200:
            msg=f"La tua richiesta è andata a buon fine, {user.first_name}\n"
        else:
            msg=f"La tua richiesta non è andata a buon fine, {user.first_name}\nRiprova più tardi"
    await update.message.reply_text(msg)                # invio la risposta

# Invio grafico richiesto
async def graph_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user                        # acquisisco il nome del richiedente
    # msg=f"Sono qui per aiutarti, {user.first_name}\n"   # inizializzo il messaggio di risposta
    messageText=update.message.text.lower()             # metto tutto in minuscolo il messaggio
    linea=tuple(messageText.split())                    # divido il messaggio
    try:                                                # verifico se alla richiesta di aiuto è associato un parametro
        globale = linea[1] not in helpDict
    except IndexError:
        globale = True

    if globale:                                         # se non c'è parametro o parametro non esistente
        msg=f"La tua richiesta non è corretta, {user.first_name}\n"
        msg+="Ecco un po' di aiuto\n\n"+helpDict["global"]
        await update.message.reply_text(msg)                # invio la risposta
    else:  
        try:                                                # verifico se alla richiesta di aiuto è associato il secondo parametro
            numSamples = int(linea[2])
        except IndexError:
            numSamples = 30

        if numSamples<0 or numSamples>50:
            numSamples=30
        atmoEventRequested=linea[1]                         # associo il nome della 
        resp = post(f'{baseURL}/chatbot',data={"atmoEventRequested":atmoEventRequested,"graph":True,"numSamples":numSamples})

        featData = resp.json()["valore"]

        dataTimes = [fData[0][11:] for fData in featData[-numSamples:]]
        dataValues = [fData[1] for fData in featData[-numSamples:]]

        plt.figure(figsize=(10, 6))
        plt.plot(dataTimes, dataValues, marker='.')
        plt.xlabel('Time')
        numTicks = 8
        gapTicks = numSamples // numTicks
        plt.xticks(ticks=range(0, len(dataTimes), gapTicks), labels=[dataTimes[i] for i in range(0, len(dataTimes), gapTicks)], rotation=60)
        # plt.ylabel(f"{atmoEventRequested}{umDict[atmoEventRequested]}")
        plt.title(f"{atmoEventRequested[0].upper()}{atmoEventRequested[1:]} [{umDict[atmoEventRequested]}]")
        plt.grid(True)
        plt.tight_layout()

        imgName = f"{atmoEventRequested}.png"
        plt.savefig(imgName, format='png')
        plt.close()

        await update.message.reply_photo(photo=open(imgName, 'rb'))
        os.remove(imgName)

# Gestione della richiesta di informazioni meteo in base al parametro
async def answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user                        # acquisisco il nome del richiedente
    messageText=update.message.text.lower()             # metto tutto in minuscolo il messaggio
    linea=tuple(messageText.split())                    # divido il messaggio

    funzioneRichiesta=linea[0]                          # estraggo il nome del parametro richiesto
    if funzioneRichiesta not in helpDict:               # se parametro non esiste lo segnalo
        msg=f"La tua richiesta non è corretta, {user.first_name}\n"
        msg+="Ecco un po' di aiuto\n\n"+helpDict["global"]
    else:                                               # altrimenti notifico il valore
        msg=f"{user.first_name}, eccoti i dati richiesti\n"
        callFnc = globals().get(funzioneRichiesta)
        valFeat=callFnc()
        msg+=f"{valFeat}"
    await update.message.reply_text(msg)


def rain():
    resp = post(f'{baseURL}/chatbot',data={"atmoEventRequested":"rain","graph":False,"numSamples":1})    # chiamo il server per acquisire i dati dell'ultima rilevazione
    valFeat = "Stanno cadendo {:4.1f} mm/h di pioggia\n".format(resp.json()["valore"][0][1])
    return valFeat

def wind():
    resp = post(f'{baseURL}/chatbot',data={"atmoEventRequested":"wind","graph":False,"numSamples":1})    # chiamo il server per acquisire i dati dell'ultima rilevazione
    valFeat = "La velocità del vento è {:4.1f} m/s\n".format(resp.json()["valore"][0][1])
    return valFeat

def humidity():
    resp = post(f'{baseURL}/chatbot',data={"atmoEventRequested":"humidity","graph":False,"numSamples":1})    # chiamo il server per acquisire i dati dell'ultima rilevazione
    valFeat = "L'umidità è del {:d}%\n".format(int(resp.json()["valore"][0][1]))
    return valFeat

def pressure():
    resp = post(f'{baseURL}/chatbot',data={"atmoEventRequested":"pressure","graph":False,"numSamples":1})    # chiamo il server per acquisire i dati dell'ultima rilevazione
    valFeat = "La pressione atmosferica è di {:6.1f} hPa\n".format(resp.json()["valore"][0][1])
    return valFeat

def temperature():
    resp = post(f'{baseURL}/chatbot',data={"atmoEventRequested":"temperature","graph":False,"numSamples":1})    # chiamo il server per acquisire i dati dell'ultima rilevazione
    valFeat = "La temperatura esterna è di {:4.1f} °C\n".format(resp.json()["valore"][0][1])
    return valFeat

def lighting():
    resp = post(f'{baseURL}/chatbot',data={"atmoEventRequested":"lighting","graph":False,"numSamples":1})    # chiamo il server per acquisire i dati dell'ultima rilevazione
    valFeat = "Il fattore di illuminazione è del {:d}%\n".format(int(resp.json()["valore"][0][1]))
    return valFeat

def forecast():
    resp = post(f'{baseURL}/chatbot',data={"atmoEventRequested":"rain10","graph":False,"numSamples":1})    # chiamo il server per acquisire i dati dell'ultima rilevazione
    respValue = int(resp.json()["valore"][0][1])
    if respValue == 0:
        valFeat = "Non prevedo pioggia a breve termine\n"
    else:
        valFeat = "Prevedo pioggia a breve termine\n"
    return valFeat

def all():
    valFeat = ""
    valFeat = valFeat + temperature() + pressure() + humidity() + wind() + lighting() + rain() + forecast()
    # valFeat = valFeat + temperature() + pressure() + humidity() + lighting() + rain() + forecast()
    return valFeat

# Gestione dell'invio di foto
async def photoAnswer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    photo_file = await update.message.photo[-1].get_file()      # acquisisco il file
    await photo_file.download_to_drive()                        # lo scarico sul disco locale
    await update.message.reply_text('Foto ricevuta e salvata!') # inv messaggio di commit

# Gestione dell'invio della posizione
async def locationAnswer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user                # acquisisco il nome del richiedente
    userLocation = update.message.location      # acquisisco la sua posizione
    replyText = "{}, la tua posizione è: latitudine {:10.6f} - longitudine {:10.6f}".format(user.first_name,userLocation.latitude,userLocation.longitude)
    await update.message.reply_text(replyText)  # rispondo con il messaggio contenente le coordinate della posizione


def main() -> None:
    # Creo applicazione con token definito
    application = Application.builder().token(bot_token).build()

    # Definisco gli handler per le differenti chiamate di comando
    application.add_handler(CommandHandler("start", start))         # comando di start
    application.add_handler(CommandHandler("help", help_command))   # comando di aiuto
    application.add_handler(CommandHandler("aiuto", help_command))
    application.add_handler(CommandHandler("graph", graph_command))   # comando di invio grafico
    application.add_handler(CommandHandler("awning", awning_command))   # comando di operazioni tende

    # Definisco l'handler per tutto ciò che è testo e non è un comando
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, answer))

    # Definisco l'handler per le foto
    application.add_handler(MessageHandler(filters.PHOTO, photoAnswer))

    # Definisco l'handler per la posizione
    application.add_handler(MessageHandler(filters.LOCATION, locationAnswer))

    # Inizio il polling fino a ^C
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()