-- Create the Database (Run this manually first if needed)
-- CREATE DATABASE ai_scribe_db;

-- 1. Create Users Table
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    password VARCHAR(255) NOT NULL,
    role VARCHAR(50) NOT NULL, -- 'doctor' or 'patient'
    name VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. Create Medical Records Table
CREATE TABLE IF NOT EXISTS medical_records (
    id SERIAL PRIMARY KEY,
    patient_email VARCHAR(255) REFERENCES users(email),
    patient_name VARCHAR(255),
    date DATE NOT NULL,
    time VARCHAR(20),
    duration VARCHAR(50),
    summary TEXT,
    type VARCHAR(50), -- 'discharge', 'video', 'chatbot'
    status VARCHAR(50), -- 'finalized', 'signed', 'flagged'
    priority VARCHAR(10), -- 'high', 'medium', 'low'
    doctor VARCHAR(255),
    clinical_significance TEXT,
    tags TEXT[] -- PostgreSQL Array for tags
);

-- 3. Insert Sample Data for Patients
INSERT INTO users (email, password, role, name) 
VALUES ('patient@gmail.com', 'test@123', 'patient', 'John Doe')
ON CONFLICT (email) DO NOTHING;

INSERT INTO users (email, password, role, name) 
VALUES ('devvratshukla24@gmail.com', 'test@123', 'patient', 'Devvrat Shukla')
ON CONFLICT (email) DO NOTHING;

-- 4. Insert Sample Data for Doctors
INSERT INTO users (email, password, role, name) 
VALUES ('doctor@gmail.com', 'test@123', 'doctor', 'Dr. Sarah Connor')
ON CONFLICT (email) DO NOTHING;

-- 5. Insert Sample Medical Records for John Doe
INSERT INTO medical_records (patient_email, patient_name, date, summary, type, status, doctor, clinical_significance, tags)
VALUES (
    'patient@gmail.com', 
    'John Doe', 
    '2026-03-01', 
    'DISCHARGE SUMMARY: Patient successfully completed cycle 4 of targeted chemotherapy.', 
    'discharge', 
    'finalized', 
    'Dr. Sarah Connor', 
    'Recovery milestones met.', 
    ARRAY['Cycle 4', 'Oncology']
);

-- 6. Insert Sample Medical Records for Devvrat Shukla
INSERT INTO medical_records (patient_email, patient_name, date, summary, type, status, doctor, clinical_significance, tags)
VALUES (
    'devvratshukla24@gmail.com', 
    'Devvrat Shukla', 
    '2026-03-10', 
    'INITIAL CONSULT: Discussed general wellness and oncology markers. Patient is responding well to treatment.', 
    'video', 
    'signed', 
    'Dr. Sarah Connor', 
    'Stable condition.', 
    ARRAY['Initial Consult', 'Wellness']
);
