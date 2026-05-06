import pyodbc
try:
    drivers = [driver for driver in pyodbc.drivers()]
    print("Available ODBC Drivers:")
    for driver in drivers:
        print(f" - {driver}")
except Exception as e:
    print(f"Error: {e}")
