import uuid
import os
import json
from datetime import datetime, timedelta

LOG_LOCATION = 'components/logs/log.log'
LOG_LIMIT = 100

# ensure log file exists
try:
    open(LOG_LOCATION, 'r')
except FileNotFoundError:
    open(LOG_LOCATION, 'w').close()

# DO NOT CHANGE
VERSION_NUMBER = '0.5'

def can_generate_new_key(key_data):
    """Check if enough time has passed to generate a new key"""
    if not key_data.get('last_generated'):
        return True
    
    last_generated = datetime.fromisoformat(key_data['last_generated'])
    return datetime.now() - last_generated > timedelta(days=180)

# if key file exists, read key, else generate key and write to file
# WARNING: DO NOT CHANGE KEY ONCE GENERATED (this will break all existing events)
try:
    UNIQUE_KEY = os.environ.get('TVWB_UNIQUE_KEY', '').strip()
    
    if not UNIQUE_KEY:
        try:
            with open('.keyfile', 'r') as key_file:
                key_data = json.load(key_file)
                UNIQUE_KEY = key_data['key']
        except (json.JSONDecodeError, KeyError):
            # Handle old format or corrupted file
            with open('.keyfile', 'r') as key_file:
                UNIQUE_KEY = key_file.read().strip()
                key_data = {
                    'key': UNIQUE_KEY,
                    'last_generated': datetime.now().isoformat()
                }
    else:
        # "Replace the saved key with the one from the environment."
        key_data = {
            'key': UNIQUE_KEY,
            'last_generated': datetime.now().isoformat()
        }
        with open('.keyfile', 'w') as key_file:
            json.dump(key_data, key_file)

except FileNotFoundError:
    if can_generate_new_key({}):  # Empty dict for new file case
        UNIQUE_KEY = str(uuid.uuid4())
        key_data = {
            'key': UNIQUE_KEY,
            'last_generated': datetime.now().isoformat()
        }
        with open('.keyfile', 'w') as key_file:
            try:
                json.dump(key_data, key_file)
            except IOError as e:
                print(f"Error writing to .keyfile: {e}")
    else:
        raise RuntimeError("Cannot generate new key: 180 days have not passed since last key generation")