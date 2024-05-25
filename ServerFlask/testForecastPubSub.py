from google.cloud import pubsub_v1
from google.auth import jwt
import json


myProj = "progetto01-417313"
myTopic = "trainRetrainReq"

servAccount = json.load(open("credentials.json"))
audience = "https://pubsub.googleapis.com/google.pubsub.v1.Publisher"
credentials = jwt.Credentials.from_service_account_info(servAccount, audience=audience)
publisher = pubsub_v1.PublisherClient(credentials=credentials)
topic_path = publisher.topic_path(myProj, myTopic)
r = publisher.publish(topic_path, b'Retrain model')
print(r.result())