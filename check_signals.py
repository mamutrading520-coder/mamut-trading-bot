import sqlite3
conn = sqlite3.connect('mamut.db')
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

cursor.execute('SELECT * FROM signals LIMIT 2')
rows = cursor.fetchall()

print('SIGNALS EN BD:')
for row in rows:
    print(f'\n  signal_id: {row["signal_id"]}')
    print(f'  mint: {row["mint"][:16]}...')
    print(f'  symbol: {row["symbol"]}')
    print(f'  signal_type: {row["signal_type"]}')
    print(f'  score: {row["score"]}')
    print(f'  confidence: {row["confidence"]}')

conn.close()
