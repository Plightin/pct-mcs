# pct.py - Presidential Campaign Team System (PCT-MCS) Main Application

from flask import Flask, jsonify, request

app = Flask(__name__)

# --- TEMPORARY IN-MEMORY DATA STORE (Will be replaced by PostgreSQL) ---
# Simulates a single active member record
MEMBER_DATABASE = {
    "SPG-2025-00123": {
        "Name": "Aisha Kanyanta",
        "NRC": "101234/18/1",
        "Province": "Copperbelt",
        "Status": "Active",
        "Membership_End_Date": "2026-12-31"
    }
}

# --- 1. CORE API ENDPOINT: Status Check ---
@app.route('/')
def home():
    """Confirms the web service is running."""
    return jsonify({
        "status": "online",
        "system": "PCT-MCS",
        "message": "Campaign Management API is active and ready for deployment."
    })

# --- 2. FEATURE SEC-401: Verification Portal Endpoint (Placeholder) ---
@app.route('/verify/<string:user_id>', methods=['GET'])
def verify_member(user_id):
    """Simulates the real-time card verification process."""
    member = MEMBER_DATABASE.get(user_id)
    
    if member:
        # SEC-401 Logic: Return only essential verification data
        verification_data = {
            "User_ID": user_id,
            "Name": member['Name'],
            "Status": member['Status'],
            "Valid_Until": member['Membership_End_Date'],
            "Verification_Result": "AUTHENTICATED" if member['Status'] == 'Active' else "EXPIRED/INACTIVE"
        }
        return jsonify(verification_data)
    else:
        return jsonify({"Verification_Result": "ID NOT FOUND", "User_ID": user_id}), 404

# --- Future Development: ID Card Generation (IDG-300 logic will go here) ---
# @app.route('/generate/<string:user_id>/pdf', methods=['POST'])
# def generate_card_pdf(user_id):
#    # ... implementation using ReportLab to generate PDF ...
#    pass

if __name__ == '__main__':
    # Render uses the Gunicorn 'start command' to run the app, but this is for local testing.
    app.run(debug=True, port=8000)
