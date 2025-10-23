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
from flask_cors import CORS 
from functools import wraps
from sqlalchemy import func
from sqlalchemy import or_ 

# Import Database Logic
from db import Session, CampaignMember, AdminUser

# --- 1. APPLICATION SETUP & CONFIGURATION ---
app = Flask(__name__)
CORS(app) # Initialize CORS to allow cross-origin requests

# Configuration for secure file handling
UPLOAD_DIR = "/tmp/photos"
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}

def allowed_file(filename):
    """Checks for allowed file extensions."""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- 2. SECURITY DECORATOR (SEC-400) ---
def role_required(required_roles):
    """Decorator to check for user authentication and required roles."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            auth_header = request.headers.get('Authorization')
            if not auth_header or not auth_header.startswith('Bearer '):
                return jsonify({"error": "Authorization token is missing or invalid."}, 401)
            
            auth_token = auth_header.split(' ')[1]
            session = Session()
            user = session.query(AdminUser).filter_by(username=auth_token).first()
            session.close()

            if user is None:
                return jsonify({"error": "User not authenticated."}, 401)
            
            if user.role not in required_roles:
                return jsonify({"error": f"Access Forbidden. Role '{user.role}' cannot access this resource."}, 403)
            
            # Pass the authenticated user object to the route function
            return f(user, *args, **kwargs)
        return decorated_function
    return decorator

# --- 3. CORE ENDPOINTS ---

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

# --- Admin Login Endpoint (SEC-400) ---
@app.route('/admin/login', methods=['POST'])
def admin_login():
    """Authenticates admin and returns their username as a token."""
    data = request.json
    session = Session()
    user = session.query(AdminUser).filter_by(username=data.get('username')).first()
    session.close()

    if user and user.check_password(data.get('password')):
        return jsonify({
            "message": "Login successful. Use your username as the Bearer Token.",
            "role": user.role,
            "token_for_testing": user.username # For testing admin routes
        }), 200
    # FIX: Ensure all failure cases return JSON, not the default HTML error page
    return jsonify({"error": "Invalid credentials. Authentication Failed."}), 401

# --- FEATURE MM-100 & MM-101: SECURE MEMBER REGISTRATION ---
@app.route('/members/register', methods=['POST'])
@role_required(['SuperAdmin', 'ProvincialAdmin', 'DataEntry'])
def register_member(admin_user):
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
        end_date_str = data.get('membership_end_date', '2028-12-31')
        
        new_member = CampaignMember(
            user_id=unique_id,
            name=data.get('name', 'N/A'),
            nrc=nrc,
            province=data.get('province', 'Unknown'),
            town=data.get('town', 'N/A'),
            zone=data.get('zone', 'N/A'),
            membership_start=date.today(),
            membership_end=date.fromisoformat(end_date_str),
            status='Active',
            photo_filename=filename, # SEC-402: Storing reference, not the image itself
            last_modified=date.today()
        )
        session.add(new_member)
        session.commit()
        
        return jsonify({
            "message": "Campaign Member registered successfully.",
            "user_id": unique_id
        }), 201

    except Exception as e:
        session.rollback()
        print(f"Registration Error: {e}")
        return jsonify({"error": f"Internal Server Error: {str(e)}"}, 500)
    finally:
        session.close()

# --- FEATURE MM-104: ADVANCED SEARCH & FILTERING (SEC-400) ---
@app.route('/admin/members/search', methods=['GET'])
@role_required(['SuperAdmin', 'ProvincialAdmin', 'DataEntry'])
def member_search(admin_user):
    """Searches and filters member records based on query parameters."""
    session = Session()
    query = session.query(CampaignMember)
    
    # 1. Apply Dynamic Filters
    if request.args.get('province'):
        query = query.filter(CampaignMember.province == request.args['province'])
    if request.args.get('status'):
        query = query.filter(CampaignMember.status == request.args['status'])

    # Search against multiple fields for partial matches
    search_term = request.args.get('q')
    if search_term:
        search_like = f"%{search_term}%"
        query = query.filter(or_(
            CampaignMember.name.ilike(search_like),
            CampaignMember.nrc.ilike(search_like),
            CampaignMember.town.ilike(search_like)
        ))

    # 2. Execute Query and Format Results
    members = query.limit(100).all()
    session.close()
    
    results = [{
        "user_id": m.user_id,
        "name": m.name,
        "nrc": m.nrc,
        "province": m.province,
        "status": m.status,
        "membership_end": m.membership_end.isoformat()
    } for m in members]

    return jsonify({
        "admin_role": admin_user.role,
        "total_results": len(results),
        "members": results
    })

# --- FEATURE GM-202: BULK DATA REPORTING (Grouped) (SEC-400) ---
@app.route('/admin/reports/region', methods=['GET'])
@role_required(['SuperAdmin', 'ProvincialAdmin'])
def region_report(admin_user):
    """Generates a summary of member counts grouped by Province and Status."""
    session = Session()
    
    report_data = session.query(
        CampaignMember.province,
        CampaignMember.status,
        func.count(CampaignMember.id).label('member_count')
    ).group_by(
        CampaignMember.province,
        CampaignMember.status
    ).order_by(
        CampaignMember.province,
        CampaignMember.status
    ).all()
    
    session.close()

    results = {}
    for province, status, count in report_data:
        if province not in results:
            results[province] = {'Total': 0}
        
        results[province][status] = count
        results[province]['Total'] += count

    return jsonify({
        "admin_role": admin_user.role,
        "report_type": "Regional Member Status Summary (GM-202)",
        "summary": results
    })

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
    # FIX: Robust check for file existence before attempting to draw (prevents 500 HTML error)
    if os.path.exists(photo_path):
        try:
            p.drawImage(photo_path, X_START + 10, Y_START + 105, PHOTO_SIZE, PHOTO_SIZE, preserveAspectRatio=True)
        except Exception:
            p.drawString(X_START + 10, Y_START + 145, "[Error Loading Photo]")
            
    else:
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

# --- FEATURE SEC-401: REAL-TIME VERIFICATION PORTAL ENDPOINT ---
@app.route('/verify/<string:user_id>', methods=['GET'])
def verify_member(user_id):
    """Provides public verification data for QR code scanning (SEC-401)."""
    session = Session()
    member = session.query(CampaignMember).filter_by(user_id=user_id).first()
    session.close()

    if not member:
        return jsonify({"error": "ID not found in system."}, 404)
    
    # Check expiry status
    is_active = member.status == 'Active' and member.membership_end >= date.today()
    
    return jsonify({
        "User_ID": member.user_id,
        "Name": member.name,
        "Status": member.status,
        "Valid_Until": member.membership_end.isoformat(),
        "Verification_Result": "AUTHENTICATED" if is_active else "EXPIRED/INACTIVE"
    })


# --- EXECUTION BLOCK ---
if __name__ == '__main__':
    # Only runs if executed directly (e.g., during local development)
    app.run(debug=True, port=8000)
