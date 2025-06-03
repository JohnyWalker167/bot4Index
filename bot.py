import uuid
import asyncio
import uvloop
import sys
from time import time as tm
from pyrogram import Client, enums, filters
from config import *
from pyrogram.errors import FloodWait, UserIsBlocked, InputUserDeactivated
from pyrogram.types import User
from utility import *
from shorterner import *
from motor.motor_asyncio import AsyncIOMotorClient 
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from asyncio import Queue

uvloop.install()



# Define an async queue to handle messages sequentially
message_queue = Queue()

user_data = {}
user_sessions = {}
LIMIT_PER_PAGE = 5  

# Initialize MongoDB client

MONGO_COLLECTION = "users"
TMDB_COLLECTION = "tmdb"
mongo_client = AsyncIOMotorClient(MONGO_URI)  # Use AsyncIOMotorClient
db = mongo_client[MONGO_DB_NAME]
collection = db[COLLECTION_NAME]
mongo_collection = db[MONGO_COLLECTION]
tmdb_collection = db[TMDB_COLLECTION]

# Function to create a text index on file_name field
async def create_text_index():
    indexes = await collection.index_information()
    if "file_name_text" not in indexes:
        result = await collection.create_index([("file_name", "text")])
        logging.info(f"Index created: {result}")
        
# PROGRAM BOT INITIALIZATION 

bot = Client(
    "bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workers=1000,
    parse_mode=enums.ParseMode.HTML
).start()

# *---------------------------------------------- HANDLER'S ----------------------------------------------------*

@bot.on_message(filters.private & filters.command("start"))
async def start_command(client, message):
    try:
        user_id = message.from_user.id
        user_link = await get_user_link(message.from_user)

        if len(message.command) > 1:
            command_arg = message.command[1]
            
            # Handle token flow
            if command_arg == "token":
                msg = await bot.get_messages(LOG_CHANNEL_ID, 1415)
                sent_msg = await msg.copy(chat_id=message.chat.id)
                await message.delete()
                await asyncio.sleep(300)
                await sent_msg.delete()
                return

            # Handle token verification
            if command_arg.startswith("token_"):
                input_token = command_arg[6:]
                token_msg = await verify_token(user_id, input_token)
                reply = await message.reply_text(token_msg)
                await bot.send_message(LOG_CHANNEL_ID, f"User🕵️‍♂️{user_link} with 🆔 {user_id} @{bot_username} {token_msg}", parse_mode=enums.ParseMode.HTML)
                await auto_delete_message(message, reply)
                return

            # Handle file flow
            if not command_arg.isdigit():
                reply = await message.reply_text("Invalid File ID.")
                await auto_delete_message(message, reply)
                return
            
            file_id = int(command_arg)

            try:
                file_message = await bot.get_messages(DB_CHANNEL_ID, file_id)
            except Exception:
                await auto_delete_message(message, await message.reply_text("File not found or inaccessible."))
                return
            
            media = file_message.video or file_message.audio or file_message.document
            if media:
                copy_message = await file_message.copy(chat_id=message.chat.id)
                if user_id not in user_data:
                    user_data[user_id] = {"file_count": 1}
                else:
                    user_data[user_id]['file_count'] = user_data[user_id].get('file_count', 0) + 1
                await auto_delete_message(message, copy_message)
                await asyncio.sleep(3)
            else:
                await auto_delete_message(message, await message.reply_text("File not found or inaccessible."))
            return

        # Default flow (no arguments)
        await mongo_collection.update_one({'user_id': user_id}, {'$set': {'user_id': user_id}}, upsert=True)
        await greet_user(message)
        
    except ValueError:
        reply = await message.reply_text("Invalid File ID.")
        await auto_delete_message(message, reply)
    except FloodWait as f:
        await asyncio.sleep(f.value)
        await start_command(client, message)  # Retry after the flood wait
    except Exception as e:
        logger.error(f"Error in start command: {e}")
        await auto_delete_message(message, await message.reply_text(f"An error occurred: {e}"))

@bot.on_message(filters.private & (filters.document | filters.video | filters.audio) & filters.user(OWNER_ID))
async def handle_dm(client, message):
    media = message.video or message.document or message.audio
    caption = await remove_unwanted(message.caption if message.caption else media.file_name)
    cpy_msg = await message.copy(DB_CHANNEL_ID, caption=f"<code>{caption}</code>", parse_mode=enums.ParseMode.HTML)
    await message_queue.put(cpy_msg)
    await message.delete()

@bot.on_message(filters.chat(DB_CHANNEL_ID) & (filters.document | filters.video | filters.audio))
async def handle_channel(client, message):
    # Add the message to the queue for sequential processing
    await message_queue.put(message)


@bot.on_message(filters.private & filters.command("index") & filters.user(OWNER_ID))
async def handle_index(client, message):
    try:
        user_id = message.from_user.id
        user_sessions[user_id] = True

        # Helper function to get user input
        async def get_user_input(prompt):
            bot_message = await message.reply_text(prompt)
            user_message = await bot.listen(chat_id=message.chat.id, filters=filters.user(OWNER_ID))
            if user_sessions.get(user_id) == False:
                raise Exception("Process cancelled")
            asyncio.create_task(auto_delete_message(bot_message, user_message))
            return await extract_tg_link(user_message.text.strip())

        async def auto_delete_message(bot_message, user_message):
            await asyncio.sleep(10)
            await bot_message.delete()
            await user_message.delete()

        # Get the start and end message IDs
        start_msg_id = int(await get_user_input("Send first post link"))
        end_msg_id = int(await get_user_input("Send end post link"))

        batch_size = 199

        for start in range(int(start_msg_id), int(end_msg_id) + 1, batch_size):            
            if user_sessions.get(user_id) == False:
                raise Exception("Process cancelled")
            end = min(start + batch_size - 1, int(end_msg_id))
            try:
                file_messages = await bot.get_messages(DB_CHANNEL_ID, list(range(start, end + 1)))
            except FloodWait as e:
                await asyncio.sleep(e.value)
                file_messages = await bot.get_messages(DB_CHANNEL_ID, list(range(start, end + 1)))
            await asyncio.sleep(3)  # Add a small delay between batches

            for file_message in file_messages:
                await message_queue.put(file_message)

    except Exception as e:
        await message.reply_text(f"An error occurred: {e}")
    finally:
        user_sessions.pop(user_id, None)

@bot.on_message(filters.private & filters.command("cancel") & filters.user(OWNER_ID))
async def cancel_process(client, message):
    user_id = message.from_user.id
    user_sessions[user_id] = False
    await message.reply_text("Process has been cancelled.")


# Get Total User Command

@bot.on_message(filters.command("users") & filters.user(OWNER_ID))
async def total_users_command(client, message):
    user_id = message.from_user.id

    total_users = await mongo_collection.count_documents({})
    total_files = await collection.count_documents({})
    response_text = f"Total users: {total_users}\nTotal files: {total_files}"
    reply = await bot.send_message(user_id, response_text)
    await auto_delete_message(message, reply)

@bot.on_message(filters.private & filters.command("del") & filters.user(OWNER_ID))
async def delete_command(client, message):
    try:               
        bot_message = await message.reply_text("Send file link")
        user_message = await bot.listen(chat_id=message.chat.id, filters=filters.user(OWNER_ID))
        file_link = user_message.text.strip()
        file_id = await extract_tg_link(file_link)
        asyncio.create_task(auto_delete_message(bot_message, user_message))
        result = await collection.delete_one({"file_id": file_id})     
        if result.deleted_count > 0:
            bot_message = await message.reply_text(f"Database record deleted {file_id}.")
            await auto_delete_message(message, bot_message)
        else:
            bot_message = await message.reply_text(f"No file found with ID {file_id} in the database.")
            await auto_delete_message(message, bot_message)
    except Exception as e:
        bot_message = await message.reply_text(f"Error: {e}")
        await auto_delete_message(message, bot_message)

        
# Get Log Command
@bot.on_message(filters.command("log") & filters.user(OWNER_ID))
async def log_command(client, message):
    user_id = message.from_user.id

    # Send the log file
    try:
        reply = await bot.send_document(user_id, document=LOG_FILE_NAME, caption="Bot Log File")
        await auto_delete_message(message, reply)
    except Exception as e:
        await bot.send_message(user_id, f"Failed to send log file. Error: {str(e)}")

@bot.on_message(filters.private & filters.command('broadcast') & filters.user(OWNER_ID))
async def handle_broadcast(client, message):
    if message.reply_to_message:
        query = await full_userbase()
        broadcast_msg = message.reply_to_message
        total = 0
        successful = 0
        blocked = 0
        deleted = 0
        unsuccessful = 0
        
        pls_wait = await message.reply("<i>Broadcasting Message.. This will Take Some Time</i>")
        for chat_id in query:
            try:
                await asyncio.sleep(3)
                await broadcast_msg.copy(chat_id)
                successful += 1
            except FloodWait as e:
                await asyncio.sleep(e.x)
                await broadcast_msg.copy(chat_id)
                successful += 1
            except UserIsBlocked:
                await del_user(chat_id)
                blocked += 1
            except InputUserDeactivated:
                await del_user(chat_id)
                deleted += 1
            except:
                unsuccessful += 1
                pass
            total += 1
        
        status = f"""<b><u>Broadcast Completed</u>

Total Users: <code>{total}</code>
Successful: <code>{successful}</code>
Blocked Users: <code>{blocked}</code>
Deleted Accounts: <code>{deleted}</code>
Unsuccessful: <code>{unsuccessful}</code></b>"""
        
        return await pls_wait.edit(status)

    else:
        msg = await message.reply("<code>Use this command as a replay to any telegram message with out any spaces.</code>")
        await asyncio.sleep(8)
        await msg.delete()

@bot.on_message(filters.command('restart') & filters.private & filters.user(OWNER_ID))
async def restart(client, message):
    os.system("python3 update.py")  
    os.execl(sys.executable, sys.executable, "bot.py")

# *-------------------------------------------------------- HELPER'S ---------------------------------------------------------*

async def greet_user(message):
    # Get the new user's first name
    user_link = await get_user_link(message.from_user)

    # Create the greeting message
    greeting_text = (
        f"Hello {user_link}, 👋\n\n"
        "Welcome to FileShare Bot! 🌟\n\n"
        "Here, you can easily access files.\n"
        "We hope you find this bot useful! If you have any questions, feel free to reach out to us. Happy sharing! 😊"
    )

    # Create the buttons
    buttons = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Website", url=f"{WEBSITE}")],
        ]
    )
    
    rply = await message.reply_text(
        text=greeting_text,
        reply_markup=buttons
        )
    
    await auto_delete_message(message, rply)

async def process_message(client, message):
    media = message.document or message.video or message.audio

    if media:
        caption = await remove_unwanted(message.caption if message.caption else media.file_name)
        file_name = await remove_extension(caption)
        file_id = message.id
        file_size = humanbytes(media.file_size)
        title = media.title if message.audio else None
        artist = media.performer if message.audio else None

        # Check if the file_name already exists in the database
        existing_document = await collection.find_one({"file_name": file_name})

        if existing_document:
            await bot.send_message(OWNER_ID, text=f"Duplicate file detected. The file '<code>{file_name}</code>' already exists in the database.")
            return

        if message.audio:
            tg_document = {
                "file_id": file_id,
                "file_name": file_name,
                "title": title,
                "artist": artist,
                "file_size": file_size
            }
        else:
            tg_document = {
                "file_id": file_id,
                "file_name": file_name,
                "file_size": file_size
            }

        try:
            await collection.insert_one(tg_document)
        except Exception as e:
            await message.reply_text(f"Unable to insert data: {e}")
               
# Function to process the queue in sequence
async def process_queue():
    while True:
        message = await message_queue.get()  # Get the next message from the queue
        if message is None:  # Exit condition
            break
        await process_message(bot, message)  # Process the message
        message_queue.task_done()
                               
async def get_user_link(user: User) -> str:
    try:
        user_id = user.id if hasattr(user, 'id') else None
        first_name = user.first_name if hasattr(user, 'first_name') else "Unknown"
    except Exception as e:
        logger.info(f"{e}")
        user_id = None
        first_name = "Unknown"
    
    if user_id:
        return f'<a href=tg://user?id={user_id}>{first_name}</a>'
    else:
        return first_name

async def verify_token(user_id, input_token):
    current_time = tm()

    # Check if the user_id exists in user_data
    if user_id not in user_data:
        return 'Token Mismatched ❌' 
    
    stored_token = user_data[user_id]['token']
    if input_token == stored_token:
        token = str(uuid.uuid4())
        user_data[user_id] = {"token": token, "time": current_time, "status": "verified", "file_count": 0}
        return f'Token Verified ✅ (Validity: {get_readable_time(TOKEN_TIMEOUT)})'
    else:
        return f'Token Mismatched ❌'
    
async def check_access(message, user_id):
    if user_id in user_data:
        time = user_data[user_id]['time']
        status = user_data[user_id]['status']
        file_count = user_data[user_id].get('file_count', 0)
        expiry = time + TOKEN_TIMEOUT
        current_time = tm()
        if current_time < expiry and status == "verified":
            if file_count < 10:
                return True
            else:
                reply = await message.reply_text(f"You have reached the limit. Please wait until the token expires")
                await auto_delete_message(message, reply)
                return False
        else:
            button = await update_token(user_id)
            send_message = await message.reply_photo(photo=f"{POSTER_URL}", 
                                                     caption=f"👋 Welcome! Please get your token verified using the link below to access your files instantly. 🚀", 
                                                     reply_markup=button)
            await auto_delete_message(message, send_message)
            return False
    else:
        button = await genrate_token(user_id)
        send_message = await message.reply_photo(photo=f"{POSTER_URL}", 
                                                    caption=f"👋 Welcome! Please get your token verified using the link below to access your files instantly. 🚀", 
                                                    reply_markup=button)        
        await auto_delete_message(message, send_message)
        return False

async def update_token(user_id):
    try:
        time = user_data[user_id]['time']
        expiry = time + TOKEN_TIMEOUT
        if time < expiry:
            token = user_data[user_id]['token']
        else:
            token = str(uuid.uuid4())
        current_time = tm()
        user_data[user_id] = {"token": token, "time": current_time, "status": "unverified", "file_count": 0}
        urlshortx = await shorten_url(f'https://telegram.me/{bot_username}?start=token_{token}')
        token_url = f'https://telegram.dog/{bot_username}?start=token'
        button1 = InlineKeyboardButton("Get verified ✅", url=urlshortx)
        button2 = InlineKeyboardButton("How to get verified ✅", url=token_url)
        button = InlineKeyboardMarkup([[button1], [button2]]) 
        return button
    except Exception as e:
        logger.error(f"error in update_token: {e}")

async def genrate_token(user_id):
    try:
        token = str(uuid.uuid4())
        current_time = tm()
        user_data[user_id] = {"token": token, "time": current_time, "status": "unverified", "file_count": 0}
        urlshortx = await shorten_url(f'https://telegram.me/{bot_username}?start=token_{token}')
        token_url = f'https://telegram.dog/{bot_username}?start=token'
        button1 = InlineKeyboardButton("Get verified ✅", url=urlshortx)
        button2 = InlineKeyboardButton("How to get verified ✅", url=token_url)
        button = InlineKeyboardMarkup([[button1], [button2]]) 
        return button
    except Exception as e:
        logger.error(f"error in genrate_token: {e}")

async def full_userbase():
    try:
        cursor = mongo_collection.find({}, {"user_id": 1, "_id": 0})
        user_ids = []
        async for document in cursor:
            user_ids.append(document["user_id"])
        return user_ids
    except Exception as e:
        logger.error(f"Error fetching user base: {e}")
        return []
    
async def del_user(user_id):
    try:
        result = await mongo_collection.delete_one({"user_id": user_id})
        if result.deleted_count > 0:
            logger.info(f"Successfully deleted user with ID {user_id}")
        else:
            logger.warning(f"No user found with ID {user_id}")
    except Exception as e:
        logger.error(f"Error deleting user with ID {user_id}: {e}")

async def main():
    await create_text_index()
    await asyncio.create_task(process_queue())

if __name__ == "__main__":
    try:
        bot.loop.run_until_complete(main())
        bot.loop.run_forever()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received. Shutting down gracefully...")
    finally:
        logger.info("Bot has stopped.")
