SETUP INSTRUCTIONS

1. Insert your bot token into config.py (BOT_TOKEN).

2. Create a Google Sheet and paste the URL into config.py (SHEET_URL).

3. Generate your own Google Service Account:
   - Google Cloud Console
   - Enable Google Sheets API
   - Create service account
   - Create JSON key → rename to credentials.json
   - Upload credentials.json into the project folder
   - Share your Google Sheet with the service account email (Editor).

4. Insert your BTC wallet address into config.py.

5. Install requirements:
   pip install -r requirements.txt

6. Run the bot:
   python bot.py

For hosting:
- Set BOT_TOKEN, BTC_WALLET, SHEET_URL as environment variables.
- Upload credentials.json to your hosting.
- Run bot as a worker/worker dyno.

If you need setup help, message me.
