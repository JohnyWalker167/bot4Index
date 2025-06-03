import re
import logging
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from motor.motor_asyncio import AsyncIOMotorClient
from fastapi.middleware.cors import CORSMiddleware
from fastapi_cache import FastAPICache
from fastapi_cache.backends.inmemory import InMemoryBackend
from fastapi_cache.decorator import cache
from contextlib import asynccontextmanager
from config import *

app = FastAPI()

# CORS settings
app.add_middleware(
    CORSMiddleware,
    allow_origins=[f"{MY_DOMAIN}"],  # Change to your domain for security
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Set up logging
logging.basicConfig(level=logging.ERROR)

# Initialize MongoDB client
mongo_client = AsyncIOMotorClient(MONGO_URI)
db = mongo_client[MONGO_DB_NAME]
collection = db[COLLECTION_NAME]

# Pagination settings
ITEMS_PER_PAGE = 10  # Number of items to display per page

@app.get('/')
async def home():
    # Create a greeting message with emojis
    greeting_message = "Welcome to the TG⚡FLIX APP! 🎉\n"
    return greeting_message


# Function to create a text index on file_name field
async def create_text_index():
    indexes = await collection.index_information()
    if "file_name_text" not in indexes:
        result = await collection.create_index([("file_name", "text")])
        logging.info(f"Index created: {result}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup event
    await create_text_index()
    FastAPICache.init(InMemoryBackend())
    yield

    # Shutdown event
    mongo_client.close()

app.router.lifespan_context = lifespan


@app.get('/api/files')
@cache(expire=300, key_builder=lambda func, *args, **kwargs: str(kwargs['request'].url))  # Cache for 5 minutes
async def api_media(request: Request):
    query = request.query_params.get('query', '').strip()  # Get the search query
    page = int(request.query_params.get('page', 1))  # Get the current page, default to 1

    if page < 1:
        raise HTTPException(status_code=400, detail="Page number must be at least 1")

    skip = (page - 1) * ITEMS_PER_PAGE  # Pagination calculation

    if query:
        # Normalize the search query by replacing spaces with dots, hyphens, underscores
        normalized_query = re.sub(r'[ \-_.]', '.', query)
        regex_query = f'({query}|{normalized_query})'
        search_filter = {"file_name": {"$regex": regex_query, "$options": "i"}}
    else:
        search_filter = {}

    sort_criteria = [("file_id", -1)]

    # Count total items for pagination
    total_items = await collection.count_documents(search_filter)
    total_pages = (total_items + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    
    # Fetch documents with the correct projection & sorting
    media_files = await collection.find(search_filter).sort(sort_criteria).skip(skip).limit(ITEMS_PER_PAGE).to_list(length=ITEMS_PER_PAGE)

    # Convert ObjectId and format timestamps
    for file in media_files:
        file["_id"] = str(file["_id"])  # Convert ObjectId to string
        file["telegram_link"] = f"https://telegram.dog/{bot_username}?start={file['file_id']}"

    response = {
        "media_files": media_files,
        "query": query,
        "current_page": page,
        "total_pages": total_pages,
        "items_per_page": ITEMS_PER_PAGE
    }

    return JSONResponse(response)
