import firebase_admin
from firebase_admin import credentials, firestore
import config

cred = credentials.Certificate(config.SERVICE_ACCOUNT_KEY)
firebase_admin.initialize_app(cred)
db = firestore.client()

db.collection('config').document('telegram').set({
    'botTokens': config.TELEGRAM_BOT_TOKENS,
    'channelId': config.TELEGRAM_CHANNEL_ID
}, merge=True)
print("✅ Telegram config initialized in Firestore")

# Also delete the broken test so we can re-ingest it properly
db.collection('tests').document('sat_2023_dec_int_a').delete()
print("✅ Deleted broken test to allow clean rerun")
