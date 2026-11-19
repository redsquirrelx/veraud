import base64
import pickle

def load_session(data):
    return pickle.loads(base64.b64decode(data))
