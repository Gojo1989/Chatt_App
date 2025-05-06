from app import app, db
from sqlalchemy import text

def upgrade_database():
    with app.app_context():
        # Add new columns to User table
        with db.engine.connect() as conn:
            conn.execute(text('ALTER TABLE user ADD COLUMN gender VARCHAR(10)'))
            conn.execute(text('ALTER TABLE user ADD COLUMN theme_color VARCHAR(20) DEFAULT "#007bff"'))
            conn.execute(text('ALTER TABLE user ADD COLUMN theme_mode VARCHAR(10) DEFAULT "light"'))
            conn.commit()

if __name__ == '__main__':
    upgrade_database() 