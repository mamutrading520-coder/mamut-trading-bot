import sqlite3
import time
import os

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

while True:
    clear_screen()
    
    conn = sqlite3.connect('mamut.db')
    c = conn.cursor()
    
    print("=" * 60)
    print("MAMUT LIVE MONITOR")
    print("=" * 60)
    
    # Estadísticas
    c.execute('SELECT COUNT(*) FROM tokens;')
    tokens = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM signals;')
    signals = c.fetchone()[0]
    
    print(f"\nTokens Descubiertos:  {tokens}")
    print(f"Señales Generadas:    {signals}")
    if tokens > 0:
        print(f"Signal Rate:          {(signals/tokens)*100:.1f}%")
    
    print(f"\nÚltimos 5 Tokens:")
    print("-" * 60)
    c.execute('SELECT symbol, risk_level FROM tokens ORDER BY created_at DESC LIMIT 5;')
    for row in c.fetchall():
        print(f"  {row[0]:<15} {row[1]}")
    
    print(f"\nSignales por Tipo:")
    print("-" * 60)
    c.execute('SELECT signal_type, COUNT(*) FROM signals GROUP BY signal_type;')
    for row in c.fetchall():
        print(f"  {row[0]:<15} {row[1]}")
    
    conn.close()
    
    print("\n" + "=" * 60)
    print("Actualizando en 10 segundos... (Ctrl+C para salir)")
    print("=" * 60)
    
    time.sleep(10)