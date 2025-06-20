from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from db import allowed_channels_col, files_col
from config import BOT_USERNAME, MY_DOMAIN
from utility import generate_telegram_link, channel_files_cache
from datetime import datetime

api = FastAPI()
api.add_middleware(
    CORSMiddleware,
    allow_origins=[f"{MY_DOMAIN}"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@api.get("/")
async def root():
    """Greet users on root route."""
    return JSONResponse({"message": "👋 Hello! Welcome to the Sharing Bot"})

@api.get("/api/channels")
async def api_channels():
    """List all channels (JSON)."""
    channels = list(allowed_channels_col.find({}, {"_id": 0, "channel_id": 1, "channel_name": 1}))
    return JSONResponse({"channels": channels})

@api.get("/api/channel/{channel_id}/files")
async def api_channel_files(
    channel_id: int,
    q: str = "",
    offset: int = 0,
    limit: int = 10
):
    """List files for a channel (JSON)."""
    bot_username = BOT_USERNAME
    query = {"channel_id": channel_id}
    if q:
        regex = ".*".join(map(lambda s: s, q.strip().split()))
        query["file_name"] = {"$regex": regex, "$options": "i"}

    cache_key = f"{channel_id}:{q}:{offset}:{limit}"
    if cache_key not in channel_files_cache:
        files = list(files_col.find(query, {"_id": 0}).sort("message_id", -1))
        for file in files:
            file["telegram_link"] = generate_telegram_link(bot_username, file["channel_id"], file["message_id"])
            if isinstance(file.get("date"), str):
                try:
                    file["date"] = datetime.fromisoformat(file["date"])
                except Exception:
                    file["date"] = None
        channel_files_cache[cache_key] = files
    else:
        files = channel_files_cache[cache_key]

    paginated_files = files[offset:offset+limit]
    has_more = offset + limit < len(files)

    def serialize_file(file):
        return {
            "file_name": file.get("file_name"),
            "file_size": file.get("file_size"),
            "file_format": file.get("file_format"),
            "telegram_link": file.get("telegram_link")
        }

    return JSONResponse({
        "files": [serialize_file(f) for f in paginated_files],
        "has_more": has_more
    })
