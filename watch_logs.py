import time
import os

last_size = 0

while True:
    try:
        if os.path.exists('logs/mamut.log'):
            with open('logs/mamut.log', 'r') as f:
                f.seek(last_size)
                lines = f.readlines()
                last_size = f.tell()
                
                for line in lines:
                    if 'EARLY SIGNAL' in line or 'ALERT SENT' in line or 'POOL FOUND' in line:
                        print(line.strip())
        
        time.sleep(1)
    except KeyboardInterrupt:
        break
    except Exception as e:
        print(f"Error: {e}")
        time.sleep(1)