import mysql.connector

def get_connection():
    connection = mysql.connector.connect(
        host='localhost',
        user='root',
        password='',
        database='db_Taxi'
    )
    return connection
