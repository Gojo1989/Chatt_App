@socketio.on('typing')
def handle_typing(data):
    """Handle typing indicator"""
    room = data.get('room')
    if room:
        socketio.emit('typing', {}, room=room)

@socketio.on('stop_typing')
def handle_stop_typing(data):
    """Handle stop typing indicator"""
    room = data.get('room')
    if room:
        socketio.emit('stop_typing', {}, room=room)