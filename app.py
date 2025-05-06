from flask import Flask, request, jsonify, render_template, redirect, url_for, session, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, join_room, leave_room, send
from datetime import datetime, timedelta
import pytz
import os
from werkzeug.utils import secure_filename
from flask_migrate import Migrate

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///db.sqlite3'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = "supersecretkey"

# File upload settings
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif', 'doc', 'docx'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Create uploads directory if it doesn't exist
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'userid' not in session:
        return jsonify({"error": "Not authenticated"}), 401
    
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        # Add timestamp to filename to make it unique
        filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{filename}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        return jsonify({
            "message": "File uploaded successfully",
            "filename": filename,
            "url": url_for('uploaded_file', filename=filename)
        })
    
    return jsonify({"error": "File type not allowed"}), 400

# Initialize database and socketio
db = SQLAlchemy(app)
socketio = SocketIO(app)

# Initialize Flask-Migrate
migrate = Migrate(app, db)

# Set default timezone to UTC
default_timezone = pytz.UTC

# Add context processor to inject current_user into all templates
def get_current_user():
    if 'userid' in session:
        user = User.query.filter_by(userid=session['userid']).first()
        return user
    return None

@app.context_processor
def inject_current_user():
    return dict(current_user=get_current_user())

class User(db.Model):
    userid = db.Column(db.String(20), primary_key=True)
    password = db.Column(db.String(20), nullable=False)
    email = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(70), nullable=False)
    contact = db.Column(db.String(15), nullable=False)
    gender = db.Column(db.String(10), nullable=True)
    theme_color = db.Column(db.String(20), default='#007bff')  # Default blue theme
    theme_mode = db.Column(db.String(10), default='light')  # light or dark
    profile_photo = db.Column(db.String(200), nullable=True)  # Path to profile photo
    background_photo = db.Column(db.String(200), nullable=True)  # Path to background photo

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    senderid = db.Column(db.String(20), db.ForeignKey('user.userid'), nullable=False, index=True)
    receiverid = db.Column(db.String(20), db.ForeignKey('user.userid'), nullable=False, index=True)
    content = db.Column(db.Text, nullable=True)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(default_timezone))
    status = db.Column(db.String(10), default='unread')

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/signup', methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        userid = request.form["userid"]
        password = request.form["password"]
        email = request.form["email"]
        name = request.form["name"]
        contact = request.form.get("contact")
        gender = request.form.get("gender", "male")  # Default to male if not specified
        
        if User.query.filter_by(email=email).first():
            return jsonify({"message": "Email already registered!"}), 400
        if User.query.filter_by(userid=userid).first():
            return jsonify({"message": "Userid already registered!"}), 400
        
        newuser = User(
            userid=userid,
            password=password,
            email=email,
            name=name,
            contact=contact,
            gender=gender
        )
        db.session.add(newuser)
        db.session.commit()
        return redirect(url_for("login"))
    return render_template('signup.html')

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        userid = request.form["userid"]
        password = request.form["password"]
        user = User.query.filter_by(userid=userid).first()
        if user and user.password == password:
            session["userid"] = user.userid
            return redirect(url_for("dashboard"))
        else:
            return jsonify({"message": "Invalid Credentials"}), 400
    return render_template('login.html')

@app.route("/dashboard")
def dashboard():
    if "userid" not in session:
        return redirect(url_for('login'))

    userid = session['userid']
    
    # Get current user details
    current_user = User.query.filter_by(userid=userid).first()
    
    # Get all users who have chatted with the current user, ordered by most recent message
    chatted_users = db.session.query(
        User,
        db.func.max(Message.timestamp).label('last_message_time'),
        db.func.count(Message.id).filter(
            (Message.receiverid == userid) & 
            (Message.status == 'unread')
        ).label('unread_count')
    ).join(
        Message, 
        ((Message.senderid == User.userid) & (Message.receiverid == userid)) |
        ((Message.receiverid == User.userid) & (Message.senderid == userid))
    ).filter(
        User.userid != userid
    ).group_by(
        User.userid,
        User.name,
        User.email,
        User.profile_photo,
        User.gender
    ).order_by(
        db.desc('last_message_time')
    ).all()

    # Get all users except current user for the user list
    all_users = User.query.filter(User.userid != userid).order_by(User.userid).all()
    users_list = [{
        "userid": user.userid,
        "name": user.name,
        "email": user.email,
        "profile_photo": user.profile_photo,
        "gender": user.gender
    } for user in all_users]

    # Format chatted users with last message preview and unread count
    chatted_users_list = []
    for user in chatted_users:
        # Get the last message between current user and this user
        last_message = Message.query.filter(
            ((Message.senderid == userid) & (Message.receiverid == user.User.userid)) |
            ((Message.senderid == user.User.userid) & (Message.receiverid == userid))
        ).order_by(Message.timestamp.desc()).first()

        # Get the last message content and sender info
        last_message_content = ""
        last_message_sender = None
        if last_message:
            last_message_content = last_message.content
            last_message_sender = last_message.senderid

        chatted_users_list.append({
            "userid": user.User.userid,
            "name": user.User.name,
            "email": user.User.email,
            "profile_photo": user.User.profile_photo,
            "gender": user.User.gender,
            "last_message": last_message_content[:30] + "..." if last_message_content and len(last_message_content) > 30 else last_message_content,
            "last_message_time": last_message.timestamp.strftime('%Y-%m-%d %H:%M:%S') if last_message else None,
            "last_message_sender": last_message_sender,
            "unread_count": user.unread_count
        })

    return render_template('dashboard.html', 
                         userid=userid, 
                         chatted_users=chatted_users_list,
                         all_users=users_list,
                         current_user={
                             "userid": current_user.userid,
                             "name": current_user.name,
                             "email": current_user.email,
                             "profile_photo": current_user.profile_photo,
                             "gender": current_user.gender,
                             "background_photo": current_user.background_photo
                         })

@app.route("/search_users")
def search_users():
    if "userid" not in session:
        return jsonify({"error": "Not authenticated"}), 401

    search_query = request.args.get('query', '').strip()
    current_user = session['userid']

    # Search for users whose userid or name contains the search query
    users = User.query.filter(
        User.userid != current_user,
        db.or_(
            User.userid.ilike(f'%{search_query}%'),
            User.name.ilike(f'%{search_query}%'),
            User.email.ilike(f'%{search_query}%')
        )
    ).order_by(User.userid).all()

    results = [{
        "userid": user.userid,
        "name": user.name,
        "email": user.email
    } for user in users]

    return jsonify(results)

@app.route("/remove_chat/<userid>", methods=["POST"])
def remove_chat(userid):
    if "userid" not in session:
        return jsonify({"error": "Not authenticated"}), 401

    current_user = session['userid']
    
    # Delete all messages between the two users
    Message.query.filter(
        ((Message.senderid == current_user) & (Message.receiverid == userid)) |
        ((Message.senderid == userid) & (Message.receiverid == current_user))
    ).delete()
    
    db.session.commit()
    return jsonify({"message": "Chat history removed successfully"})

@app.route("/delete_all_chats", methods=["POST"])
def delete_all_chats():
    if "userid" not in session:
        return jsonify({"error": "Not authenticated"}), 401

    current_user = session['userid']
    
    # Delete all messages where the current user is either sender or receiver
    Message.query.filter(
        (Message.senderid == current_user) | (Message.receiverid == current_user)
    ).delete()
    
    db.session.commit()
    return jsonify({"message": "All chats deleted successfully"})

@app.route("/delete_chats_by_date", methods=["POST"])
def delete_chats_by_date():
    if "userid" not in session:
        return jsonify({"error": "Not authenticated"}), 401

    current_user = session['userid']
    data = request.json
    
    try:
        # Validate required fields
        if not data or 'start_date' not in data or 'end_date' not in data:
            return jsonify({"error": "Start date and end date are required"}), 400
            
        # Parse dates
        try:
            start_date = datetime.strptime(data['start_date'], '%Y-%m-%d')
            end_date = datetime.strptime(data['end_date'], '%Y-%m-%d')
        except ValueError:
            return jsonify({"error": "Invalid date format. Please use YYYY-MM-DD format"}), 400
            
        # Validate date range
        if start_date > end_date:
            return jsonify({"error": "Start date cannot be after end date"}), 400
            
        # Set end_date to end of day
        end_date = end_date.replace(hour=23, minute=59, second=59)
        
        # Delete messages within the date range where the current user is either sender or receiver
        deleted_count = Message.query.filter(
            ((Message.senderid == current_user) | (Message.receiverid == current_user)) &
            (Message.timestamp >= start_date) &
            (Message.timestamp <= end_date)
        ).delete(synchronize_session=False)
        
        db.session.commit()
        return jsonify({
            "message": f"Successfully deleted {deleted_count} messages",
            "deleted_count": deleted_count
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@app.route("/finduser", methods=["GET", "POST"])
def finduser():
    if request.method == "POST":
        search = request.form.get("userid") or request.form.get("email")
        user = User.query.filter((User.userid == search) | (User.email == search)).first()
        if user:
            return redirect(url_for("chat", userid=user.userid))
        else:
            return jsonify({"message": "User not found"}), 404
    return render_template("dashboard.html")

@app.route("/chat/<userid>", methods=["GET", "POST"])
def chat(userid):
    if "userid" not in session:
        return redirect(url_for('login'))

    senderid = session['userid']
    
    # Get receiver's information
    receiver = User.query.filter_by(userid=userid).first()
    if not receiver:
        return redirect(url_for('dashboard'))

    if request.method == "POST":
        content = request.form.get('message') or (request.json.get('message') if request.is_json else None)
        
        if not content:
            return jsonify({"error": "Message content is required"}), 400

        # Create message with UTC timestamp
        current_time = datetime.now(default_timezone)
        new_message = Message(
            senderid=senderid,
            receiverid=userid,
            content=content,
            timestamp=current_time,
            status='unread'
        )
        db.session.add(new_message)
        db.session.commit()

        # Get the room name
        room_name = ''.join(sorted(map(str, [senderid, userid])))
        
        # Emit the new message to the room
        socketio.emit('message', {
            "id": new_message.id,
            "sender": senderid,
            "message": content,
            "timestamp": current_time.isoformat(),
            "status": "unread"
        }, room=room_name)

        return jsonify({
            "status": "Message Sent!",
            "message": {
                "id": new_message.id,
                "sender": senderid,
                "content": content,
                "timestamp": current_time.isoformat(),
                "status": "unread"
            }
        })

    # Mark all unread messages from this user as read
    Message.query.filter_by(
        senderid=userid,
        receiverid=senderid,
        status='unread'
    ).update({'status': 'read'})
    db.session.commit()

    # Fetch chat history (last 50 messages)
    messages = Message.query.filter(
        ((Message.senderid == senderid) & (Message.receiverid == userid)) |
        ((Message.senderid == userid) & (Message.receiverid == senderid))
    ).order_by(Message.timestamp.desc()).limit(50).all()
    messages.reverse()  # Reverse to show oldest first

    return render_template("chat.html", 
                         receiverid=userid,
                         receiver=receiver,
                         messages=messages,
                         now=lambda: datetime.now(default_timezone),
                         timedelta=timedelta)

@app.route('/check_notifications', methods=['GET'])
def check_notifications():
    if "userid" not in session:
        return jsonify([])

    current_user = session['userid']

    # Get all users who have sent unread messages
    notifications = db.session.query(
        Message.senderid,
        db.func.count(Message.id).label("unread_count")
    ).filter(
        Message.receiverid == current_user,
        Message.status == 'unread'
    ).group_by(Message.senderid).all()

    # Format the results
    results = [{
        "userid": sender,
        "has_new_message": True,
        "unread_count": unread
    } for sender, unread in notifications]

    return jsonify(results)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for('home'))

@app.route("/delete_selected_messages", methods=["POST"])
def delete_selected_messages():
    if "userid" not in session:
        return jsonify({"error": "Not authenticated"}), 401

    current_user = session['userid']
    data = request.json
    message_ids = data.get('message_ids', [])
    
    try:
        # Delete only messages that belong to the current user (either as sender or receiver)
        Message.query.filter(
            Message.id.in_(message_ids),
            ((Message.senderid == current_user) | (Message.receiverid == current_user))
        ).delete(synchronize_session=False)
        
        db.session.commit()
        return jsonify({"message": "Selected messages deleted successfully"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 400

@app.route('/mark_messages_read', methods=['POST'])
def mark_messages_read():
    if "userid" not in session:
        return jsonify({"error": "Not authenticated"}), 401

    data = request.json
    sender_id = data.get('sender_id')
    
    if not sender_id:
        return jsonify({"error": "Sender ID required"}), 400

    try:
        # Mark all messages from this sender as read
        Message.query.filter_by(
            senderid=sender_id,
            receiverid=session['userid'],
            status='unread'
        ).update({'status': 'read'})
        
        db.session.commit()
        return jsonify({"message": "Messages marked as read"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@app.route("/profile")
def profile():
    if "userid" not in session:
        return redirect(url_for('login'))
    
    user = User.query.filter_by(userid=session['userid']).first()
    return render_template('profile.html', user=user)

@app.route("/update_profile", methods=["POST"])
def update_profile():
    if "userid" not in session:
        return jsonify({"error": "Not authenticated"}), 401
    
    user = User.query.filter_by(userid=session['userid']).first()
    data = request.form
    
    # Verify current password if changing password
    if data.get('new_password'):
        if not data.get('current_password') or data['current_password'] != user.password:
            return jsonify({"error": "Current password is incorrect"}), 400
        user.password = data['new_password']
    
    # Update other fields
    if data.get('name'):
        user.name = data['name']
    if data.get('gender'):
        user.gender = data['gender']
    if data.get('contact'):
        user.contact = data['contact']
    
    # Handle user ID change
    if data.get('new_userid') and data['new_userid'] != user.userid:
        # Check if new user ID is already taken
        if User.query.filter_by(userid=data['new_userid']).first():
            return jsonify({"error": "Username already taken"}), 400
        user.userid = data['new_userid']
        session['userid'] = data['new_userid']  # Update session
    
    # Update theme settings
    if data.get('theme_color'):
        user.theme_color = data['theme_color']
    if data.get('theme_mode'):
        user.theme_mode = data['theme_mode']
    
    # Handle profile photo upload
    if 'profile_photo' in request.files:
        file = request.files['profile_photo']
        if file and allowed_file(file.filename):
            # Delete old profile photo if exists
            if user.profile_photo:
                old_photo_path = os.path.join(app.config['UPLOAD_FOLDER'], user.profile_photo)
                if os.path.exists(old_photo_path):
                    os.remove(old_photo_path)
            
            filename = secure_filename(file.filename)
            filename = f"profile_{session['userid']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{filename}"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            user.profile_photo = filename

    # Handle background photo upload
    if 'background_photo' in request.files:
        file = request.files['background_photo']
        if file and allowed_file(file.filename):
            # Delete old background photo if exists
            if user.background_photo:
                old_photo_path = os.path.join(app.config['UPLOAD_FOLDER'], user.background_photo)
                if os.path.exists(old_photo_path):
                    os.remove(old_photo_path)
            
            filename = secure_filename(file.filename)
            filename = f"background_{session['userid']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{filename}"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            user.background_photo = filename
    
    try:
        db.session.commit()
        return jsonify({"message": "Profile updated successfully"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 400

@app.route("/remove_profile_photo", methods=["POST"])
def remove_profile_photo():
    if "userid" not in session:
        return jsonify({"error": "Not authenticated"}), 401
    
    user = User.query.filter_by(userid=session['userid']).first()
    
    if user.profile_photo:
        # Delete the photo file
        photo_path = os.path.join(app.config['UPLOAD_FOLDER'], user.profile_photo)
        if os.path.exists(photo_path):
            os.remove(photo_path)
        
        # Remove photo reference from database
        user.profile_photo = None
        db.session.commit()
        
        return jsonify({"message": "Profile photo removed successfully"})
    
    return jsonify({"error": "No profile photo found"}), 404

@app.route("/remove_background_photo", methods=["POST"])
def remove_background_photo():
    if "userid" not in session:
        return jsonify({"error": "Not authenticated"}), 401
    
    user = User.query.filter_by(userid=session['userid']).first()
    
    if user.background_photo:
        # Delete the photo file
        photo_path = os.path.join(app.config['UPLOAD_FOLDER'], user.background_photo)
        if os.path.exists(photo_path):
            os.remove(photo_path)
        
        # Remove photo reference from database
        user.background_photo = None
        db.session.commit()
        
        return jsonify({"message": "Background photo removed successfully"})
    
    return jsonify({"error": "No background photo found"}), 404

@app.route("/update_background_theme", methods=["POST"])
def update_background_theme():
    if "userid" not in session:
        return jsonify({"error": "Not authenticated"}), 401
    
    data = request.json
    if not data or 'background_photo' not in data:
        return jsonify({"error": "Background photo name is required"}), 400
    
    user = User.query.filter_by(userid=session['userid']).first()
    user.background_photo = data['background_photo']
    
    try:
        db.session.commit()
        return jsonify({"message": "Background theme updated successfully"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@app.route("/delete_account", methods=["POST"])
def delete_account():
    if "userid" not in session:
        return jsonify({"error": "Not authenticated"}), 401
    
    data = request.json
    confirmation_text = data.get('confirmation_text', '')
    
    if confirmation_text != "Delete My Account":
        return jsonify({"error": "Confirmation text does not match"}), 400
    
    user = User.query.filter_by(userid=session['userid']).first()
    if not user:
        return jsonify({"error": "User not found"}), 404
    
    try:
        # Delete user's messages
        Message.query.filter(
            (Message.senderid == user.userid) | (Message.receiverid == user.userid)
        ).delete()
        
        # Delete user's uploaded files
        if user.profile_photo:
            profile_photo_path = os.path.join(app.config['UPLOAD_FOLDER'], user.profile_photo)
            if os.path.exists(profile_photo_path):
                os.remove(profile_photo_path)
        
        if user.background_photo:
            background_photo_path = os.path.join(app.config['UPLOAD_FOLDER'], user.background_photo)
            if os.path.exists(background_photo_path):
                os.remove(background_photo_path)
        
        # Delete user from database
        db.session.delete(user)
        db.session.commit()
        
        # Clear session
        session.clear()
        
        return jsonify({"message": "Account deleted successfully"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@app.route("/clear_chat_history", methods=["POST"])
def clear_chat_history():
    if "userid" not in session:
        return jsonify({"error": "Not authenticated"}), 401

    data = request.json
    receiver_id = data.get('receiver_id')
    
    if not receiver_id:
        return jsonify({"error": "Receiver ID is required"}), 400

    current_user = session['userid']
    
    try:
        # Delete all messages between the two users
        Message.query.filter(
            ((Message.senderid == current_user) & (Message.receiverid == receiver_id)) |
            ((Message.senderid == receiver_id) & (Message.receiverid == current_user))
        ).delete(synchronize_session=False)
        
        db.session.commit()
        return jsonify({"message": "Chat history cleared successfully"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

# WebSocket Handling
@socketio.on('join')
def on_join(data):
    """Handle user joining a chat room"""
    if 'userid' not in session:
        return
        
    room = data.get('room')
    if not room:
        return
        
    join_room(room)
    
    # Mark messages as read when joining the chat room
    current_user = session['userid']
    other_user = room.replace(current_user, '')
    
    Message.query.filter_by(
        senderid=other_user,
        receiverid=current_user,
        status='unread'
    ).update({'status': 'read'})
    db.session.commit()

@socketio.on('leave')
def on_leave(data):
    """Handle user leaving a chat room"""
    room = data.get('room')
    if room:
        leave_room(room)

@socketio.on('message')
def handle_message(data):
    room = data['room']
    message = data['message']
    sender = data['sender']
    receiver = data['receiver']
    
    # Create new message in database
    new_message = Message(
        senderid=sender,
        receiverid=receiver,
        content=message,
        status='unread'
    )
    db.session.add(new_message)
    db.session.commit()
    
    # Get updated chat list for both sender and receiver
    def get_updated_chat_list(user_id):
        chatted_users = db.session.query(
            User,
            db.func.max(Message.timestamp).label('last_message_time'),
            db.func.count(Message.id).filter(
                (Message.receiverid == user_id) & 
                (Message.status == 'unread')
            ).label('unread_count')
        ).join(
            Message, 
            ((Message.senderid == User.userid) & (Message.receiverid == user_id)) |
            ((Message.receiverid == User.userid) & (Message.senderid == user_id))
        ).filter(
            User.userid != user_id
        ).group_by(
            User.userid,
            User.name,
            User.email,
            User.profile_photo,
            User.gender
        ).order_by(
            db.desc('last_message_time')
        ).all()

        chat_list = []
        for user in chatted_users:
            last_message = Message.query.filter(
                ((Message.senderid == user_id) & (Message.receiverid == user.User.userid)) |
                ((Message.senderid == user.User.userid) & (Message.receiverid == user_id))
            ).order_by(Message.timestamp.desc()).first()

            last_message_content = ""
            last_message_sender = None
            if last_message:
                last_message_content = last_message.content
                last_message_sender = last_message.senderid

            chat_list.append({
                "userid": user.User.userid,
                "name": user.User.name,
                "email": user.User.email,
                "profile_photo": user.User.profile_photo,
                "gender": user.User.gender,
                "last_message": last_message_content[:30] + "..." if last_message_content and len(last_message_content) > 30 else last_message_content,
                "last_message_time": last_message.timestamp.strftime('%Y-%m-%d %H:%M:%S') if last_message else None,
                "last_message_sender": last_message_sender,
                "unread_count": user.unread_count
            })
        return chat_list

    # Get updated chat lists
    sender_chat_list = get_updated_chat_list(sender)
    receiver_chat_list = get_updated_chat_list(receiver)
    
    # Emit the new message to the room
    socketio.emit('message', {
        "id": new_message.id,
        "sender": sender,
        "message": message,
        "timestamp": new_message.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
        "status": "unread"
    }, room=room)
    
    # Emit updated chat lists to both users
    socketio.emit('update_chat_list', {
        "chat_list": sender_chat_list
    }, room=sender)
    
    socketio.emit('update_chat_list', {
        "chat_list": receiver_chat_list
    }, room=receiver)
    
    # Emit unread count update to receiver
    unread_count = Message.query.filter_by(
        senderid=sender,
        receiverid=receiver,
        status='unread'
    ).count()
    
    socketio.emit('unread_count', {
        'sender': sender,
        'count': unread_count
    }, room=receiver)

@socketio.on('mark_read')
def handle_mark_read(data):
    sender = data['sender']
    receiver = data['receiver']
    
    # Mark all messages from sender to receiver as read
    Message.query.filter_by(
        senderid=sender,
        receiverid=receiver,
        status='unread'
    ).update({'status': 'read'})
    
    db.session.commit()
    
    # Emit read status to sender
    socketio.emit('messages_read', {
        'sender': sender,
        'receiver': receiver
    }, room=sender)

@socketio.on('typing')
def handle_typing(data):
    """Handle typing indicator"""
    room = data.get('room')
    sender = data.get('sender')
    receiver = data.get('receiver')
    
    if room and sender and receiver:
        # Emit typing event to the receiver
        socketio.emit('typing', {
            'sender': sender,
            'is_typing': True
        }, room=receiver)

@socketio.on('stop_typing')
def handle_stop_typing(data):
    """Handle stop typing indicator"""
    room = data.get('room')
    sender = data.get('sender')
    receiver = data.get('receiver')
    
    if room and sender and receiver:
        # Emit stop typing event to the receiver
        socketio.emit('typing', {
            'sender': sender,
            'is_typing': False
        }, room=receiver)

@app.route('/check_userid', methods=['POST'])
def check_userid():
    data = request.get_json()
    userid = data.get('userid')
    
    if not userid:
        return jsonify({"error": "Username is required"}), 400
        
    user = User.query.filter_by(userid=userid).first()
    
    if user:
        return jsonify({
            "exists": True,
            "message": "Username already taken"
        })
    else:
        return jsonify({
            "exists": False,
            "message": "Username available"
        })

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
