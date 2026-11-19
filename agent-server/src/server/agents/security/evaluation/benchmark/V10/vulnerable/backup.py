import os

def backup(path):
    os.system("tar -czf backup.tgz " + path)
