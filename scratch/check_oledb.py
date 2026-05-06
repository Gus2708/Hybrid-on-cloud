import win32com.client

try:
    obj = win32com.client.Dispatch("SQLDMO.Application")
    # Actually just listing providers in registry or trying ADODB
    conn = win32com.client.Dispatch("ADODB.Connection")
    print("ADODB object created successfully")
except Exception as e:
    print(e)
