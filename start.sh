# Start the FastAPI application using uvicorn
uvicorn app:app --host 0.0.0.0 --port 8000 --log-level error &

# Run the update script
python3 update.py

# Start the bot
python3 bot.py