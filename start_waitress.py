#start_waitress.py
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler
from scraper import scrape_and_update, daily_statistics_update, TIMEZONE
import waitress

app = Flask(__name__)
scheduler = BackgroundScheduler(timezone=TIMEZONE)

def scrape_and_update_task():
    scrape_and_update()

def start_scheduler():
    if not scheduler.running:
        # Every 30 seconds from 6:00 AM to 9:59 PM
        scheduler.add_job(scrape_and_update_task, 'cron',
                          hour='6-21', minute='*', second='0,30',
                          misfire_grace_time=60)
        # Every 60 seconds from 10:00 PM to 5:59 AM
        scheduler.add_job(scrape_and_update_task, 'cron',
                          hour='22-23,0-5', minute='*', second='0',
                          misfire_grace_time=120)
        # Daily statistics update at 3 AM
        scheduler.add_job(daily_statistics_update, 'cron', hour=3, minute=0)
        
        scheduler.start()
        # Run immediately upon starting
        scrape_and_update_task()

if __name__ == "__main__":
    start_scheduler()
    waitress.serve(app, host="0.0.0.0", port=5000)