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
from reportlab.lib.utils import ImageReader # For handling images in ReportLab
from reportlab.lib import colors # For defining custom colors
from flask import Flask, jsonify, request, send_file
from werkzeug.utils import secure_filename
from flask_cors import CORS 
from functools import wraps
from sqlalchemy import func
from sqlalchemy import or_ 
from sqlalchemy.exc import OperationalError # Import to catch connection issues

# Import Database Logic
from db import Session, CampaignMember, AdminUser, create_db_tables

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
    """Confirms the web service is running and checks DB connectivity."""
    session = Session()
    try:
        # Perform a quick query to test database connectivity
        member_count = session.query(CampaignMember).count()
        
        return jsonify({
            "status": "online",
            "system": "Presidential Campaign Team System (PCT-MCS)",
            "message": "API and Database connection are active.",
            "active_members_in_db": member_count
        })
    
    except OperationalError as e:
        print(f"FATAL DB ERROR: {e}")
        return jsonify({
            "status": "offline/db-error",
            "message": "Database Operational Error: Cannot connect or tables not created.",
            "troubleshoot": "Ensure DATABASE_URL is correct and run the database initialization script."
        }), 500
    
    finally:
        session.close()

# --- Admin Login Endpoint (SEC-400) ---
@app.route('/admin/login', methods=['POST'])
def admin_login():
    """Authenticates admin and returns their username as a token."""
    data = request.json
    session = Session()
    try:
        user = session.query(AdminUser).filter_by(username=data.get('username')).first()
        
        if user and user.check_password(data.get('password')):
            return jsonify({
                "message": "Login successful. Use your username as the Bearer Token.",
                "role": user.role,
                "token_for_testing": user.username # For testing admin routes
            }), 200
        
        # FIX: Ensure all failure cases return JSON, not the default HTML error page
        return jsonify({"error": "Invalid credentials. Authentication Failed."}), 401
    
    except OperationalError as e:
        print(f"Login DB Operational Error: {e}")
        return jsonify({
            "error": "Database error during login. Check server logs.",
        }), 500
    
    finally:
        session.close()


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

    except OperationalError as e:
        session.rollback()
        print(f"Registration DB Operational Error: {e}")
        return jsonify({"error": "Database is unavailable. Cannot register member."}, 500)

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
    try:
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

    except OperationalError as e:
        print(f"Search DB Operational Error: {e}")
        return jsonify({"error": "Database is unavailable. Cannot perform search."}, 500)
    
    except Exception as e:
        print(f"Search Error: {e}")
        return jsonify({"error": f"Internal Server Error: {str(e)}"}, 500)
    
    finally:
        session.close()

# --- FEATURE GM-202: BULK DATA REPORTING (Grouped) (SEC-400) ---
@app.route('/admin/reports/region', methods=['GET'])
@role_required(['SuperAdmin', 'ProvincialAdmin'])
def region_report(admin_user):
    """Generates a summary of member counts grouped by Province and Status."""
    session = Session()
    try:
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

    except OperationalError as e:
        print(f"Report DB Operational Error: {e}")
        return jsonify({"error": "Database is unavailable. Cannot generate report."}, 500)
    
    except Exception as e:
        print(f"Report Error: {e}")
        return jsonify({"error": f"Internal Server Error: {str(e)}"}, 500)
    
    finally:
        session.close()

# --- FEATURE IDG-300: DIGITAL ID CARD GENERATION ---
@app.route('/members/<string:user_id>/card', methods=['GET'])
def generate_member_card(user_id):
    """Generates the secure PDF Membership Card (PCT-MC) with enhanced design."""
    session = Session()
    try:
        member = session.query(CampaignMember).filter_by(user_id=user_id).first()

        if not member:
            return jsonify({"error": "Member not found."}, 404)
            
        if member.status != 'Active':
            return jsonify({"error": f"Card generation failed: Member status is {member.status}. Access Denied."}, 403)

        # Use BytesIO to create the PDF in memory (IDG-300)
        buffer = BytesIO()
        p = canvas.Canvas(buffer, pagesize=letter)
        width, height = letter
        
        # --- Card Design Parameters (Enhanced IDG-301) ---
        CARD_WIDTH = 350
        CARD_HEIGHT = 220
        X_OFFSET = 50 # Starting X position for the card
        Y_OFFSET = height - CARD_HEIGHT - 50 # Starting Y position for the card (top-down)

        PHOTO_BOX_SIZE = 90
        PHOTO_X = X_OFFSET + 15
        PHOTO_Y = Y_OFFSET + CARD_HEIGHT - PHOTO_BOX_SIZE - 20 # Position from card top
        
        QR_CODE_SIZE = 60
        QR_X = X_OFFSET + 15
        QR_Y = Y_OFFSET + 15 # Position from card bottom

        # --- Define Colors ---
        COLOR_PRIMARY_RED = colors.Color(0.85, 0.27, 0.2) # A strong red
        COLOR_DARK_BLUE = colors.Color(0.1, 0.1, 0.4)
        COLOR_ACCENT_YELLOW = colors.Color(0.95, 0.75, 0.0)
        COLOR_TEXT_LIGHT = colors.white
        COLOR_TEXT_DARK = colors.black

        # --- 1. Draw Card Background and Border ---
        p.setFillColor(colors.white)
        p.setStrokeColor(COLOR_DARK_BLUE)
        p.setLineWidth(1.5)
        p.roundRect(X_OFFSET, Y_OFFSET, CARD_WIDTH, CARD_HEIGHT, 10, stroke=1, fill=1)

        # Draw Inner Red Background
        p.setFillColor(COLOR_PRIMARY_RED)
        p.rect(X_OFFSET + 2, Y_OFFSET + 2, CARD_WIDTH - 4, CARD_HEIGHT - 4, stroke=0, fill=1)

        # --- 2. Campaign Logo (Top Right - UPND.jpg) ---
        # FIX 1: Explicitly use the correct logo filename 'UPND.jpg'
        try:
            script_dir = os.path.dirname(__file__)
            logo_path = os.path.join(script_dir, 'UPND.jpg') 
            if os.path.exists(logo_path):
                logo = ImageReader(logo_path)
                # Position the logo in the top right corner area, size reduced slightly
                p.drawImage(logo, X_OFFSET + CARD_WIDTH - 85, Y_OFFSET + CARD_HEIGHT - 60, 70, 50, preserveAspectRatio=True, mask='auto')
            else:
                p.setFillColor(COLOR_TEXT_LIGHT)
                p.setFont("Helvetica-Bold", 10)
                p.drawString(X_OFFSET + CARD_WIDTH - 75, Y_OFFSET + CARD_HEIGHT - 35, "PCT Logo Missing")
        except Exception as e:
            print(f"Error loading logo: {e}")
            p.setFillColor(COLOR_TEXT_LIGHT)
            p.setFont("Helvetica-Bold", 10)
            p.drawString(X_OFFSET + CARD_WIDTH - 75, Y_OFFSET + CARD_HEIGHT - 35, "PCT Logo Error")


        # --- 3. Header Text ---
        # Shift the header text left to avoid the logo
        HEADER_X = X_OFFSET + 120 
        
        p.setFont("Helvetica-Bold", 16)
        p.setFillColor(COLOR_TEXT_LIGHT)
        p.drawString(HEADER_X, Y_OFFSET + CARD_HEIGHT - 30, "PRESIDENTIAL CAMPAIGN TEAM")
        p.setFont("Helvetica", 10)
        p.drawString(HEADER_X, Y_OFFSET + CARD_HEIGHT - 45, "OFFICIAL MEMBERSHIP CARD (PCT-MC)")

        # --- 4. Photo Placeholder (Circular Frame) ---
        p.setFillColor(colors.white)
        p.setStrokeColor(COLOR_ACCENT_YELLOW) # Frame color
        p.setLineWidth(2)
        p.circle(PHOTO_X + PHOTO_BOX_SIZE/2, PHOTO_Y + PHOTO_BOX_SIZE/2, PHOTO_BOX_SIZE/2, stroke=1, fill=1) # Draw white circle with yellow border

        # Draw Official Photo ID (ID Face)
        photo_path = os.path.join(UPLOAD_DIR, member.photo_filename)
        
        # FIX 2: Handle the Photo Error Placeholder more gracefully
        try:
            if os.path.exists(photo_path):
                # Try loading the image only if the file exists locally
                img = ImageReader(photo_path)
                
                # Use a circular clip path for the photo
                p.saveState()
                p.setFillColor(colors.white) 
                p.setStrokeColor(colors.white)
                p.circle(PHOTO_X + PHOTO_BOX_SIZE/2, PHOTO_Y + PHOTO_BOX_SIZE/2, PHOTO_BOX_SIZE/2, stroke=0, fill=1)
                p.clipPage()
                p.drawImage(img, PHOTO_X, PHOTO_Y, PHOTO_BOX_SIZE, PHOTO_BOX_SIZE, preserveAspectRatio=True, mask='auto')
                p.restoreState() # Restore context after clipping
            else:
                # File not found (e.g., server restart or temporary file deleted)
                p.setFillColor(COLOR_TEXT_DARK)
                p.setFont("Helvetica-Bold", 10)
                p.drawCentredString(PHOTO_X + PHOTO_BOX_SIZE/2, PHOTO_Y + PHOTO_BOX_SIZE/2 + 5, "Photo File")
                p.drawCentredString(PHOTO_X + PHOTO_BOX_SIZE/2, PHOTO_Y + PHOTO_BOX_SIZE/2 - 5, "Missing (SEC-402)")

        except Exception as e:
            # If ReportLab fails to draw the image for other reasons (e.g., corrupt file)
            print(f"Photo drawing error: {e}")
            p.setFillColor(COLOR_TEXT_DARK)
            p.setFont("Helvetica", 8)
            p.drawCentredString(PHOTO_X + PHOTO_BOX_SIZE/2, PHOTO_Y + PHOTO_BOX_SIZE/2 - 5, "Photo Error")
            p.drawCentredString(PHOTO_X + PHOTO_BOX_SIZE/2, PHOTO_Y + PHOTO_BOX_SIZE/2 - 15, "Placeholder")


        # --- 5. Member Details ---
        DETAIL_TEXT_X = X_OFFSET + PHOTO_BOX_SIZE + 15 # Start details block at 15pt right of photo border
        DETAIL_Y_START = Y_OFFSET + CARD_HEIGHT - 70 # Starting Y position for details
        LINE_SPACING = 12 # Tightened spacing for better fit

        p.setFillColor(COLOR_TEXT_LIGHT)
        p.setFont("Helvetica-Bold", 11)
        p.drawString(DETAIL_TEXT_X, DETAIL_Y_START, f"NAME: {member.name.upper()}")
        p.drawString(DETAIL_TEXT_X, DETAIL_Y_START - LINE_SPACING, f"NRC: {member.nrc}")
        p.drawString(DETAIL_TEXT_X, DETAIL_Y_START - (2 * LINE_SPACING), f"ID: {member.user_id}")
        
        # Geographic Data (GM-201)
        p.setFont("Helvetica", 9)
        p.drawString(DETAIL_TEXT_X, DETAIL_Y_START - (3.5 * LINE_SPACING) - 5, f"Province: {member.province}") 
        p.drawString(DETAIL_TEXT_X, DETAIL_Y_START - (4.5 * LINE_SPACING) - 5, f"Town: {member.town}")
        p.drawString(DETAIL_TEXT_X, DETAIL_Y_START - (5.5 * LINE_SPACING) - 5, f"Zone: {member.zone}")

        # --- 6. Membership Period (IDG-303) - Stylized Band ---
        BAND_HEIGHT = 25
        BAND_Y = Y_OFFSET + 65 
        p.setFillColor(COLOR_ACCENT_YELLOW)
        p.rect(X_OFFSET + 2, BAND_Y, CARD_WIDTH - 4, BAND_HEIGHT, stroke=0, fill=1) 

        p.setFont("Helvetica-BoldOblique", 12)
        p.setFillColor(COLOR_DARK_BLUE)
        p.drawCentredString(X_OFFSET + CARD_WIDTH / 2, BAND_Y + 8, 
                           f"VALID UNTIL: {member.membership_end.strftime('%Y-%m-%d')}")
        
        # --- 7. QR Code (IDG-302) ---
        qr_data = f"PCT-VERIFY:{member.user_id}|STATUS:{member.status}|EXPIRY:{member.membership_end.strftime('%Y-%m-%d')}" 
        qrw = qr.QrCodeWidget(qr_data)
        
        # Adjust QR code bounds for rendering
        bounds = qrw.getBounds()
        x1, y1, x2, y2 = bounds
        qr_drawing = Drawing(QR_CODE_SIZE, QR_CODE_SIZE, transform=[QR_CODE_SIZE/(x2-x1),0,0,QR_CODE_SIZE/(y2-y1),-x1*QR_CODE_SIZE/(x2-x1),-y1*QR_CODE_SIZE/(y2-y1)])
        qr_drawing.add(qrw)
        renderPDF.draw(qr_drawing, p, QR_X, QR_Y) # Position bottom-left
        
        # Verification Text below QR
        p.setFont("Helvetica", 8)
        p.setFillColor(COLOR_TEXT_LIGHT)
        p.drawString(QR_X + QR_CODE_SIZE + 5, QR_Y + 25, "Scan to verify status (SEC-401)")
        p.drawString(QR_X + QR_CODE_SIZE + 5, QR_Y + 15, "ID: " + member.user_id) # Repeat ID for quick lookup

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

    except OperationalError as e:
        print(f"PDF Generation DB Operational Error: {e}")
        return jsonify({"error": "Database is unavailable. Cannot generate PDF."}, 500)

    except Exception as e:
        print(f"PDF Generation Error: {e}")
        return jsonify({"error": f"Internal Server Error during PDF generation: {str(e)}"}, 500)
    
    finally:
        session.close()

# --- FEATURE SEC-401: REAL-TIME VERIFICATION PORTAL ENDPOINT ---
@app.route('/verify/<string:user_id>', methods=['GET'])
def verify_member(user_id):
    """Provides public verification data for QR code scanning (SEC-401)."""
    session = Session()
    try:
        member = session.query(CampaignMember).filter_by(user_id=user_id).first()

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

    except OperationalError as e:
        print(f"Verification DB Operational Error: {e}")
        return jsonify({"error": "Database is unavailable. Cannot verify ID."}, 500)
    
    except Exception as e:
        print(f"Verification Error: {e}")
        return jsonify({"error": f"Internal Server Error during verification: {str(e)}"}, 500)
    
    finally:
        session.close()


# --- EXECUTION BLOCK ---
if __name__ == '__main__':
    # Only runs if executed directly (e.g., during local development)
    app.run(debug=True, port=8000)
