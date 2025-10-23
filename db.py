# db.py - Presidential Campaign Team System Database Model

import os
from datetime import date
from sqlalchemy import create_engine, Column, Integer, String, Date
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from werkzeug.security import generate_password_hash, check_password_hash # For password hashing

# --- 1. Database Connection ---
# Retrieves the connection string from Render's environment variables
DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    # Use a dummy SQLite URL for local testing fallback, otherwise raise error
    if os.environ.get("FLASK_ENV") == "development":
        DATABASE_URL = "sqlite:///pct_local.db"
    else:
        raise ValueError("FATAL: DATABASE_URL environment variable is not configured for production.")

engine = create_engine(DATABASE_URL)
Base = declarative_base()
Session = sessionmaker(bind=engine)

# --- 2. Database Model (MM-100 Schema) ---
class CampaignMember(Base):
    __tablename__ = 'campaign_members'
    
    # Core Identity Fields (Primary Key is Auto-Generated ID)
    id = Column(Integer, primary_key=True)
    user_id = Column(String, unique=True, nullable=False) # PCT-MCS unique ID
    name = Column(String, nullable=False)
    nrc = Column(String, unique=True, nullable=False)     # National Registration Card (MM-101)
    
    # Geographic/Affiliation Fields (GM-201)
    town = Column(String)
    zone = Column(String)
    province = Column(String)
    
    # Membership Status and Media (MM-103, IDG-303)
    membership_start = Column(Date, default=date.today)
    membership_end = Column(Date) 
    status = Column(String, default='Active')             # Active, Expired, Suspended
    
    # Secure Media Reference (SEC-402)
    photo_filename = Column(String) # Reference to the securely stored image file

    # Audit Field (MM-102)
    last_modified = Column(Date, default=date.today)

    def __repr__(self):
        return f"<CampaignMember(user_id='{self.user_id}', name='{self.name}', status='{self.status}')>"

# --- Admin User Model (SEC-400) ---
class AdminUser(Base):
    __tablename__ = 'admin_users'
    
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, default='DataEntry') # Roles: SuperAdmin, ProvincialAdmin, DataEntry

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


# --- 3. Database Initialization Function ---
def create_db_tables():
    """Creates the necessary tables in the database (CampaignMember and AdminUser)."""
    print("Attempting to create database tables...")
    Base.metadata.create_all(engine)
    print("Database tables created successfully or already exist.")

    # --- Initial User Setup (SEC-400: SuperAdmin Creation) ---
    session = Session()
    if session.query(AdminUser).filter_by(username='superadmin').first() is None:
        initial_admin = AdminUser(username='superadmin', role='SuperAdmin')
        initial_admin.set_password('PCT_InitialSecure2025') # **CHANGE THIS PASSWORD IMMEDIATELY**
        session.add(initial_admin)
        session.commit()
        print("Created default SuperAdmin user: 'superadmin'.")
    session.close()

if __name__ == '__main__':
    # This is for manual execution on the Render Shell
    create_db_tables()
