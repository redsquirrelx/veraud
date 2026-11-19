import yaml

def load_config(text):
    return yaml.load(text, Loader=yaml.Loader)
