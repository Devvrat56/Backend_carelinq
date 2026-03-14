import os
import json
import asyncio
from datetime import datetime
from typing import Dict, Set, Optional, Any, List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
from dotenv import load_dotenv
import asyncpg
from motor.motor_asyncio import AsyncIOMotorClient

# Load environment variables
load_dotenv()

app = FastAPI(title="Carelinq Unified Backend (Python)")

# CORS Middleware - Fixed for broad compatibility
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,  # Set to False to allow '*' origins
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"status": "online", "message": "Carelinq Unified Backend (Python) is running"}

# --- GLOBAL STATE FOR WEB SOCKETS ---
# email -> websocket
user_sockets: Dict[str, WebSocket] = {}
# room_id -> set of websockets
rooms: Dict[str, Set[WebSocket]] = {}

# Keep track of alive status (FastAPI doesn't have a direct ws.isAlive property)
alive_sockets: Set[WebSocket] = set()

async def heartbeat_task():
    while True:
        await asyncio.sleep(30)
        # In a real production app, you might send a custom ping frame
        # For simplicity in this conversion, we check if connections are still responsive
        to_remove = []
        for ws in list(alive_sockets):
            try:
                # We can't easily wait for a pong without blocking
                # But we can try to send a ping frame
                # Most async websocket libs handle this at the protocol level
                pass 
            except:
                to_remove.append(ws)
        
        # Note: FastAPI/Uvicorn handles many heartbeat details automatically
        # if configured. This is a placeholder for the logic in server.js.

# --- DATABASE CONNECTIONS ---
pg_pool: Optional[asyncpg.Pool] = None
mongo_client: Optional[AsyncIOMotorClient] = None
mongodb = None

@app.on_event("startup")
async def startup():
    global pg_pool, mongo_client, mongodb
    
    # PostgreSQL Connection
    database_url = os.getenv("DATABASE_URL")
    
    # Configure SSL for Neon/Railway (rejectUnauthorized: false equivalent in Node)
    # asyncpg uses ssl context for more control
    ssl_context = False
    if database_url and "localhost" not in database_url:
        import ssl
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

    try:
        if database_url:
            pg_pool = await asyncpg.create_pool(dsn=database_url, ssl=ssl_context)
            print("Successfully connected to PostgreSQL")
        else:
            print("DATABASE_URL not found in environment variables")
    except Exception as e:
        print(f"PostgreSQL connection error: {e}")

    # MongoDB Connection
    mongo_uri = os.getenv("MONGO_DB_URL") or os.getenv("MONGO_URI") or "mongodb://localhost:27017/Specialist_portal"
    try:
        mongo_client = AsyncIOMotorClient(mongo_uri)
        mongodb = mongo_client.get_database()
        print(f"Successfully connected to MongoDB: {mongodb.name}")
    except Exception as e:
        print(f"MongoDB connection error: {e}")

    # Start Heartbeat Task
    asyncio.create_task(heartbeat_task())

@app.on_event("shutdown")
async def shutdown():
    if pg_pool:
        await pg_pool.close()
    if mongo_client:
        mongo_client.close()

# --- PYDANTIC MODELS (Schemas) ---
class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    role: str

class MedicalSaveRequest(BaseModel):
    doctor_email: str
    patient_email: str
    transcription: str
    session_history: List[Any] = Field(default_factory=list)
    consult_request_details: Dict[str, Any] = Field(default_factory=dict)

class ChatbotSaveRequest(BaseModel):
    user_email: str
    message: str
    response: str

class LogRequest(BaseModel):
    user_email: str
    action: str

# --- WEB SOCKET SIGNALING SERVER ---
@app.websocket("/ws")
@app.websocket("/")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    user_email: Optional[str] = None
    current_room: Optional[str] = None

    try:
        while True:
            # Receive message
            data_raw = await websocket.receive_text()
            data = json.loads(data_raw)
            msg_type = data.get("type")

            if msg_type == "identify":
                user_email = data.get("email", "").lower()
                user_sockets[user_email] = websocket
                print(f"User identified: {user_email}")

            elif msg_type == "join":
                current_room = str(data.get("room"))
                if current_room not in rooms:
                    rooms[current_room] = set()
                rooms[current_room].add(websocket)
                print(f"User joined room: {current_room}")

            elif msg_type == "signal":
                if current_room in rooms:
                    for client in rooms[current_room]:
                        if client != websocket:
                            await client.send_text(json.dumps(data))

            elif msg_type == "initiate-call":
                target_email = data.get("targetEmail", "").lower()
                target_socket = user_sockets.get(target_email)
                if target_socket:
                    await target_socket.send_text(json.dumps({
                        "type": "incoming-call",
                        "fromEmail": data.get("fromEmail"),
                        "fromName": data.get("fromName"),
                        "callType": data.get("callType"),
                        "roomID": data.get("roomID"),
                        "timestamp": int(datetime.now().timestamp() * 1000)
                    }))
                    print(f"Relaying call from {data.get('fromEmail')} to {target_email}")

    except WebSocketDisconnect:
        if user_email and user_sockets.get(user_email) == websocket:
            del user_sockets[user_email]
        if current_room and current_room in rooms:
            rooms[current_room].discard(websocket)
            if not rooms[current_room]:
                del rooms[current_room]
        print("User disconnected")
    except Exception as e:
        print(f"WebSocket error: {e}")
        if user_email and user_sockets.get(user_email) == websocket:
            del user_sockets[user_email]

# --- API ENDPOINTS ---

# Memory storage to keep track of failed login attempts
failed_login_attempts: Dict[str, int] = {}

@app.post("/api/login")
@app.post("/login")
async def login(req: LoginRequest):
    email_key = req.email.lower().strip()
    print(f"Login attempt for: {email_key}, role: {req.role}")
    
    # Check if user has already exceeded the maximum trials
    if failed_login_attempts.get(email_key, 0) >= 3:
        print(f"Login blocked for {email_key}: too many attempts")
        raise HTTPException(
            status_code=403, 
            detail="Maximum login attempts exceeded. Please use forgot password or recreate the password."
        )

    if pg_pool is None:
        print("DATABASE_URL is not set or PostgreSQL connection failed.")
        raise HTTPException(
            status_code=503,
            detail="Database connection is not available. Please check environment variables."
        )

    name = email_key.split('@')[0]
    async with pg_pool.acquire() as conn:
        # Case-insensitive search using email_key
        user = await conn.fetchrow("SELECT * FROM users WHERE LOWER(email) = $1", email_key)
        
        if not user:
            print(f"Registering new user: {email_key}")
            # Register new user (Mirroring server.js logic)
            user = await conn.fetchrow(
                "INSERT INTO users (email, password, role, name) VALUES ($1, $2, $3, $4) RETURNING *",
                email_key, req.password, req.role, name
            )
            # Initialize attempts for new user
            failed_login_attempts[email_key] = 0
        else:
            if user['password'] != req.password:
                # Increment failed attempts
                failed_login_attempts[email_key] = failed_login_attempts.get(email_key, 0) + 1
                attempts_left = 3 - failed_login_attempts[email_key]
                print(f"Invalid password for {email_key}. Attempts remaining: {attempts_left}")
                
                if attempts_left <= 0:
                    raise HTTPException(
                        status_code=403, 
                        detail="Maximum login attempts exceeded. Please use forgot password or recreate the password."
                    )
                else:
                    raise HTTPException(
                        status_code=401, 
                        detail=f"Incorrect passphrase. {attempts_left} attempts remaining."
                    )
            
            # Reset attempts on successful password match
            failed_login_attempts[email_key] = 0

            if user['role'] != req.role:
                raise HTTPException(
                    status_code=403, 
                    detail=f"Access Denied: This email is registered as a {user['role']}. Please select the correct portal."
                )

        return {
            "success": True,
            "user": {
                "id": str(user['id']),
                "email": user['email'],
                "name": user['name'],
                "role": user['role']
            }
        }

@app.get("/api/health-status/{email}")
async def get_health_status(email: str):
    async with pg_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM health_status WHERE user_email = $1", email)
        if not row:
            # Insert default if not found
            row = await conn.fetchrow(
                """INSERT INTO health_status 
                (user_email, heart_rate, oxygen_level, steps, recovery_progress, hydration_target, hydration_done) 
                VALUES ($1, 72, 98, 4500, 85, 2.5, 1.2) RETURNING *""",
                email
            )
        return dict(row)

@app.get("/api/records/{email}")
async def get_records(email: str):
    async with pg_pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM medical_records WHERE patient_email = $1 ORDER BY date DESC", email)
        return [dict(row) for row in rows]

# --- MongoDB Endpoints ---

@app.post("/api/medical/save")
async def save_medical(req: MedicalSaveRequest):
    record = req.dict()
    record["timestamp"] = datetime.utcnow()
    await mongodb.medical.insert_one(record)
    return {"success": True, "message": "Consultation history saved to MongoDB"}

@app.post("/api/chatbot/save")
async def save_chatbot(req: ChatbotSaveRequest):
    record = req.dict()
    record["timestamp"] = datetime.utcnow()
    await mongodb["Chatbot conversation"].insert_one(record)
    return {"success": True}

@app.post("/api/timestamp/log")
async def log_timestamp(req: LogRequest):
    record = req.dict()
    record["timestamp"] = datetime.utcnow()
    await mongodb.timestamp.insert_one(record)
    return {"success": True}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 5000))
    uvicorn.run(app, host="0.0.0.0", port=port)
