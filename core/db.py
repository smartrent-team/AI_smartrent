from core.config import DATABASE_URL
import psycopg2

def get_connection():
    return psycopg2.connect(DATABASE_URL)