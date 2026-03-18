import sqlite3

conn = sqlite3.connect('mamut.db')
c = conn.cursor()

c.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = c.fetchall()

print('TABLAS EN BD:')
for table in tables:
    print(f'  - {table[0]}')
    c.execute(f'SELECT COUNT(*) FROM {table[0]}')
    count = c.fetchone()[0]
    print(f'    Registros: {count}')

conn.close()