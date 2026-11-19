def get_user(cursor, user_id):
    user_id = user_id.strip()
    cursor.execute("SELECT * FROM users WHERE id = " + user_id)
    return cursor.fetchone()
