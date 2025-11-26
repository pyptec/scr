from datetime import datetime, timedelta
import time 
import os
TIMERTEMP = 10
def report_AC_status(trigger_minute=15):
    date_time=datetime.now()
    print("datetime :",date_time.minute)
    if(date_time.minute%trigger_minute == 0):
        print("timer a tiempo")

if __name__=='__main__':
    minute = datetime.now().minute
    
    while True:
        current_time = datetime.now()
        
        if(current_time.minute >= minute or current_time.second%30 ==0):  
            report_AC_status(TIMERTEMP)
            #send_boot_events()
            print ("minutos: ",str(minute))
            if(minute>=59):
                minute=0
            else:
                minute=minute+1 
        