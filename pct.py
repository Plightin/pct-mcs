# pct.py - Presidential Campaign Team System (PCT-MCS) Full Implementation

import os
import uuid
from datetime import date
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing
from reportlab.graphics import renderPDF
from flask import Flask, jsonify, request, send_file
from werkzeug.utils import secure_filename

# Import Database Logic
from db import Session, CampaignMember

# --- 1. APPLICATION SETUP & CONFIGURATION ---
app = Flask(__name__)

# Configuration for secure file handling
# NOTE: In Render, /tmp is the only writable directory, but data here is volatile.
# A true production system would use AWS S3/Google Cloud Storage for permanent photo storage.
UPLOAD_DIR = "/tmp/photos"
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}

def allowed_file(filename):
    """Checks for allowed file extensions."""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- 2. CORE ENDPOINTS ---

@app.route('/')
def home():
    """Confirms the web service is running."""
    session = Session()
    member_count = session.query(CampaignMember).count()
    session.close()
    
    return jsonify({
        "status": "online",
        "system": "Presidential Campaign Team System (PCT-MCS)",
        "message": "API is active.",
        "active_members_in_db": member_count
    })

# --- FEATURE MM-100 & MM-101: SECURE MEMBER REGISTRATION ---
@app.route('/members/register', methods=['POST'])
def register_member():
    """Handles new member registration, NRC uniqueness check, and photo upload."""
    session = Session()
    try:
        data = request.form
        photo_file = request.files.get('id_photo')
        
        # 1. Validation Checks (MM-101)
        nrc = data.get('nrc')
        if not nrc or not photo_file:
            return jsonify({"error": "Missing required data (NRC or Photo ID)."}, 400)
            
        if session.query(CampaignMember).filter_by(nrc=nrc).first():
            return jsonify({"error": "NRC already exists. Cannot create duplicate member."}, 409)

        if not allowed_file(photo_file.filename):
            return jsonify({"error": "Invalid photo file type. Must be PNG, JPG, or JPEG."}, 400)

        # 2. Secure File Handling (SEC-404)
        unique_id = f"PCT-{date.today().year}-{uuid.uuid4().hex[:6].upper()}"
        filename = secure_filename(f"{unique_id}_photo.jpg")
        
        filepath = os.path.join(UPLOAD_DIR, filename)
        photo_file.save(filepath)
        
        # 3. Save to Database (MM-100)
        # Assuming required dates are provided or defaulted
        end_date_str = data.get('membership_end_date', '2028-12-31')
        
        new_member = CampaignMember(
            user_id=unique_id,
            name=data.get('name', 'N/A'),
            nrc=nrc,
            province=data.get('province', 'Unknown'),
            town=data.get('town', 'N/A'),
            zone=data.get('zone', 'N/A'),
            membership_end=date.fromisoformat(end_date_str),
            photo_filename=filename,
            last_modified=date.today()
        )
        session.add(new_member)
        session.commit()
        
        return jsonify({
            "message": "Campaign Member registered successfully.",
            "user_id": unique_id,
            "verification_link": f"{request.host_url}members/{unique_id}/card"
        }), 201

    except Exception as e:
        session.rollback()
        # In a real system, log the full traceback for SEC-403 Audit
        print(f"Registration Error: {e}")
        return jsonify({"error": f"Internal Server Error: {str(e)}"}, 500)
    finally:
        session.close()

# --- FEATURE IDG-300: DIGITAL ID CARD GENERATION ---
@app.route('/members/<string:user_id>/card', methods=['GET'])
def generate_member_card(user_id):
    """Generates the secure PDF Membership Card (PCT-MC)."""
    session = Session()
    member = session.query(CampaignMember).filter_by(user_id=user_id).first()
    session.close()

    if not member:
        return jsonify({"error": "Member not found."}, 404)
        
    if member.status != 'Active':
        return jsonify({"error": f"Card generation failed: Member status is {member.status}. Access Denied."}, 403)

    # Use BytesIO to create the PDF in memory (IDG-300)
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    
    # Card Design Parameters (IDG-301)
    CARD_WIDTH = 320
    CARD_HEIGHT = 210
    X_START = 50
    Y_START = height - CARD_HEIGHT - 50 
    PHOTO_SIZE = 90
    QR_SIZE = 60

    # 1. Border and Header
    p.setStrokeColorRGB(0.1, 0.1, 0.4) 
    p.setLineWidth(2)
    p.rect(X_START, Y_START, CARD_WIDTH, CARD_HEIGHT, stroke=1, fill=0)

    p.setFont("Helvetica-Bold", 16)
    p.setFillColorRGB(0.4, 0.0, 0.0) 
    p.drawCentredString(X_START + CARD_WIDTH / 2, Y_START + CARD_HEIGHT - 25, "PRESIDENTIAL CAMPAIGN TEAM")
    p.setFont("Helvetica", 10)
    p.drawCentredString(X_START + CARD_WIDTH / 2, Y_START + CARD_HEIGHT - 40, "OFFICIAL MEMBERSHIP CARD (PCT-MC)")

    # 2. Draw Official Photo ID (ID Face)
    photo_path = os.path.join(UPLOAD_DIR, member.photo_filename)
    try:
        p.drawImage(photo_path, X_START + 10, Y_START + 105, PHOTO_SIZE, PHOTO_SIZE, preserveAspectRatio=True)
    except Exception:
        # Fallback if image file is missing (SEC-402)
        p.drawString(X_START + 10, Y_START + 145, "[Photo Placeholder]")

    # 3. Draw Member Details
    p.setFillColorRGB(0, 0, 0)
    p.setFont("Helvetica-Bold", 11)
    p.drawString(X_START + PHOTO_SIZE + 20, Y_START + 160, f"NAME: {member.name.upper()}")
    p.drawString(X_START + PHOTO_SIZE + 20, Y_START + 145, f"NRC: {member.nrc}")
    p.drawString(X_START + PHOTO_SIZE + 20, Y_START + 130, f"ID: {member.user_id}")
    
    # Geographic Data (GM-201)
    p.setFont("Helvetica", 10)
    p.drawString(X_START + PHOTO_SIZE + 20, Y_START + 105, f"Province: {member.province}")
    p.drawString(X_START + PHOTO_SIZE + 20, Y_START + 90, f"Region/Town: {member.zone} / {member.town}")
    
    # 4. Draw Membership Period (IDG-303)
    p.setFont("Helvetica-BoldOblique", 11)
    p.setFillColorRGB(0.5, 0.1, 0.1)
    p.drawString(X_START + 10, Y_START + 70, f"VALID UNTIL: {member.membership_end.strftime('%Y-%m-%d')}")
    
    # 5. Draw QR Code (IDG-302)
    qr_data = f"PCT-VERIFY:{member.user_id}|STATUS:{member.status}" 
    qrw = qr.QrCodeWidget(qr_data)
    
    d = Drawing(QR_SIZE, QR_SIZE, transform=[QR_SIZE / (qrw.getBounds()[2]-qrw.getBounds()[0]), 0, 0, QR_SIZE / (qrw.getBounds()[3]-qrw.getBounds()[1]), 0, 0])
    d.add(qrw)
    renderPDF.draw(d, p, X_START + 10, Y_START + 10) # Position bottom-left
    
    p.setFont("Helvetica", 8)
    p.setFillColorRGB(0, 0, 0)
    p.drawString(X_START + QR_SIZE + 20, Y_START + 30, "Scan to verify status (SEC-401)")

    # Finalize and Return PDF
    p.showPage()
    p.save()
    
    buffer.seek(0)
    return send_file(
        buffer,
        as_attachment=True,
        download_name=f"PCT_ID_Card_{member.user_id}.pdf",
        mimetype='application/pdf'
    )

# --- EXECUTION BLOCK ---
if __name__ == '__main__':
    # Only runs if executed directly (e.g., during local development)
    # Note: On Render, Gunicorn runs the app, not this block.
    # For local testing, ensure your database connection is set up first.
    app.run(debug=True, port=8000)
