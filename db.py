# db.py - Presidential Campaign Team System Database Model

import os
from datetime import date
from sqlalchemy import create_engine, Column, Integer, String, Date
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base

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

# --- 3. Database Initialization Function ---
def create_db_tables():
    """Creates the necessary tables in the database."""
    print("Attempting to create database tables...")
    Base.metadata.create_all(engine)
    print("Database tables created successfully or already exist.")

if __name__ == '__main__':
    # This is for manual execution on the Render Shell
    create_db_tables()
