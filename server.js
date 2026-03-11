const express = require('express');
const { Pool } = require('pg');
const cors = require('cors');
const mongoose = require('mongoose');
const WebSocket = require('ws');
require('dotenv').config();

const app = express();
const server = require('http').createServer(app);
const PORT = process.env.PORT || 5000;

// --- WEB SOCKET SIGNALING SERVER (For Video Calls) ---
const wss = new WebSocket.Server({ server });

console.log(`Secured Backend & Signaling Server initializing on port ${PORT}`);

const userSockets = new Map(); // email -> socket
const rooms = new Map(); // roomID -> Set of client sockets

wss.on('connection', (ws) => {
    ws.isAlive = true;
    ws.on('pong', () => { ws.isAlive = true; });

    let currentRoom = null;
    let userEmail = null;

    ws.on('message', (message) => {
        const data = JSON.parse(message);

        switch (data.type) {
            case 'identify':
                userEmail = data.email.toLowerCase();
                userSockets.set(userEmail, ws);
                console.log(`User identified: ${userEmail}`);
                break;

            case 'join':
                currentRoom = data.room;
                if (!rooms.has(currentRoom)) {
                    rooms.set(currentRoom, new Set());
                }
                rooms.get(currentRoom).add(ws);
                console.log(`User joined room: ${currentRoom}`);
                break;

            case 'signal':
                // Relay WebRTC signals within a room
                if (rooms.has(currentRoom)) {
                    rooms.get(currentRoom).forEach(client => {
                        if (client !== ws && client.readyState === WebSocket.OPEN) {
                            client.send(JSON.stringify(data));
                        }
                    });
                }
                break;

            case 'initiate-call':
                // Targeted signaling for "ringing" a specific user
                const targetEmail = data.targetEmail.toLowerCase();
                const targetSocket = userSockets.get(targetEmail);
                if (targetSocket && targetSocket.readyState === WebSocket.OPEN) {
                    targetSocket.send(JSON.stringify({
                        type: 'incoming-call',
                        fromEmail: data.fromEmail,
                        fromName: data.fromName,
                        callType: data.callType,
                        roomID: data.roomID,
                        timestamp: Date.now()
                    }));
                    console.log(`Relaying call from ${data.fromEmail} to ${targetEmail}`);
                }
                break;
        }
    });

    ws.on('close', () => {
        if (userEmail) userSockets.delete(userEmail);
        if (currentRoom && rooms.has(currentRoom)) {
            rooms.get(currentRoom).delete(ws);
            if (rooms.get(currentRoom).size === 0) {
                rooms.delete(currentRoom);
            }
        }
        console.log('User disconnected');
    });
});

// Periodic heartbeat to keep connections alive and clean up stale ones
const interval = setInterval(() => {
    wss.clients.forEach((ws) => {
        if (ws.isAlive === false) return ws.terminate();
        ws.isAlive = false;
        ws.ping();
    });
}, 30000);

wss.on('close', () => {
    clearInterval(interval);
});

// Middleware
app.use(cors());
app.use(express.json());

// PostgreSQL Connection Pool using DATABASE_URL
const pool = new Pool({
    connectionString: process.env.DATABASE_URL,
    ssl: process.env.DATABASE_URL && process.env.DATABASE_URL.includes('localhost') ? false : { rejectUnauthorized: false }
});

// Test Database Connection
pool.connect((err, client, release) => {
    if (err) {
        return console.error('Error acquiring client', err.stack);
    }
    console.log('Successfully connected to PostgreSQL');
    release();
});

// MongoDB Connection - Updated to Specialist_portal
const MONGO_URI = process.env.MONGO_URI || 'mongodb://localhost:27017/Specialist_portal';
mongoose.connect(MONGO_URI)
    .then(() => console.log('Successfully connected to Specialist_portal MongoDB'))
    .catch(err => console.error('MongoDB connection error:', err));

// --- MongoDB Schemas & Models ---

// 1. Medical Session History (Transcription, Session History, Consult Requests)
const MedicalSchema = new mongoose.Schema({
    doctor_email: String,
    patient_email: String,
    transcription: String,
    session_history: Array, // Full chat log during session
    consult_request_details: Object, // Time, priority, etc.
    timestamp: { type: Date, default: Date.now }
}, { collection: 'medical' });

const Medical = mongoose.model('Medical', MedicalSchema);

// 2. Chatbot Interaction
const ChatbotSchema = new mongoose.Schema({
    user_email: String,
    message: String,
    response: String,
    timestamp: { type: Date, default: Date.now }
}, { collection: 'Chatbot conversation' });

const Chatbot = mongoose.model('Chatbot', ChatbotSchema);

// 3. User Activity Logs
const TimestampSchema = new mongoose.Schema({
    user_email: String,
    action: String,
    timestamp: { type: Date, default: Date.now }
}, { collection: 'timestamp' });

const Log = mongoose.model('Log', TimestampSchema);

// --- API ENDPOINTS ---

// 1. Authentication / Login
app.post('/api/login', async (req, res) => {
    const { email, password, role } = req.body;
    const name = email.split('@')[0];

    try {
        const checkQuery = 'SELECT * FROM users WHERE email = $1';
        const checkResult = await pool.query(checkQuery, [email]);
        let user;

        if (checkResult.rows.length === 0) {
            const insertQuery = 'INSERT INTO users (email, password, role, name) VALUES ($1, $2, $3, $4) RETURNING *';
            const insertResult = await pool.query(insertQuery, [email, password, role, name]);
            user = insertResult.rows[0];
        } else {
            user = checkResult.rows[0];
            if (user.password !== password) {
                return res.status(401).json({ success: false, message: 'Incorrect passphrase.' });
            }
            if (user.role !== role) {
                return res.status(403).json({
                    success: false,
                    message: `Access Denied: This email is registered as a ${user.role}. Please select the correct portal.`
                });
            }
        }

        res.json({
            success: true,
            user: { id: user.id, email: user.email, name: user.name, role: user.role }
        });
    } catch (err) {
        console.error(err);
        res.status(500).json({ success: false });
    }
});

// 2. Health Status (Postgres)
app.get('/api/health-status/:email', async (req, res) => {
    const { email } = req.params;
    try {
        const query = 'SELECT * FROM health_status WHERE user_email = $1';
        let result = await pool.query(query, [email]);
        if (result.rows.length === 0) {
            const defaultQuery = `INSERT INTO health_status 
            (user_email, heart_rate, oxygen_level, steps, recovery_progress, hydration_target, hydration_done) 
            VALUES ($1, 72, 98, 4500, 85, 2.5, 1.2) RETURNING *`;
            result = await pool.query(defaultQuery, [email]);
        }
        res.json(result.rows[0]);
    } catch (err) {
        res.status(500).json({ success: false });
    }
});

// 3. Medical Records (Postgres)
app.get('/api/records/:email', async (req, res) => {
    try {
        const query = 'SELECT * FROM medical_records WHERE patient_email = $1 ORDER BY date DESC';
        const result = await pool.query(query, [req.params.email]);
        res.json(result.rows);
    } catch (err) {
        res.status(500).json({ success: false });
    }
});

// --- MongoDB Endpoints ---

// Save Medical History (Telehealth Session)
app.post('/api/medical/save', async (req, res) => {
    const { doctor_email, patient_email, transcription, session_history, consult_request_details } = req.body;
    try {
        const newRecord = new Medical({
            doctor_email,
            patient_email,
            transcription,
            session_history,
            consult_request_details
        });
        await newRecord.save();
        res.json({ success: true, message: 'Consultation history saved to MongoDB' });
    } catch (err) {
        console.error(err);
        res.status(500).json({ success: false, message: 'Failed to save session data' });
    }
});

// Save Chatbot Chat
app.post('/api/chatbot/save', async (req, res) => {
    const { user_email, message, response } = req.body;
    try {
        const chat = new Chatbot({ user_email, message, response });
        await chat.save();
        res.json({ success: true });
    } catch (err) {
        res.status(500).json({ success: false });
    }
});

// Activity Logging
app.post('/api/timestamp/log', async (req, res) => {
    const { user_email, action } = req.body;
    try {
        const log = new Log({ user_email, action });
        await log.save();
        res.json({ success: true });
    } catch (err) {
        res.status(500).json({ success: false });
    }
});

server.listen(PORT, () => {
    console.log(`Unified Backend & Signaling Server running on port ${PORT}`);
});
